package main

import (
	"bufio"
	"bytes"
	"io"
	"net"
	"net/netip"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/osrg/gobgp/v4/pkg/packet/bgp"
)

// syncBuffer is a bytes.Buffer the test can read while the sink writes.
type syncBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}

func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

func testSink(buf io.Writer) *sink {
	return &sink{
		cfg: config{
			localAS: localAS, peerAS: 1000,
			routerID:  netip.MustParseAddr("10.10.0.3"),
			localAddr: netip.MustParseAddr("10.10.0.3"),
			peerAddr:  netip.MustParseAddr("10.10.0.2"),
			holdTime:  90, hostname: "test",
		},
		log: newEventLog(buf, monotonicNS),
	}
}

// peer is the target's end of the pipe.
type peer struct {
	t  *testing.T
	nc net.Conn
	r  *bufio.Reader
}

func (p *peer) send(m *bgp.BGPMessage) {
	p.t.Helper()
	b, err := m.Serialize()
	if err != nil {
		p.t.Fatal(err)
	}
	if _, err := p.nc.Write(b); err != nil {
		p.t.Fatal(err)
	}
}

func (p *peer) sendRaw(b []byte) {
	p.t.Helper()
	if _, err := p.nc.Write(b); err != nil {
		p.t.Fatal(err)
	}
}

func (p *peer) recv() *bgp.BGPMessage {
	p.t.Helper()
	p.nc.SetReadDeadline(time.Now().Add(5 * time.Second))
	h := make([]byte, bgp.BGP_HEADER_LENGTH)
	if _, err := io.ReadFull(p.r, h); err != nil {
		p.t.Fatal(err)
	}
	n := int(h[16])<<8 | int(h[17])
	body := make([]byte, n-bgp.BGP_HEADER_LENGTH)
	if _, err := io.ReadFull(p.r, body); err != nil {
		p.t.Fatal(err)
	}
	m, err := bgp.ParseBGPMessage(append(h, body...))
	if err != nil {
		p.t.Fatal(err)
	}
	return m
}

func targetOpen(t *testing.T, as uint32) *bgp.BGPMessage {
	m, err := bgp.NewBGPOpenMessage(uint16(as), 90, netip.MustParseAddr("10.10.0.2"),
		[]bgp.OptionParameterInterface{bgp.NewOptionParameterCapability([]bgp.ParameterCapabilityInterface{
			bgp.NewCapMultiProtocol(bgp.RF_IPv4_UC),
			bgp.NewCapFourOctetASNumber(as),
		})})
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func establish(t *testing.T, buf io.Writer) (*peer, chan struct{}) {
	t.Helper()
	a, b := net.Pipe()
	s := testSink(buf)
	done := make(chan struct{})
	go func() { s.serve(a, false); close(done) }()
	p := &peer{t: t, nc: b, r: bufio.NewReader(b)}

	open := p.recv()
	o, ok := open.Body.(*bgp.BGPOpen)
	if !ok {
		t.Fatalf("expected OPEN, got %d", open.Header.Type)
	}
	if o.MyAS != localAS || o.HoldTime != 90 {
		t.Fatalf("OPEN: AS %d hold %d", o.MyAS, o.HoldTime)
	}
	p.send(targetOpen(t, 1000))
	if m := p.recv(); m.Header.Type != bgp.BGP_MSG_KEEPALIVE {
		t.Fatalf("expected KEEPALIVE, got %d", m.Header.Type)
	}
	p.send(bgp.NewBGPKeepAliveMessage())
	return p, done
}

func waitFor(t *testing.T, buf *syncBuffer, want string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(buf.String(), want) {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("log never contained %q:\n%s", want, buf.String())
}

func kinds(log string) []string {
	var out []string
	for _, l := range strings.Split(strings.TrimSpace(log), "\n") {
		f := strings.Fields(l)
		out = append(out, f[0]+" "+strings.Join(f[2:], " "))
	}
	return out
}

func TestOpenAdvertisesWhatTheGoBGPMonitorDid(t *testing.T) {
	// Captured from bgperf/gobgp 4.9.0 as the monitor (AS 1001): route
	// refresh, FQDN, extended message, IPv4 unicast, 4-octet AS, extended
	// next hop. Only the FQDN's hostname differs between containers.
	s := testSink(io.Discard)
	b, err := s.openMessage().Serialize()
	if err != nil {
		t.Fatal(err)
	}
	m, _ := bgp.ParseBGPMessage(b)
	var codes []bgp.BGPCapabilityCode
	for _, p := range m.Body.(*bgp.BGPOpen).OptParams {
		for _, c := range p.(*bgp.OptionParameterCapability).Capability {
			codes = append(codes, c.Code())
		}
	}
	want := []bgp.BGPCapabilityCode{2, 73, 6, 1, 65, 5}
	if len(codes) != len(want) {
		t.Fatalf("capabilities %v, want %v", codes, want)
	}
	for i := range want {
		if codes[i] != want[i] {
			t.Fatalf("capabilities %v, want %v", codes, want)
		}
	}
	// The captured OPEN, with the FQDN's hostname replaced by "test".
	captured := "ffffffffffffffffffffffffffffffff" + "003f" + "01" + "04" + "03e9" + "005a" + "0a0a0003" +
		"22" + "02" + "20" + "0200" + "4906" + "04" + "74657374" + "00" + "0600" + "010400010001" +
		"410400" + "0003e9" + "0506000100010002"
	if got := hexOf(b); got != captured {
		t.Fatalf("OPEN differs from the GoBGP monitor's:\n got %s\nwant %s", got, captured)
	}
}

func hexOf(b []byte) string {
	const digits = "0123456789abcdef"
	out := make([]byte, 0, 2*len(b))
	for _, c := range b {
		out = append(out, digits[c>>4], digits[c&15])
	}
	return string(out)
}

func TestSessionCountsAndEndOfRIB(t *testing.T) {
	buf := &syncBuffer{}
	p, done := establish(t, buf)
	waitFor(t, buf, " established inbound 1 10.10.0.2 1000 hold=90 four_byte=true extended=false")

	p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, 1000), nlris(t, "10.1.0.0/24", "10.2.0.0/24")))
	p.send(bgp.NewBGPUpdateMessage(nlris(t, "10.1.0.0/24"), nil, nil))
	p.send(bgp.NewEndOfRib(bgp.RF_IPv4_UC))
	waitFor(t, buf, "\nE ")
	p.send(bgp.NewBGPNotificationMessage(bgp.BGP_ERROR_CEASE, bgp.BGP_ERROR_SUB_ADMINISTRATIVE_SHUTDOWN, nil))
	<-done

	got := kinds(buf.String())
	want := []string{
		"S connected inbound 1 pipe",
		"S open_sent inbound 1",
		"S established inbound 1 10.10.0.2 1000 hold=90 four_byte=true extended=false",
		"C 0 0 0",
		// Two UPDATEs before the End-of-RIB: they may or may not coalesce,
		// so only the last state before it is asserted below.
	}
	for i, w := range want {
		if got[i] != w {
			t.Fatalf("line %d: got %q want %q\n%s", i, got[i], w, buf.String())
		}
	}
	tail := got[len(got)-5:]
	wantTail := []string{
		"C 1 2 0",
		"C 1 3 1",
		"E 1 3",
		"C 0 0 0",
		"S down inbound 1 received notification 6/2",
	}
	for i, w := range wantTail {
		if tail[i] != w {
			t.Fatalf("tail %d: got %q want %q\n%s", i, tail[i], w, buf.String())
		}
	}
}

