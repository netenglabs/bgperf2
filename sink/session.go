package main

// One BGP peer, held as the monitor held it, and nothing more.
//
// The sink speaks what the monitor role needs. That means IPv4 unicast,
// 4-octet AS, and the same OPEN the GoBGP monitor sent, read off the wire from
// `bgperf/gobgp` 4.9.0 rather than assumed. It initiates and accepts, as gobgpd
// did, because targets differ in which side opens. A connection collision is
// resolved by RFC 4271 6.8, so both ends drop the same connection. Keepalives
// have their own goroutine, so a saturated reader cannot let the peer's hold
// timer expire. ROUTE-REFRESH is accepted and ignored. It never sends an UPDATE.
//
// An UPDATE that fails to parse or validate resets the session, with the
// NOTIFICATION the parser names. That is GoBGP's behaviour with
// `treat-as-withdraw` off, which is how the monitor was configured. The rule
// matters for agreement: a sink that kept a session GoBGP would have reset
// would hold a count GoBGP never reached.

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"slices"
	"sync"
	"sync/atomic"
	"time"

	"github.com/osrg/gobgp/v4/pkg/packet/bgp"
)

// openWait bounds how long a connection may sit waiting for the peer's OPEN or
// first KEEPALIVE: RFC 4271's suggested large hold time.
const openWait = 4 * time.Minute

type config struct {
	localAS, peerAS     uint32
	routerID            netip.Addr
	localAddr, peerAddr netip.Addr
	holdTime            uint16
	connectRetry        time.Duration
	coalesce, heartbeat time.Duration
	hostname            string
}

// sessionError is how a session ends: the NOTIFICATION to send, if any, and
// what to log.
type sessionError struct {
	notify *bgp.BGPMessage
	reason string
}

func (e *sessionError) Error() string { return e.reason }

func notifyErr(code, sub uint8, data []byte, format string, args ...any) *sessionError {
	return &sessionError{
		notify: bgp.NewBGPNotificationMessage(code, sub, data),
		reason: fmt.Sprintf("sent notification %d/%d: ", code, sub) + fmt.Sprintf(format, args...),
	}
}

func fromMessageError(err error, what string) *sessionError {
	var me *bgp.MessageError
	if errors.As(err, &me) && me.TypeCode != 0 {
		return notifyErr(me.TypeCode, me.SubTypeCode, me.Data, "%s: %v", what, err)
	}
	// ValidateUpdateMsg's family check carries code 0. GoBGP still resets
	// the session for it; with no code to send, the connection just closes.
	return &sessionError{reason: fmt.Sprintf("%s: %v", what, err)}
}

type conn struct {
	nc       net.Conn
	r        *bufio.Reader
	wmu      sync.Mutex
	outbound bool // the sink initiated it
	// id names this connection on every S line. Direction alone does not:
	// a second inbound connection that loses to the held one is logged as
	// `down inbound` too, and a reader must not end the session on it.
	id       uint64
	remoteID netip.Addr
	closed   bool // set under sink.mu when collision resolution drops it
	// body is reused for every message: one allocation per connection rather
	// than one per UPDATE on the instrument's hot path. A parsed message may
	// alias it, so nothing may keep a message past the next read -- the table
	// keeps only prefix keys, and an OPEN is reduced to values first.
	body [bgp.BGP_MAX_EXTENDED_MESSAGE_LENGTH]byte
}

func (c *conn) send(m *bgp.BGPMessage, opts ...*bgp.MarshallingOption) error {
	b, err := m.Serialize(opts...)
	if err != nil {
		return err
	}
	c.wmu.Lock()
	defer c.wmu.Unlock()
	c.nc.SetWriteDeadline(time.Now().Add(30 * time.Second))
	_, err = c.nc.Write(b)
	return err
}

// read returns one message. maxLen is the length cap for UPDATE,
// NOTIFICATION and ROUTE-REFRESH; OPEN and KEEPALIVE keep 4096 (RFC 8654).
func (c *conn) read(deadline time.Duration, maxLen int, opts *bgp.MarshallingOption) (*bgp.BGPMessage, error) {
	if deadline > 0 {
		c.nc.SetReadDeadline(time.Now().Add(deadline))
	} else {
		c.nc.SetReadDeadline(time.Time{})
	}
	var hb [bgp.BGP_HEADER_LENGTH]byte
	if _, err := io.ReadFull(c.r, hb[:]); err != nil {
		return nil, err
	}
	h := &bgp.BGPHeader{}
	if err := h.DecodeFromBytes(hb[:]); err != nil {
		return nil, fromMessageError(err, "malformed header")
	}
	limit := bgp.BGP_MAX_MESSAGE_LENGTH
	switch h.Type {
	case bgp.BGP_MSG_UPDATE, bgp.BGP_MSG_NOTIFICATION, bgp.BGP_MSG_ROUTE_REFRESH:
		limit = maxLen
	}
	if int(h.Len) > limit {
		return nil, notifyErr(bgp.BGP_ERROR_MESSAGE_HEADER_ERROR, bgp.BGP_ERROR_SUB_BAD_MESSAGE_LENGTH,
			binary.BigEndian.AppendUint16(nil, h.Len), "message length %d over %d", h.Len, limit)
	}
	body := c.body[:int(h.Len)-bgp.BGP_HEADER_LENGTH]
	if _, err := io.ReadFull(c.r, body); err != nil {
		return nil, err
	}
	m, err := bgp.ParseBGPBody(h, body, opts)
	if err != nil {
		return nil, fromMessageError(err, fmt.Sprintf("malformed message type %d", h.Type))
	}
	return m, nil
}

