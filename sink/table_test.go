package main

import (
	"net/netip"
	"testing"

	"github.com/osrg/gobgp/v4/pkg/packet/bgp"
)

func nlris(t *testing.T, prefixes ...string) []bgp.PathNLRI {
	t.Helper()
	var out []bgp.PathNLRI
	for _, p := range prefixes {
		n, err := bgp.NewIPAddrPrefix(netip.MustParsePrefix(p))
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, bgp.PathNLRI{NLRI: n})
	}
	return out
}

func attrs(t *testing.T, asPath ...uint32) []bgp.PathAttributeInterface {
	t.Helper()
	nh, err := bgp.NewPathAttributeNextHop(netip.MustParseAddr("10.0.0.1"))
	if err != nil {
		t.Fatal(err)
	}
	return []bgp.PathAttributeInterface{
		bgp.NewPathAttributeOrigin(0),
		bgp.NewPathAttributeAsPath([]bgp.AsPathParamInterface{
			bgp.NewAs4PathParam(bgp.BGP_ASPATH_ATTR_TYPE_SEQ, asPath)}),
		nh,
	}
}

// roundTrip serialises and re-parses an UPDATE, so every test counts what the
// parser hands the sink off the wire rather than a struct built in memory.
func roundTrip(t *testing.T, m *bgp.BGPMessage) *bgp.BGPUpdate {
	t.Helper()
	b, err := m.Serialize()
	if err != nil {
		t.Fatal(err)
	}
	p, err := bgp.ParseBGPMessage(b)
	if err != nil {
		t.Fatal(err)
	}
	return p.Body.(*bgp.BGPUpdate)
}

func announce(t *testing.T, as []uint32, prefixes ...string) *bgp.BGPUpdate {
	return roundTrip(t, bgp.NewBGPUpdateMessage(nil, attrs(t, as...), nlris(t, prefixes...)))
}

func withdraw(t *testing.T, prefixes ...string) *bgp.BGPUpdate {
	return roundTrip(t, bgp.NewBGPUpdateMessage(nlris(t, prefixes...), nil, nil))
}

const localAS = 1001

func TestAnnounceWithdrawReplace(t *testing.T) {
	tb := newTable(localAS, netip.Addr{})
	r := tb.apply(announce(t, []uint32{1000}, "10.1.0.0/24", "10.2.0.0/24", "10.3.0.0/24"), false)
	if r.announced != 3 || tb.accepted != 3 {
		t.Fatalf("announce: %+v accepted=%d", r, tb.accepted)
	}
	// A re-announcement replaces: one path per prefix without ADD-PATH.
	tb.apply(announce(t, []uint32{1000, 65000}, "10.1.0.0/24"), false)
	if tb.accepted != 3 {
		t.Fatalf("replace changed the count: %d", tb.accepted)
	}
	r = tb.apply(withdraw(t, "10.1.0.0/24", "10.9.0.0/24"), false)
	if r.withdrawn != 2 || tb.accepted != 2 {
		t.Fatalf("withdraw: %+v accepted=%d", r, tb.accepted)
	}
	// Withdrawing what is not held changes nothing.
	tb.apply(withdraw(t, "10.9.0.0/24"), false)
	if tb.accepted != 2 || len(tb.held) != 2 {
		t.Fatalf("withdrawing an unheld prefix: accepted=%d held=%d", tb.accepted, len(tb.held))
	}
}

func TestPrefixIdentityIsAddressAndLength(t *testing.T) {
	tb := newTable(localAS, netip.Addr{})
	tb.apply(announce(t, []uint32{1000}, "10.0.0.0/8", "10.0.0.0/16", "10.0.0.0/24", "0.0.0.0/0"), false)
	if tb.accepted != 4 {
		t.Fatalf("same address, different lengths must be different prefixes: %d", tb.accepted)
	}
}

func TestSameMessageAnnounceAndWithdrawEndsWithdrawn(t *testing.T) {
	// GoBGP's order is NLRI, MP_REACH, withdrawn, MP_UNREACH.
	tb := newTable(localAS, netip.Addr{})
	u := roundTrip(t, bgp.NewBGPUpdateMessage(nlris(t, "10.1.0.0/24"), attrs(t, 1000), nlris(t, "10.1.0.0/24")))
	tb.apply(u, false)
	if tb.accepted != 0 {
		t.Fatalf("expected GoBGP's reading (withdrawn), got %d", tb.accepted)
	}
}

