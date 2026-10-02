package main

// The sink's only output: a line-oriented log in its bind-mounted directory,
// read by the controller on the host. Nothing polls the sink.
//
// Every line is `<kind> <monotonic_ns> <fields...>`. The timestamp is
// CLOCK_MONOTONIC, which a container shares with the host unless a time
// namespace was configured -- the controller compares it with Python's
// time.monotonic_ns(), which reads the same clock. That is an assumption the
// 7a Docker checks verify, not one this file can.
//
//   V <ns> <format> <version...>            first line: format and build
//   B <ns> <unix_ns>                        the two clocks read together
//   S <ns> <state> <direction> <conn> <detail...>
//                                           session: connected, open_sent,
//                                           established, down, dropped; <conn>
//                                           names the connection, since two
//                                           can share a direction
//   C <ns> <accepted> <updates> <eor>       the count changed
//   H <ns> <accepted> <updates> <eor>       heartbeat: still true at <ns>
//   E <ns> <accepted> <updates>             IPv4 unicast End-of-RIB received
//   M <ns> <detail...>                      a message the sink refused: one
//                                           that reset the session (an S down
//                                           follows), or an UPDATE the session
//                                           was kept through, whose detail
//                                           starts treat-as-withdraw or
//                                           attribute-discard
//
// A C line is dated to the last UPDATE folded into the state it reports, not
// to when it was written. Changes are coalesced to at most one C line per
// coalesce interval, so a count first shown on a line became true after the
// previous line's time and no later than its own: the coalesce interval is the
// resolution, not the write cadence. A count that must not be merged into a
// later one -- the last before a session drop, the one an End-of-RIB arrives
// on -- is written at once at its own time. An H line is written when nothing else has been for
// a heartbeat interval, so a reader can tell a sink that has nothing to report
// from one that has stopped.
//
// `updates` counts UPDATE messages on the current session, End-of-RIB
// included; `eor` counts IPv4 unicast End-of-RIBs on it. All three reset when
// the session goes down, because GoBGP drops the adj-RIB-in then too.
//
// A reader must stop at the last complete line: the sink is still writing.

import (
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/unix"
)

const logFormat = 1

var lineEnds = strings.NewReplacer("\n", " ", "\r", " ")

// monoBase pairs one direct CLOCK_MONOTONIC read with Go's own clock, read
// together at start. monotonicNS() then advances from it with time.Since(),
// which Go serves from the vDSO's CLOCK_MONOTONIC with no syscall: the reading
// is the same clock the host's time.monotonic() reads, and it is taken once per
// UPDATE, on the instrument's hot path. The two start reads are a few hundred
// nanoseconds apart, which bounds the offset this introduces.
var monoBaseNS, monoBase = clockMonotonicNS(), time.Now()

func clockMonotonicNS() int64 {
	var ts unix.Timespec
	if err := unix.ClockGettime(unix.CLOCK_MONOTONIC, &ts); err != nil {
		panic(err)
	}
	return ts.Nano()
}

func monotonicNS() int64 {
	return monoBaseNS + int64(time.Since(monoBase))
}

type countState struct {
	at       int64 // monotonic ns at which this state became true
	accepted int
	updates  uint64
	eor      uint64
}

type eventLog struct {
	mu      sync.Mutex
	w       io.Writer
	clock   func() int64
	cur     countState
	dirty   bool  // cur has not been written as a C line yet
	written int64 // clock() when the last line of any kind was written
	err     error
}

func newEventLog(w io.Writer, clock func() int64) *eventLog {
	return &eventLog{w: w, clock: clock}
}

// emit writes one complete line in a single Write, so a reader never sees the
// sink's half of a line interleaved with another. Called with mu held.
func (l *eventLog) emit(kind byte, at int64, fields ...any) {
	var b strings.Builder
	fmt.Fprintf(&b, "%c %d", kind, at)
	for _, f := range fields {
		// A field is free text when it is an error, and an error may carry a
		// line end. The reader takes every line as a record, so one inside a
		// field would split this record in two and the second half would be
		// read as a malformed line of its own.
		fmt.Fprintf(&b, " %s", lineEnds.Replace(fmt.Sprint(f)))
	}
	b.WriteByte('\n')
	if _, err := io.WriteString(l.w, b.String()); err != nil && l.err == nil {
		l.err = err
	}
	l.written = l.clock()
}

// flushLocked writes the pending count, if any. Called with mu held.
func (l *eventLog) flushLocked() {
	if l.dirty {
		l.emit('C', l.cur.at, l.cur.accepted, l.cur.updates, l.cur.eor)
		l.dirty = false
	}
}

// Line writes an event that is not a count. A pending count is flushed first,
// so the log stays in the order things happened.
func (l *eventLog) Line(kind byte, detail ...any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.flushLocked()
	l.emit(kind, l.clock(), detail...)
}

// Count records a new state. It is written by the next Tick, or at once when
// immediate is set -- for a session going down, which must not be coalesced
// into the count that preceded it.
func (l *eventLog) Count(s countState, immediate bool) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if immediate {
		// The pending state is written first, at its own time: overwriting
		// it would lose the instant the table peaked before it was dropped.
		l.flushLocked()
	}
	l.cur = s
	l.dirty = true
	if immediate {
		l.flushLocked()
	}
}

// EndOfRIB records the End-of-RIB with the state it arrived on. Any pending
// count is written first at its own time, so the End-of-RIB is never what
// dates the table's last change.
func (l *eventLog) EndOfRIB(s countState) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.flushLocked()
	l.cur = s
	l.dirty = true
	l.flushLocked()
	l.emit('E', s.at, s.accepted, s.updates)
}

// Tick is called once per coalesce interval: it writes a pending count, or a
// heartbeat when nothing has been written for `heartbeat`.
func (l *eventLog) Tick(heartbeat time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.dirty {
		l.flushLocked()
		return
	}
	now := l.clock()
	if now-l.written >= heartbeat.Nanoseconds() {
		l.emit('H', now, l.cur.accepted, l.cur.updates, l.cur.eor)
	}
}

// Err is the first write error, if any. The sink exits on it: an instrument
// that cannot record is not measuring.
func (l *eventLog) Err() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.err
}