func (n negotiated) hold() time.Duration { return time.Duration(n.holdTime) * time.Second }

// negotiated is what the two OPENs agreed.
type negotiated struct {
	holdTime uint16
	fourByte bool
	extended bool
	remoteID netip.Addr
	remoteAS uint32
}

func (s *sink) openMessage() *bgp.BGPMessage {
	// The order and set are the GoBGP monitor's OPEN as captured from
	// bgperf/gobgp 4.9.0: route-refresh, FQDN, extended message, IPv4
	// unicast, 4-octet AS, extended next hop for IPv4 unicast over IPv6.
	caps := []bgp.ParameterCapabilityInterface{
		bgp.NewCapRouteRefresh(),
		bgp.NewCapFQDN(s.cfg.hostname, ""),
		bgp.NewCapExtendedMessage(),
		bgp.NewCapMultiProtocol(bgp.RF_IPv4_UC),
		bgp.NewCapFourOctetASNumber(s.cfg.localAS),
		bgp.NewCapExtendedNexthop([]*bgp.CapExtendedNexthopTuple{
			bgp.NewCapExtendedNexthopTuple(bgp.RF_IPv4_UC, bgp.AFI_IP6)}),
	}
	myAS := uint16(bgp.AS_TRANS)
	if s.cfg.localAS <= 0xffff {
		myAS = uint16(s.cfg.localAS)
	}
	m, err := bgp.NewBGPOpenMessage(myAS, s.cfg.holdTime, s.cfg.routerID,
		[]bgp.OptionParameterInterface{bgp.NewOptionParameterCapability(caps)})
	if err != nil {
		panic(err) // the router ID was validated at startup
	}
	return m
}

// checkOpen validates the peer's OPEN against the configuration.
func (s *sink) checkOpen(m *bgp.BGPMessage) (negotiated, error) {
	var n negotiated
	o, ok := m.Body.(*bgp.BGPOpen)
	if !ok {
		return n, notifyErr(bgp.BGP_ERROR_FSM_ERROR, 0, nil, "expected OPEN, got type %d", m.Header.Type)
	}
	if o.Version != 4 {
		return n, notifyErr(bgp.BGP_ERROR_OPEN_MESSAGE_ERROR, bgp.BGP_ERROR_SUB_UNSUPPORTED_VERSION_NUMBER,
			[]byte{0, 4}, "version %d", o.Version)
	}
	n.remoteAS = uint32(o.MyAS)
	for _, p := range o.OptParams {
		pc, ok := p.(*bgp.OptionParameterCapability)
		if !ok {
			continue
		}
		for _, c := range pc.Capability {
			switch c.Code() {
			case bgp.BGP_CAP_FOUR_OCTET_AS_NUMBER:
				n.fourByte = true
				n.remoteAS = c.(*bgp.CapFourOctetASNumber).CapValue
			case bgp.BGP_CAP_EXTENDED_MESSAGE:
				n.extended = true
			}
		}
	}
	if n.remoteAS != s.cfg.peerAS {
		return n, notifyErr(bgp.BGP_ERROR_OPEN_MESSAGE_ERROR, bgp.BGP_ERROR_SUB_BAD_PEER_AS, nil,
			"peer AS %d, expected %d", n.remoteAS, s.cfg.peerAS)
	}
	if o.HoldTime == 1 || o.HoldTime == 2 {
		return n, notifyErr(bgp.BGP_ERROR_OPEN_MESSAGE_ERROR, bgp.BGP_ERROR_SUB_UNACCEPTABLE_HOLD_TIME, nil,
			"hold time %d", o.HoldTime)
	}
	if !o.ID.Is4() || o.ID.IsUnspecified() {
		return n, notifyErr(bgp.BGP_ERROR_OPEN_MESSAGE_ERROR, bgp.BGP_ERROR_SUB_BAD_BGP_IDENTIFIER, nil,
			"BGP identifier %v", o.ID)
	}
	// RFC 6286 2.2: an identifier equal to our own is refused from an
	// internal peer only; between ASes, AS plus identifier is what is unique.
	if o.ID == s.cfg.routerID && n.remoteAS == s.cfg.localAS {
		return n, notifyErr(bgp.BGP_ERROR_OPEN_MESSAGE_ERROR, bgp.BGP_ERROR_SUB_BAD_BGP_IDENTIFIER, nil,
			"internal peer has our own BGP identifier %v", o.ID)
	}
	n.remoteID = o.ID
	n.holdTime = min(s.cfg.holdTime, o.HoldTime)
	return n, nil
}

