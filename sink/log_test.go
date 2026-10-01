package main

import (
	"bytes"
	"strings"
	"testing"
	"time"
)

type fakeClock struct{ ns int64 }

func (c *fakeClock) now() int64 { return c.ns }

func lines(b *bytes.Buffer) []string {
	return strings.Split(strings.TrimSuffix(b.String(), "\n"), "\n")
}

func TestCountsCoalesceToLatestStateAndItsTime(t *testing.T) {
	var b bytes.Buffer
	c := &fakeClock{ns: 1000}
	l := newEventLog(&b, c.now)
	l.Count(countState{at: 1100, accepted: 10, updates: 1}, false)
	l.Count(countState{at: 1200, accepted: 25, updates: 2}, false)
	if b.Len() != 0 {
		t.Fatalf("a count was written before the tick: %q", b.String())
	}
	c.ns = 5000
	l.Tick(time.Second)
	got := lines(&b)
	// Dated to the UPDATE that produced it, not to when it was written.
	if len(got) != 1 || got[0] != "C 1200 25 2 0" {
		t.Fatalf("got %q", got)
	}
}

func TestHeartbeatOnlyWhenQuiet(t *testing.T) {
	var b bytes.Buffer
	c := &fakeClock{}
	l := newEventLog(&b, c.now)
	l.Count(countState{at: 0, accepted: 7, updates: 3, eor: 1}, true)
	c.ns = int64(500 * time.Millisecond)
	l.Tick(time.Second)
	if n := len(lines(&b)); n != 1 {
		t.Fatalf("heartbeat too early: %q", b.String())
	}
	c.ns = int64(time.Second)
	l.Tick(time.Second)
	got := lines(&b)
	if len(got) != 2 || got[1] != "H 1000000000 7 3 1" {
		t.Fatalf("got %q", got)
	}
}

func TestEventLineFlushesPendingCountFirst(t *testing.T) {
	var b bytes.Buffer
	c := &fakeClock{ns: 900}
	l := newEventLog(&b, c.now)
	l.Count(countState{at: 800, accepted: 4, updates: 1}, false)
	l.Line('S', "down", "inbound", "eof")
	got := lines(&b)
	if len(got) != 2 || got[0] != "C 800 4 1 0" || got[1] != "S 900 down inbound eof" {
		t.Fatalf("got %q", got)
	}
}

func TestEndOfRIBFollowsItsCount(t *testing.T) {
	var b bytes.Buffer
	c := &fakeClock{ns: 0}
	l := newEventLog(&b, c.now)
	l.EndOfRIB(countState{at: 300, accepted: 9, updates: 4, eor: 1})
	got := lines(&b)
	if len(got) != 2 || got[0] != "C 300 9 4 1" || got[1] != "E 300 9 4" {
		t.Fatalf("got %q", got)
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, bytes.ErrTooLarge }

func TestWriteErrorIsKept(t *testing.T) {
	l := newEventLog(failingWriter{}, (&fakeClock{}).now)
	l.Line('S', "x")
	if l.Err() == nil {
		t.Fatal("a failed write must be reported")
	}
}

func TestImmediateCountKeepsThePendingOne(t *testing.T) {
	var b bytes.Buffer
	l := newEventLog(&b, (&fakeClock{ns: 50}).now)
	l.Count(countState{at: 40, accepted: 100, updates: 9}, false)
	l.Count(countState{at: 45}, true) // session down
	got := lines(&b)
	if len(got) != 2 || got[0] != "C 40 100 9 0" || got[1] != "C 45 0 0 0" {
		t.Fatalf("the peak before the drop was lost: %q", got)
	}
}

func TestEndOfRIBDoesNotRedateThePendingCount(t *testing.T) {
	var b bytes.Buffer
	l := newEventLog(&b, (&fakeClock{}).now)
	l.Count(countState{at: 100, accepted: 1000, updates: 50}, false)
	l.EndOfRIB(countState{at: 105, accepted: 1000, updates: 51, eor: 1})
	got := lines(&b)
	if len(got) != 3 || got[0] != "C 100 1000 50 0" || got[1] != "C 105 1000 51 1" || got[2] != "E 105 1000 51" {
		t.Fatalf("got %q", got)
	}
}
