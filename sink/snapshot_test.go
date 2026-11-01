package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/osrg/gobgp/v4/pkg/packet/bgp"
)

func snapshotSink() *sink {
	s := testSink(io.Discard)
	s.cfg.snapshotSocket = "enabled"
	s.active = &conn{id: 7}
	s.snapshotTable = newTable(localAS, netip.Addr{})
	return s
}

func TestSnapshotAcceptedCanonicalPrefixes(t *testing.T) {
	s := snapshotSink()
	tb := s.snapshotTable
	tb.announce(netip.MustParsePrefix("10.2.3.4/16"), false)
	tb.announce(netip.MustParsePrefix("10.1.1.1/8"), false)
	tb.announce(netip.MustParsePrefix("10.1.1.1/24"), true)
	r := s.prefixSnapshot()
	want := []string{"10.0.0.0/8", "10.2.0.0/16"}
	if r.Schema != snapshotSchema || r.Status != "complete" || r.Reason != nil ||
		r.MonotonicNS <= 0 || r.ConnectionID != 7 || r.AcceptedCount != 2 || !reflect.DeepEqual(r.Prefixes, want) {
		t.Fatalf("snapshot: %+v", r)
	}
	original := r.Prefixes
	// Replacement changes acceptance even when the prefix stays held; a
	// withdrawal then removes it. Snapshot membership follows both changes.
	tb.announce(netip.MustParsePrefix("10.2.0.0/16"), true)
	tb.announce(netip.MustParsePrefix("10.1.1.0/24"), false)
	tb.withdraw(netip.MustParsePrefix("10.0.0.0/8"))
	r = s.prefixSnapshot()
	if r.AcceptedCount != 1 || !reflect.DeepEqual(r.Prefixes, []string{"10.1.1.0/24"}) {
		t.Fatalf("replacement/withdrawal snapshot: %+v", r)
	}
	// Previously returned data is a copy, not a live view.
	if !reflect.DeepEqual(original, want) {
		t.Fatal("old snapshot changed")
	}
}

func TestSnapshotDisabledAndNoActiveTable(t *testing.T) {
	s := snapshotSink()
	s.cfg.snapshotSocket = ""
	for _, active := range []bool{true, false} {
		if !active {
			s.cfg.snapshotSocket = "enabled"
			s.active = nil
		}
		r := s.prefixSnapshot()
		if r.Status != "unavailable" || r.Reason == nil || len(r.Prefixes) != 0 || r.ConnectionID != 0 {
			t.Fatalf("unavailable state: %+v", r)
		}
	}
}

func TestSnapshotLimitIncludesRejectedHeldEntries(t *testing.T) {
	for _, rejected := range []bool{false, true} {
		s := snapshotSink()
		for i := 0; i <= maxSnapshotPrefixes; i++ {
			s.snapshotTable.held[prefixKey(uint64(i)<<8|32)] = rejected
		}
		if !rejected {
			s.snapshotTable.accepted = maxSnapshotPrefixes + 1
		}
		r := s.prefixSnapshot()
		if r.Status != "unavailable" || r.Reason == nil || len(r.Prefixes) != 0 || r.ConnectionID != 7 {
			t.Fatalf("oversized table returned partial evidence: %+v", r)
		}
	}
}

func TestSnapshotSocket(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "prefix.sock")
	ln, err := listenSnapshots(path)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o666 {
		t.Fatalf("socket permissions: %v %v", info, err)
	}
	s := snapshotSink()
	s.snapshotTable.announce(netip.MustParsePrefix("100.0.0.0/32"), false)
	done := make(chan struct{})
	go func() { s.serveSnapshots(ln); close(done) }()
	c, err := net.DialTimeout("unix", path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	c.SetReadDeadline(time.Now().Add(time.Second))
	var r prefixSnapshot
	if err := json.NewDecoder(c).Decode(&r); err != nil || r.Status != "complete" || r.AcceptedCount != 1 {
		t.Fatalf("socket response: %+v %v", r, err)
	}
	c.Close()
	ln.Close()
	<-done
	if _, err := os.Lstat(path); err != nil {
		t.Fatalf("closing removed retained socket entry: %v", err)
	}
	if second, err := listenSnapshots(path); err == nil {
		second.Close()
		t.Fatal("preexisting socket was replaced")
	}
	file := filepath.Join(t.TempDir(), "existing")
	if err := os.WriteFile(file, []byte("preserve"), 0o600); err != nil {
		t.Fatal(err)
	}
	if second, err := listenSnapshots(file); err == nil {
		second.Close()
		t.Fatal("preexisting regular file was replaced")
	}
	if data, err := os.ReadFile(file); err != nil || string(data) != "preserve" {
		t.Fatalf("existing file changed: %q %v", data, err)
	}
}

