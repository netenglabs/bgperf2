package main

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"strings"
	"testing"

	"github.com/osrg/gobgp/v4/pkg/packet/bgp"
)

// These correctly sized communities are from the frozen rrc00 route
// 103.137.98.0/23; the two final EVPN subtype-249 values triggered the old
// observer's treat-as-withdraw. RFC 7606 section 7.14 requires preservation
// of unknown types/subtypes rather than treating them as an UPDATE error.
func sourceCommunities(t *testing.T) []byte {
	t.Helper()
	data, err := hex.DecodeString("0002b0790000045c0202000206f9232a06f927110000000006f92af800000000")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestUnknownEVPNCommunitiesPreserveEveryByteAndNeighbors(t *testing.T) {
	data := sourceCommunities(t)
	var serialized []byte
	for offset := 0; offset < len(data); offset += 8 {
		community, err := bgp.ParseExtended(data[offset:])
		if err != nil {
			t.Fatalf("valid unknown extended community rejected: %v", err)
		}
		value, err := community.Serialize()
		if err != nil {
			t.Fatal(err)
		}
		serialized = append(serialized, value...)
	}
	if !bytes.Equal(data, serialized) {
		t.Fatalf("community bytes changed: %x != %x", data, serialized)
	}
	for _, subtype := range []byte{249, 250, 255} {
		encoded := []byte{6, subtype, 1, 2, 3, 4, 5, 6}
		community, err := bgp.ParseExtended(encoded)
		if err != nil {
			t.Fatal(err)
		}
		// The constructor owns its seven bytes; reusing the packet buffer
		// must not change the decoded value.
		encoded[2] = 99
		value, err := community.Serialize()
		if err != nil || value[2] != 1 {
			t.Fatalf("opaque value aliases packet storage: %x %v", value, err)
		}
	}
}

func TestUnknownEVPNDoesNotWithdrawIPv4RouteOrResetSession(t *testing.T) {
	buf := &syncBuffer{}
	p, done := establish(t, buf)
	waitFor(t, buf, " established ")
	var communities []bgp.ExtendedCommunityInterface
	data := sourceCommunities(t)
	for offset := 0; offset < len(data); offset += 8 {
		communities = append(communities, bgp.NewUnknownExtended(bgp.ExtendedCommunityAttrType(data[offset]), data[offset+1:offset+8]))
	}
	path := append(attrs(t, 1000), bgp.NewPathAttributeExtendedCommunities(communities))
	p.send(bgp.NewBGPUpdateMessage(nil, path, nlris(t, "10.8.0.0/24")))
	if e := sendKeepsSession(t, p, buf); e != "E 2 3" {
		t.Fatalf("End-of-RIB %q, want E 2 3: %s", e, buf.String())
	}
	p.nc.Close()
	<-done
	if strings.Contains(buf.String(), "treat-as-withdraw") {
		t.Fatalf("unknown subtype withdrawn: %s", buf.String())
	}
}

func TestMalformedExtendedCommunityLengthStillWithdraws(t *testing.T) {
	buf := &syncBuffer{}
	p, done := establish(t, buf)
	waitFor(t, buf, " established ")
	p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, 1000), nlris(t, "10.1.0.0/24")))
	var attributes []byte
	for _, a := range attrs(t, 1000) {
		value, err := a.Serialize()
		if err != nil {
			t.Fatal(err)
		}
		attributes = append(attributes, value...)
	}
	attributes = append(attributes, 0xc0, 16, 7, 6, 249, 1, 2, 3, 4, 5) // Seven bytes, not a multiple of eight.
	body := []byte{0, 0}
	body = binary.BigEndian.AppendUint16(body, uint16(len(attributes)))
	body = append(body, attributes...)
	body = append(body, 24, 10, 1, 0)
	p.sendRaw(rawUpdate(body))
	if e := sendKeepsSession(t, p, buf); e != "E 1 4" {
		t.Fatalf("malformed EC was not withdrawn: %q %s", e, buf.String())
	}
	p.nc.Close()
	<-done
	if !strings.Contains(buf.String(), "treat-as-withdraw") {
		t.Fatalf("malformed EC handling not recorded: %s", buf.String())
	}
}