type sink struct {
	cfg config
	log *eventLog

	mu      sync.Mutex
	pending []*conn // in OpenConfirm
	active  *conn   // Established
	connIDs atomic.Uint64
}

func idValue(a netip.Addr) uint32 {
	b := a.As4()
	return binary.BigEndian.Uint32(b[:])
}

// enterOpenConfirm registers c as having received the peer's OPEN, resolving
// a collision with any other connection to the same peer (RFC 4271 6.8): the
// side with the higher BGP identifier keeps the connection it initiated, and
// with equal identifiers -- legal between different ASes -- the side with the
// larger AS does (RFC 6286 2.3). Both ends apply the same rule, so they drop
// the same connection. It returns false when c is the one dropped.
func (s *sink) enterOpenConfirm(c *conn) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.active != nil {
		return false
	}
	local, remote := idValue(s.cfg.routerID), idValue(c.remoteID)
	keepOutbound := local > remote || (local == remote && s.cfg.localAS > s.cfg.peerAS)
	collides := false
	for _, other := range s.pending {
		if other.outbound != c.outbound {
			collides = true
		}
	}
	if collides && c.outbound != keepOutbound {
		return false
	}
	var kept []*conn
	for _, other := range s.pending {
		if other.outbound != c.outbound {
			other.closed = true
			go s.drop(other, "connection collision: kept the other connection")
			continue
		}
		kept = append(kept, other)
	}
	s.pending = append(kept, c)
	return true
}

// establish promotes c from OpenConfirm. It fails if c was dropped meanwhile.
func (s *sink) establish(c *conn) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.unpend(c)
	if c.closed || s.active != nil {
		return false
	}
	s.active = c
	return true
}

// unpend removes c from the OpenConfirm list. Called with mu held.
func (s *sink) unpend(c *conn) {
	s.pending = slices.DeleteFunc(s.pending, func(p *conn) bool { return p == c })
}

func (s *sink) forget(c *conn) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.unpend(c)
	if s.active == c {
		s.active = nil
	}
}

func (s *sink) wasDropped(c *conn) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return c.closed
}

func (s *sink) established() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.active != nil
}

func (s *sink) drop(c *conn, reason string) {
	c.send(bgp.NewBGPNotificationMessage(bgp.BGP_ERROR_CEASE,
		bgp.BGP_ERROR_SUB_CONNECTION_COLLISION_RESOLUTION, nil))
	c.nc.Close()
	s.log.Line('S', "dropped", direction(c), c.id, reason)
}

func direction(c *conn) string {
	if c.outbound {
		return "outbound"
	}
	return "inbound"
}

// serve runs one connection to the end. It returns when the connection
// closes, for whatever reason, having logged why.
func (s *sink) serve(nc net.Conn, outbound bool) {
	c := &conn{nc: nc, r: bufio.NewReaderSize(nc, 1<<20), outbound: outbound, id: s.connIDs.Add(1)}
	defer nc.Close()
	defer s.forget(c)
	s.log.Line('S', "connected", direction(c), c.id, nc.RemoteAddr().String())

	err := s.run(c)
	var se *sessionError
	if errors.As(err, &se) && se.notify != nil {
		c.send(se.notify)
	}
	if s.wasDropped(c) {
		return // already logged by drop()
	}
	s.log.Line('S', "down", direction(c), c.id, err)
}