func TestSnapshotRefusesPublicDirectory(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "prefix.sock")
	if listener, err := listenSnapshots(path); err == nil {
		listener.Close()
		t.Fatal("accepted a public snapshot directory")
	}
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatalf("refused request created a socket: %v", err)
	}
}

type blockingSnapshotResetLog struct {
	block            atomic.Bool
	once             sync.Once
	entered, release chan struct{}
}

func (w *blockingSnapshotResetLog) Write(p []byte) (int, error) {
	if w.block.Load() {
		w.once.Do(func() { close(w.entered) })
		<-w.release
	}
	return len(p), nil
}

func TestSnapshotInvalidatedBeforeBlockedResetLog(t *testing.T) {
	writer := &blockingSnapshotResetLog{entered: make(chan struct{}), release: make(chan struct{})}
	var release sync.Once
	defer release.Do(func() { close(writer.release) })
	s := snapshotSink()
	s.log = newEventLog(writer, monotonicNS)
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	c := &conn{id: 9, nc: a, r: bufio.NewReader(a)}
	s.active, s.snapshotTable = c, nil
	done := make(chan error, 1)
	go func() { done <- s.holdSession(c, negotiated{fourByte: true}) }()
	p := &peer{t: t, nc: b, r: bufio.NewReader(b)}
	p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, 1000), nlris(t, "100.0.0.1/32")))
	deadline := time.Now().Add(time.Second)
	for s.prefixSnapshot().Updates != 1 {
		if time.Now().After(deadline) {
			t.Fatal("UPDATE was not applied")
		}
		time.Sleep(time.Millisecond)
	}
	writer.block.Store(true)
	b.Close()
	select {
	case <-writer.entered:
	case <-time.After(time.Second):
		t.Fatal("reset log did not block")
	}
	if r := s.prefixSnapshot(); r.Status != "unavailable" || r.ConnectionID != 0 {
		t.Fatalf("lost table visible while reset log blocked: %+v", r)
	}
	release.Do(func() { close(writer.release) })
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("session did not finish")
	}
}

func TestSnapshotConcurrentSessionUpdatesAndReset(t *testing.T) {
	s := snapshotSink()
	a, b := net.Pipe()
	c := &conn{id: 9, nc: a, r: bufio.NewReader(a)}
	s.active, s.snapshotTable = c, nil
	done := make(chan error, 1)
	go func() { done <- s.holdSession(c, negotiated{fourByte: true}) }()
	stop, snapshotsDone := make(chan struct{}), make(chan error, 1)
	go func() {
		for {
			select {
			case <-stop:
				snapshotsDone <- nil
				return
			default:
				r := s.prefixSnapshot()
				if r.Status == "complete" && (r.AcceptedCount != len(r.Prefixes) || r.ConnectionID != 9) {
					snapshotsDone <- fmt.Errorf("inconsistent live snapshot: %+v", r)
					return
				}
			}
		}
	}()
	p := &peer{t: t, nc: b, r: bufio.NewReader(b)}
	for i := 0; i < 50; i++ {
		address := fmt.Sprintf("100.0.0.%d/32", i)
		p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, 1000), nlris(t, address)))
		if i%2 == 0 {
			// Replace accepted paths with rejected ones while snapshots copy.
			p.send(bgp.NewBGPUpdateMessage(nil, attrs(t, localAS), nlris(t, address)))
		}
	}
	deadline := time.Now().Add(time.Second)
	for {
		r := s.prefixSnapshot()
		if r.Updates == 75 {
			if r.Status != "complete" || r.AcceptedCount != 25 {
				t.Fatalf("final snapshot: %+v", r)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("session did not apply all updates")
		}
		time.Sleep(time.Millisecond)
	}
	b.Close()
	if err := <-done; err == nil {
		t.Fatal("expected closed connection")
	}
	a.Close()
	close(stop)
	if err := <-snapshotsDone; err != nil {
		t.Fatal(err)
	}
	if r := s.prefixSnapshot(); r.Status != "unavailable" || r.ConnectionID != 0 || len(r.Prefixes) != 0 {
		t.Fatalf("lost session served old table: %+v", r)
	}
}