func TestMalformedUpdateResetsTheSession(t *testing.T) {
	// GoBGP with treat-as-withdraw off -- the monitor's config -- resets the
	// session on an UPDATE that fails validation. An announcement with no
	// ORIGIN is one.
	buf := &syncBuffer{}
	p, done := establish(t, buf)
	waitFor(t, buf, " established ")
	p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, 1000), nlris(t, "10.1.0.0/24")))
	p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, 1000)[1:], nlris(t, "10.2.0.0/24")))
	m := p.recv()
	n, ok := m.Body.(*bgp.BGPNotification)
	if !ok || n.ErrorCode != bgp.BGP_ERROR_UPDATE_MESSAGE_ERROR || n.ErrorSubcode != bgp.BGP_ERROR_SUB_MISSING_WELL_KNOWN_ATTRIBUTE {
		t.Fatalf("expected notification 3/3, got %+v", m.Body)
	}
	p.nc.Close()
	<-done
	log := buf.String()
	if !strings.Contains(log, "\nM ") {
		t.Fatalf("the refused UPDATE was not logged:\n%s", log)
	}
	got := kinds(log)
	if got[len(got)-2] != "C 0 0 0" || !strings.HasPrefix(got[len(got)-1], "S down inbound 1 sent notification 3/3") {
		t.Fatalf("session did not end as a reset:\n%s", log)
	}
	// The count held before the reset is in the log, not overwritten.
	if !strings.Contains(log, " 1 1 0\n") {
		t.Fatalf("the count before the reset was lost:\n%s", log)
	}
}

func TestWrongPeerASIsRefused(t *testing.T) {
	a, b := net.Pipe()
	buf := &syncBuffer{}
	s := testSink(buf)
	done := make(chan struct{})
	go func() { s.serve(a, false); close(done) }()
	p := &peer{t: t, nc: b, r: bufio.NewReader(b)}
	p.recv()
	p.send(targetOpen(t, 4242))
	m := p.recv()
	if n, ok := m.Body.(*bgp.BGPNotification); !ok || n.ErrorCode != bgp.BGP_ERROR_OPEN_MESSAGE_ERROR || n.ErrorSubcode != bgp.BGP_ERROR_SUB_BAD_PEER_AS {
		t.Fatalf("expected notification 2/2, got %+v", m.Body)
	}
	p.nc.Close()
	<-done
	if strings.Contains(buf.String(), " established ") {
		t.Fatal("a session with the wrong AS was established")
	}
}