func TestMPReachAndUnreachForIPv4(t *testing.T) {
	tb := newTable(localAS, netip.Addr{})
	reach, err := bgp.NewPathAttributeMpReachNLRI(bgp.RF_IPv4_UC, nlris(t, "10.1.0.0/24", "10.2.0.0/24"),
		netip.MustParseAddr("10.0.0.1"))
	if err != nil {
		t.Fatal(err)
	}
	a := attrs(t, 1000)[:2]
	tb.apply(roundTrip(t, bgp.NewBGPUpdateMessage(nil, append(a, reach), nil)), false)
	if tb.accepted != 2 {
		t.Fatalf("MP_REACH: %d", tb.accepted)
	}
	unreach, err := bgp.NewPathAttributeMpUnreachNLRI(bgp.RF_IPv4_UC, nlris(t, "10.1.0.0/24"))
	if err != nil {
		t.Fatal(err)
	}
	tb.apply(roundTrip(t, bgp.NewBGPUpdateMessage(nil, []bgp.PathAttributeInterface{unreach}, nil)), false)
	if tb.accepted != 1 {
		t.Fatalf("MP_UNREACH: %d", tb.accepted)
	}
}

func TestMPReachWithIPv6NextHop(t *testing.T) {
	// The OPEN advertises extended next hop for IPv4 unicast over IPv6, as
	// the GoBGP monitor's did, so a target may send this.
	tb := newTable(localAS, netip.Addr{})
	reach, err := bgp.NewPathAttributeMpReachNLRI(bgp.RF_IPv4_UC, nlris(t, "10.1.0.0/24"),
		netip.MustParseAddr("2001:db8::1"))
	if err != nil {
		t.Fatal(err)
	}
	tb.apply(roundTrip(t, bgp.NewBGPUpdateMessage(nil, append(attrs(t, 1000)[:2], reach), nil)), false)
	if tb.accepted != 1 {
		t.Fatalf("IPv6 next hop: %d", tb.accepted)
	}
}

func TestEndOfRIB(t *testing.T) {
	tb := newTable(localAS, netip.Addr{})
	tb.apply(announce(t, []uint32{1000}, "10.1.0.0/24"), false)
	r := tb.apply(roundTrip(t, bgp.NewEndOfRib(bgp.RF_IPv4_UC)), false)
	if !r.eor || tb.accepted != 1 {
		t.Fatalf("EoR: %+v accepted=%d", r, tb.accepted)
	}
	r = tb.apply(roundTrip(t, bgp.NewEndOfRib(bgp.RF_IPv6_UC)), false)
	if r.eor {
		t.Fatal("an IPv6 End-of-RIB is not the IPv4 one")
	}
}

func TestOwnASLoopIsHeldButNotAccepted(t *testing.T) {
	tb := newTable(localAS, netip.Addr{})
	tb.apply(announce(t, []uint32{1000, localAS, 7}, "10.1.0.0/24"), false)
	if tb.accepted != 0 || len(tb.held) != 1 {
		t.Fatalf("looped path: accepted=%d held=%d", tb.accepted, len(tb.held))
	}
	// Replaced by a clean path: now accepted.
	tb.apply(announce(t, []uint32{1000}, "10.1.0.0/24"), false)
	if tb.accepted != 1 {
		t.Fatalf("clean replacement: %d", tb.accepted)
	}
	// Replaced by a looped one again: rejected again.
	tb.apply(announce(t, []uint32{1000, localAS}, "10.1.0.0/24"), false)
	if tb.accepted != 0 {
		t.Fatalf("looped replacement: %d", tb.accepted)
	}
	// Withdrawing a rejected path does not drive the count negative.
	tb.apply(withdraw(t, "10.1.0.0/24"), false)
	if tb.accepted != 0 || len(tb.held) != 0 {
		t.Fatalf("withdrawn rejected path: accepted=%d held=%d", tb.accepted, len(tb.held))
	}
}