func (s *sink) run(c *conn) error {
	if err := c.send(s.openMessage()); err != nil {
		return err
	}
	s.log.Line('S', "open_sent", direction(c), c.id)
	m, err := c.read(openWait, bgp.BGP_MAX_MESSAGE_LENGTH, nil)
	if err != nil {
		return err
	}
	if n, ok := m.Body.(*bgp.BGPNotification); ok {
		return fmt.Errorf("received notification %d/%d", n.ErrorCode, n.ErrorSubcode)
	}
	neg, err := s.checkOpen(m)
	if err != nil {
		return err
	}
	c.remoteID = neg.remoteID
	if !s.enterOpenConfirm(c) {
		return notifyErr(bgp.BGP_ERROR_CEASE, bgp.BGP_ERROR_SUB_CONNECTION_COLLISION_RESOLUTION, nil,
			"connection collision: the other connection is kept")
	}
	if err := c.send(bgp.NewBGPKeepAliveMessage()); err != nil {
		return err
	}
	wait := neg.hold()
	if wait == 0 {
		wait = openWait
	}
	m, err = c.read(wait, bgp.BGP_MAX_MESSAGE_LENGTH, nil)
	if err != nil {
		return err
	}
	switch b := m.Body.(type) {
	case *bgp.BGPKeepAlive:
	case *bgp.BGPNotification:
		return fmt.Errorf("received notification %d/%d", b.ErrorCode, b.ErrorSubcode)
	default:
		return notifyErr(bgp.BGP_ERROR_FSM_ERROR, 0, nil, "expected KEEPALIVE in OpenConfirm, got type %d", m.Header.Type)
	}
	if !s.establish(c) {
		return notifyErr(bgp.BGP_ERROR_CEASE, bgp.BGP_ERROR_SUB_CONNECTION_COLLISION_RESOLUTION, nil,
			"connection collision: another connection is established")
	}
	s.log.Line('S', "established", direction(c), c.id, neg.remoteID, neg.remoteAS,
		fmt.Sprintf("hold=%d four_byte=%t extended=%t", neg.holdTime, neg.fourByte, neg.extended))
	return s.holdSession(c, neg)
}

func (s *sink) holdSession(c *conn, neg negotiated) error {
	done := make(chan struct{})
	defer close(done)
	hold := neg.hold()
	if hold > 0 {
		// Its own goroutine, on its own clock: a reader busy with a large
		// UPDATE burst must not be what decides whether the peer's hold timer
		// expires.
		go func() {
			t := time.NewTicker(hold / 3)
			defer t.Stop()
			for {
				select {
				case <-done:
					return
				case <-t.C:
					if c.send(bgp.NewBGPKeepAliveMessage()) != nil {
						return
					}
				}
			}
		}()
	}

	var ibgpID netip.Addr
	if s.cfg.localAS == s.cfg.peerAS {
		ibgpID = s.cfg.routerID
	}
	t := newTable(s.cfg.localAS, ibgpID)
	st := countState{at: monotonicNS()}
	// The session starts empty, and says so.
	s.log.Count(st, true)
	defer func() {
		// GoBGP drops the adj-RIB-in when a session goes down; the count
		// goes to zero with it, written at once rather than coalesced.
		s.log.Count(countState{at: monotonicNS()}, true)
	}()

	maxLen := bgp.BGP_MAX_MESSAGE_LENGTH
	if neg.extended {
		maxLen = bgp.BGP_MAX_EXTENDED_MESSAGE_LENGTH
	}
	opts := &bgp.MarshallingOption{
		AddPath:         map[bgp.Family]bgp.BGPAddPathMode{bgp.RF_IPv4_UC: bgp.BGP_ADD_PATH_NONE},
		Use2ByteAS:      !neg.fourByte,
		ExtendedMessage: neg.extended,
	}
	rfs := map[bgp.Family]bgp.BGPAddPathMode{bgp.RF_IPv4_UC: bgp.BGP_ADD_PATH_NONE}
	isEBGP := s.cfg.localAS != s.cfg.peerAS
	for {
		m, err := c.read(hold, maxLen, opts)
		if err != nil {
			var ne net.Error
			if errors.As(err, &ne) && ne.Timeout() {
				return notifyErr(bgp.BGP_ERROR_HOLD_TIMER_EXPIRED, 0, nil, "hold timer expired")
			}
			if _, ok := err.(*sessionError); ok {
				s.log.Line('M', err)
			}
			return err
		}
		switch b := m.Body.(type) {
		case *bgp.BGPUpdate:
			if ok, verr := bgp.ValidateUpdateMsg(b, rfs, isEBGP, false, false); !ok {
				se := fromMessageError(verr, "invalid UPDATE")
				s.log.Line('M', se)
				return se
			}
			r := t.apply(b)
			st.updates++
			st.accepted = t.accepted
			st.at = monotonicNS()
			if r.eor {
				st.eor++
				s.log.EndOfRIB(st)
			} else {
				s.log.Count(st, false)
			}
		case *bgp.BGPKeepAlive, *bgp.BGPRouteRefresh:
		case *bgp.BGPNotification:
			return fmt.Errorf("received notification %d/%d", b.ErrorCode, b.ErrorSubcode)
		default:
			return notifyErr(bgp.BGP_ERROR_FSM_ERROR, 0, nil, "unexpected message type %d when established", m.Header.Type)
		}
	}
}