func TestTruncatedMessageEndsTheSession(t *testing.T) {
	buf := &syncBuffer{}
	p, done := establish(t, buf)
	waitFor(t, buf, " established ")
	b, _ := bgp.NewBGPUpdateMessage(nil, attrs(t, 1000), nlris(t, "10.1.0.0/24")).Serialize()
	p.sendRaw(b[:len(b)-3])
	p.nc.Close()
	<-done
	if !strings.Contains(buf.String(), "S ") || !strings.Contains(buf.String(), " down inbound ") {
		t.Fatalf("no down line:\n%s", buf.String())
	}
}

func TestCollisionKeepsOneConnection(t *testing.T) {
	// The sink's identifier (10.10.0.3) is higher than the target's
	// (10.10.0.2), so by RFC 4271 6.8 the outbound connection survives.
	s := testSink(io.Discard)
	in := &conn{outbound: false, remoteID: netip.MustParseAddr("10.10.0.2")}
	out := &conn{outbound: true, remoteID: netip.MustParseAddr("10.10.0.2")}
	a, b := net.Pipe()
	in.nc = a
	go io.Copy(io.Discard, b)
	if !s.enterOpenConfirm(in) {
		t.Fatal("first connection refused")
	}
	if !s.enterOpenConfirm(out) {
		t.Fatal("the outbound connection should win")
	}
	if !s.wasDropped(in) {
		t.Fatal("the inbound connection should have been dropped")
	}
	if s.establish(in) {
		t.Fatal("a dropped connection was established")
	}
	if !s.establish(out) {
		t.Fatal("the kept connection could not establish")
	}

	// And the other way round: a lower identifier keeps the inbound one.
	s = testSink(io.Discard)
	s.cfg.routerID = netip.MustParseAddr("10.10.0.1")
	in = &conn{outbound: false, remoteID: netip.MustParseAddr("10.10.0.2")}
	out = &conn{outbound: true, remoteID: netip.MustParseAddr("10.10.0.2")}
	if !s.enterOpenConfirm(in) {
		t.Fatal("first connection refused")
	}
	if s.enterOpenConfirm(out) {
		t.Fatal("the outbound connection should lose")
	}
}

func TestEqualIdentifiersFallBackToTheAS(t *testing.T) {
	// RFC 6286 2.3: equal identifiers between ASes -- the larger AS keeps
	// the connection it initiated. The sink is AS 1001, the target 1000.
	s := testSink(io.Discard)
	same := s.cfg.routerID
	in := &conn{outbound: false, remoteID: same}
	out := &conn{outbound: true, remoteID: same}
	a, b := net.Pipe()
	in.nc = a
	go io.Copy(io.Discard, b)
	if !s.enterOpenConfirm(in) || !s.enterOpenConfirm(out) {
		t.Fatal("the larger AS keeps its outbound connection")
	}
	if !s.wasDropped(in) {
		t.Fatal("the inbound connection should have been dropped")
	}
}

func TestInternalPeerWithOurIdentifierIsRefused(t *testing.T) {
	s := testSink(io.Discard)
	s.cfg.peerAS = localAS
	m, err := bgp.NewBGPOpenMessage(localAS, 90, s.cfg.routerID,
		[]bgp.OptionParameterInterface{bgp.NewOptionParameterCapability([]bgp.ParameterCapabilityInterface{
			bgp.NewCapFourOctetASNumber(localAS)})})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.checkOpen(m); err == nil || !strings.Contains(err.Error(), "notification 2/3") {
		t.Fatalf("expected notification 2/3, got %v", err)
	}
}

func TestConnectScheduleIsGoBGPs(t *testing.T) {
	retry := 10 * time.Second
	// The first attempt waits 1.5 to 2 s, not nothing and not a whole retry.
	if got := connectDelay(0, retry, 0); got != 1500*time.Millisecond {
		t.Fatalf("first attempt, r=0: %v", got)
	}
	if got := connectDelay(0, retry, 0.999999); got > 2*time.Second || got < 1999*time.Millisecond {
		t.Fatalf("first attempt, r=1: %v", got)
	}
	// Later ones 7.5 to 10 s.
	if got := connectDelay(1, retry, 0); got != 7500*time.Millisecond {
		t.Fatalf("second attempt, r=0: %v", got)
	}
	if got := connectDelay(5, retry, 0.5); got != 8750*time.Millisecond {
		t.Fatalf("later attempt, r=0.5: %v", got)
	}
	// A retry below GoBGP's minimum is floored at it.
	if got := connectDelay(3, time.Second, 0); got != 1500*time.Millisecond {
		t.Fatalf("short retry: %v", got)
	}
}
