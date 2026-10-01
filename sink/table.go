package main

// The sink's count, and the only thing in it that has to agree with GoBGP.
//
// bgperf2 read exactly one number from the GoBGP monitor:
// `afi_safis[0].state.accepted`, which is `AdjRib.Accepted()` for IPv4
// unicast (`internal/pkg/table/adj.go` at v4.9.0). This file reproduces what
// moves that counter, rule for rule, and nothing else:
//
//   - one path per prefix, because the monitor negotiates no ADD-PATH, so a
//     re-announcement replaces rather than adds (`AdjRib.Update` matches on
//     the remote path ID, which is always 0 here);
//   - a withdrawal of a prefix that is not held changes nothing;
//   - within one UPDATE the order is NLRI, MP_REACH, withdrawn, MP_UNREACH
//     (`table.ProcessMessage`), so a prefix both announced and withdrawn in
//     the same message ends withdrawn -- GoBGP's reading, kept even where
//     RFC 7606 would read it the other way, because agreement is the point;
//   - a path whose AS_PATH contains the monitor's own AS is held but
//     *rejected*, and a rejected path is not accepted (`hasOwnASLoop` with
//     allow-own-as 0 and no confederation, which is the monitor's config);
//   - on an iBGP session only, a path whose ORIGINATOR_ID is the monitor's
//     router ID is rejected the same way (RFC 4456 8, `peer.handleUpdate`).
//     gen_conf() always peers the monitor over eBGP, but a hand-written `-f`
//     scenario need not. v4.9.0 has no CLUSTER_LIST rule on this path;
//   - End-of-RIB is not a path and moves nothing.
//
// What GoBGP does after that -- best-path selection, policy, the global RIB --
// never reached `accepted`, and is exactly the work this sink exists not to do.

import (
	"encoding/binary"
	"net/netip"

	"github.com/osrg/gobgp/v4/pkg/packet/bgp"
)

// prefixKey packs an IPv4 prefix into one word: the masked address in the high
// 32 bits and the length in the low 8. A full table is about a million of
// these, so the key is a word rather than a netip.Prefix, which is three.
type prefixKey uint64

func keyOf(p netip.Prefix) (prefixKey, bool) {
	if !p.Addr().Is4() || p.Bits() < 0 {
		return 0, false
	}
	a := p.Masked().Addr().As4()
	return prefixKey(uint64(binary.BigEndian.Uint32(a[:]))<<8 | uint64(p.Bits())), true
}

// table is one session's adj-RIB-in, reduced to what `accepted` needs: which
// prefixes are held, and whether each was rejected.
type table struct {
	localAS uint32
	// routerID is set only on an iBGP session, where ORIGINATOR_ID is checked.
	routerID netip.Addr
	// held maps a prefix to whether its path was rejected.
	held     map[prefixKey]bool
	accepted int
}

// newTable starts an empty adj-RIB-in. ibgpRouterID is the sink's router ID
// on an iBGP session and the zero Addr otherwise.
func newTable(localAS uint32, ibgpRouterID netip.Addr) *table {
	return &table{localAS: localAS, routerID: ibgpRouterID, held: make(map[prefixKey]bool)}
}

// applied says what one UPDATE did, for the log and for the tests.
type applied struct {
	announced int // prefixes announced in the message, held or replaced
	withdrawn int // prefixes withdrawn in the message, whether held or not
	eor       bool
}

func (t *table) announce(p netip.Prefix, rejected bool) {
	k, ok := keyOf(p)
	if !ok {
		return
	}
	old, held := t.held[k]
	switch {
	case !held:
		if !rejected {
			t.accepted++
		}
	case old && !rejected:
		t.accepted++
	case !old && rejected:
		t.accepted--
	}
	t.held[k] = rejected
}

func (t *table) withdraw(p netip.Prefix) {
	k, ok := keyOf(p)
	if !ok {
		return
	}
	if rejected, held := t.held[k]; held {
		if !rejected {
			t.accepted--
		}
		delete(t.held, k)
	}
}

func prefixOf(n bgp.NLRI) (netip.Prefix, bool) {
	if p, ok := n.(*bgp.IPAddrPrefix); ok {
		return p.Prefix, true
	}
	return netip.Prefix{}, false
}

// ownASLoop is GoBGP's hasOwnASLoop with allow-own-as 0 and confederations
// off: any occurrence of the local AS, in a sequence or a set, rejects.
func ownASLoop(localAS uint32, attrs []bgp.PathAttributeInterface) bool {
	for _, a := range attrs {
		asPath, ok := a.(*bgp.PathAttributeAsPath)
		if !ok {
			continue
		}
		for _, param := range asPath.Value {
			for _, as := range param.GetAS() {
				if as == localAS {
					return true
				}
			}
		}
	}
	return false
}

// originatedHere is GoBGP's iBGP-only ORIGINATOR_ID check.
func (t *table) originatedHere(attrs []bgp.PathAttributeInterface) bool {
	if !t.routerID.IsValid() {
		return false
	}
	for _, a := range attrs {
		if o, ok := a.(*bgp.PathAttributeOriginatorId); ok {
			return o.Value == t.routerID
		}
	}
	return false
}

// apply folds one validated UPDATE into the table.
func (t *table) apply(u *bgp.BGPUpdate) applied {
	var r applied
	if eor, family := u.IsEndOfRib(); eor {
		r.eor = family == bgp.RF_IPv4_UC
		return r
	}
	var reach *bgp.PathAttributeMpReachNLRI
	var unreach *bgp.PathAttributeMpUnreachNLRI
	for _, a := range u.PathAttributes {
		switch a := a.(type) {
		case *bgp.PathAttributeMpReachNLRI:
			reach = a
		case *bgp.PathAttributeMpUnreachNLRI:
			unreach = a
		}
	}
	rejected := ownASLoop(t.localAS, u.PathAttributes) || t.originatedHere(u.PathAttributes)

	for _, n := range u.NLRI {
		if p, ok := prefixOf(n.NLRI); ok {
			t.announce(p, rejected)
			r.announced++
		}
	}
	if reach != nil && bgp.NewFamily(reach.AFI, reach.SAFI) == bgp.RF_IPv4_UC {
		for _, n := range reach.Value {
			if p, ok := prefixOf(n.NLRI); ok {
				t.announce(p, rejected)
				r.announced++
			}
		}
	}
	for _, n := range u.WithdrawnRoutes {
		if p, ok := prefixOf(n.NLRI); ok {
			t.withdraw(p)
			r.withdrawn++
		}
	}
	if unreach != nil && bgp.NewFamily(unreach.AFI, unreach.SAFI) == bgp.RF_IPv4_UC {
		for _, n := range unreach.Value {
			if p, ok := prefixOf(n.NLRI); ok {
				t.withdraw(p)
				r.withdrawn++
			}
		}
	}
	return r
}
