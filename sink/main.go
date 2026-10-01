// bgperf-sink is bgperf2's monitor: a BGP speaker that holds one session to
// the target, counts the IPv4 unicast prefixes it is sent, and writes every
// change to a timestamped log. It replaces a GoBGP monitor that was polled
// once a second by `docker exec`; why, and what the change must preserve, is
// Phase 7 of docs/bgperf2-measurement-implementation-plan.md and its entry in
// the decision log.
//
// The source lives in bgperf2's repository and is embedded in the image recipe
// (sink.py), so the recipe hash that marks an image stale covers this code too.
package main

import (
	"flag"
	"fmt"
	"net"
	"net/netip"
	"os"
	"runtime"
	"runtime/debug"
	"strconv"
	"time"
)

const sinkVersion = "0.1.0"

// sourceHash is set at build time from the files compiled (see sink.py). An
// image built some other way says so rather than reporting nothing.
var sourceHash = "unknown"

func gobgpVersion() string {
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, d := range info.Deps {
			if d.Path == "github.com/osrg/gobgp/v4" {
				return d.Version
			}
		}
	}
	return "unknown"
}

func versionString() string {
	return fmt.Sprintf("bgperf-sink %s (src %s) gobgp/v4 %s %s",
		sinkVersion, sourceHash, gobgpVersion(), runtime.Version())
}

func parseAS(s string) (uint32, error) {
	v, err := strconv.ParseUint(s, 10, 32)
	return uint32(v), err
}

func main() {
	var (
		localAS      = flag.String("local-as", "", "the sink's AS")
		peerAS       = flag.String("peer-as", "", "the target's AS")
		routerID     = flag.String("router-id", "", "the sink's BGP identifier")
		localAddr    = flag.String("local-address", "", "address to listen on and connect from")
		peerAddr     = flag.String("peer-address", "", "the target's address")
		holdTime     = flag.Uint("hold-time", 90, "hold time to offer, seconds (GoBGP's default)")
		connectRetry = flag.Duration("connect-retry", 10*time.Second, "outbound connect interval (the monitor's connect-retry)")
		coalesce     = flag.Duration("coalesce", 10*time.Millisecond, "at most one count line per interval")
		heartbeat    = flag.Duration("heartbeat", time.Second, "write a heartbeat after this long with nothing written")
		logPath      = flag.String("log", "", "the event log to append to")
		version      = flag.Bool("version", false, "print the version and exit")
	)
	flag.Parse()
	if *version {
		fmt.Println(versionString())
		return
	}

	fail := func(format string, args ...any) {
		fmt.Fprintf(os.Stderr, "bgperf-sink: "+format+"\n", args...)
		os.Exit(2)
	}
	var cfg config
	var err error
	if cfg.localAS, err = parseAS(*localAS); err != nil || cfg.localAS == 0 {
		fail("-local-as: %q", *localAS)
	}
	if cfg.peerAS, err = parseAS(*peerAS); err != nil || cfg.peerAS == 0 {
		fail("-peer-as: %q", *peerAS)
	}
	for _, a := range []struct {
		dst  *netip.Addr
		src  string
		name string
	}{{&cfg.routerID, *routerID, "router-id"}, {&cfg.localAddr, *localAddr, "local-address"},
		{&cfg.peerAddr, *peerAddr, "peer-address"}} {
		if *a.dst, err = netip.ParseAddr(a.src); err != nil || !a.dst.Is4() {
			fail("-%s: %q is not an IPv4 address", a.name, a.src)
		}
	}
	if *holdTime > 0xffff || *holdTime == 1 || *holdTime == 2 {
		fail("-hold-time: %d", *holdTime)
	}
	// A zero or negative coalesce interval panics the ticker; a zero
	// connect-retry would redial with no pause and burn the instrument's CPU.
	if *coalesce <= 0 || *heartbeat <= 0 || *connectRetry <= 0 {
		fail("-coalesce, -heartbeat and -connect-retry must be positive")
	}
	if *logPath == "" {
		fail("-log is required")
	}
	cfg.holdTime = uint16(*holdTime)
	cfg.connectRetry, cfg.coalesce, cfg.heartbeat = *connectRetry, *coalesce, *heartbeat
	if cfg.hostname, err = os.Hostname(); err != nil {
		cfg.hostname = "bgperf-sink"
	}

	f, err := os.OpenFile(*logPath, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		fail("%v", err)
	}
	s := &sink{cfg: cfg, log: newEventLog(f, monotonicNS)}
	s.log.Line('V', logFormat, versionString())
	s.log.Line('B', time.Now().UnixNano())

	ln, err := net.Listen("tcp", netip.AddrPortFrom(cfg.localAddr, 179).String())
	if err != nil {
		fail("%v", err)
	}
	go s.accept(ln)
	go s.connect()

	t := time.NewTicker(cfg.coalesce)
	defer t.Stop()
	for range t.C {
		s.log.Tick(cfg.heartbeat)
		if err := s.log.Err(); err != nil {
			// An instrument that cannot record is not measuring.
			fail("writing %s: %v", *logPath, err)
		}
	}
}

func (s *sink) accept(ln net.Listener) {
	for {
		nc, err := ln.Accept()
		if err != nil {
			s.log.Line('S', "accept_failed", err)
			time.Sleep(time.Second)
			continue
		}
		remote, _ := netip.ParseAddrPort(nc.RemoteAddr().String())
		if remote.Addr().Unmap() != s.cfg.peerAddr {
			s.log.Line('S', "rejected", nc.RemoteAddr().String())
			nc.Close()
			continue
		}
		go s.serve(nc, false)
	}
}

func (s *sink) connect() {
	d := net.Dialer{
		LocalAddr: &net.TCPAddr{IP: s.cfg.localAddr.AsSlice()},
		Timeout:   s.cfg.connectRetry,
	}
	target := netip.AddrPortFrom(s.cfg.peerAddr, 179).String()
	for {
		if !s.established() {
			if nc, err := d.Dial("tcp", target); err == nil {
				s.serve(nc, true)
			}
		}
		time.Sleep(s.cfg.connectRetry)
	}
}