func TestOwnASInASSetRejects(t *testing.T) {
	tb := newTable(localAS, netip.Addr{})
	a := attrs(t, 1000)
	a[1] = bgp.NewPathAttributeAsPath([]bgp.AsPathParamInterface{
		bgp.NewAs4PathParam(bgp.BGP_ASPATH_ATTR_TYPE_SEQ, []uint32{1000}),
		bgp.NewAs4PathParam(bgp.BGP_ASPATH_ATTR_TYPE_SET, []uint32{5, localAS}),
	})
	tb.apply(roundTrip(t, bgp.NewBGPUpdateMessage(nil, a, nlris(t, "10.1.0.0/24"))), false)
	if tb.accepted != 0 {
		t.Fatalf("own AS in an AS_SET: %d", tb.accepted)
	}
}

func TestFullTableScale(t *testing.T) {
	// A million distinct /24s, in UPDATEs of 500 -- the shape of the MRT cell.
	if testing.Short() {
		t.Skip()
	}
	tb := newTable(localAS, netip.Addr{})
	a := attrs(t, 1000)
	var batch []bgp.PathNLRI
	n := 0
	for i := 0; i < 1<<20; i++ {
		p := netip.PrefixFrom(netip.AddrFrom4([4]byte{byte(1 + i>>16), byte(i >> 8), byte(i), 0}), 24)
		nl, _ := bgp.NewIPAddrPrefix(p)
		batch = append(batch, bgp.PathNLRI{NLRI: nl})
		if len(batch) == 500 {
			tb.apply(&bgp.BGPUpdate{PathAttributes: a, NLRI: batch}, false)
			n += len(batch)
			batch = nil
		}
	}
	tb.apply(&bgp.BGPUpdate{PathAttributes: a, NLRI: batch}, false)
	n += len(batch)
	if tb.accepted != n {
		t.Fatalf("accepted %d, sent %d", tb.accepted, n)
	}
}

func TestOwnOriginatorIDRejectsOnIBGPOnly(t *testing.T) {
	rid := netip.MustParseAddr("10.10.0.3")
	orig, err := bgp.NewPathAttributeOriginatorId(rid)
	if err != nil {
		t.Fatal(err)
	}
	u := func() *bgp.BGPUpdate {
		return roundTrip(t, bgp.NewBGPUpdateMessage(nil, append(attrs(t, 1000), orig), nlris(t, "10.1.0.0/24")))
	}
	ibgp := newTable(localAS, rid)
	ibgp.apply(u(), false)
	if ibgp.accepted != 0 || len(ibgp.held) != 1 {
		t.Fatalf("iBGP, own ORIGINATOR_ID: accepted=%d held=%d", ibgp.accepted, len(ibgp.held))
	}
	ebgp := newTable(localAS, netip.Addr{})
	ebgp.apply(u(), false)
	if ebgp.accepted != 1 {
		t.Fatalf("eBGP ignores ORIGINATOR_ID: accepted=%d", ebgp.accepted)
	}
}

func TestApplyAsWithdraw(t *testing.T) {
	// Treat-as-withdraw withdraws what the UPDATE announces, NLRI and
	// MP_REACH alike, and reads none of its attributes: an own-AS loop on a
	// treated UPDATE neither holds nor rejects anything.
	tb := newTable(localAS, netip.Addr{})
	tb.apply(announce(t, []uint32{1000}, "10.1.0.0/24", "10.2.0.0/24"), false)
	r := tb.apply(announce(t, []uint32{1000, localAS}, "10.1.0.0/24", "10.9.0.0/24"), true)
	if r.announced != 0 || r.withdrawn != 2 || tb.accepted != 1 || len(tb.held) != 1 {
		t.Fatalf("got %+v, accepted %d, held %d", r, tb.accepted, len(tb.held))
	}
	reach, err := bgp.NewPathAttributeMpReachNLRI(bgp.RF_IPv4_UC, nlris(t, "10.2.0.0/24"), netip.MustParseAddr("10.0.0.1"))
	if err != nil {
		t.Fatal(err)
	}
	tb.apply(roundTrip(t, bgp.NewBGPUpdateMessage(nil, append(attrs(t, 1000)[:2], reach), nil)), true)
	if tb.accepted != 0 || len(tb.held) != 0 {
		t.Fatalf("MP_REACH was not withdrawn: accepted %d, held %d", tb.accepted, len(tb.held))
	}
}
