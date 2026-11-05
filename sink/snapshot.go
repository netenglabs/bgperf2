package main

// Prefix snapshots are opt-in functional evidence. They are requested after
// measurement by a local reader, never used for count or convergence timing.
// A complete response describes one instant of the active accepted table.

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"slices"
	"time"
)

const snapshotSchema = "bgperf2/observer-prefixes/v1alpha1"
const maxSnapshotPrefixes = 100000

type prefixSnapshot struct {
	Schema        string   `json:"schema"`
	Status        string   `json:"status"`
	MonotonicNS   int64    `json:"monotonic_ns"`
	ConnectionID  uint64   `json:"connection_id"`
	Updates       uint64   `json:"updates"`
	AcceptedCount int      `json:"accepted_count"`
	Prefixes      []string `json:"prefixes"`
	Reason        *string  `json:"reason"`
}

func (s *sink) prefixSnapshot() prefixSnapshot {
	r := prefixSnapshot{Schema: snapshotSchema, Status: "unavailable", Prefixes: []string{}}
	var keys []prefixKey
	s.mu.Lock()
	r.MonotonicNS = monotonicNS()
	switch {
	case s.cfg.snapshotSocket == "":
		reason := "Prefix snapshot capture is disabled."
		r.Reason = &reason
	case s.active == nil || s.snapshotTable == nil:
		reason := "No active initialized session table is available."
		r.Reason = &reason
	default:
		r.ConnectionID, r.Updates = s.active.id, s.snapshotUpdates
		r.AcceptedCount = s.snapshotTable.accepted
		if r.AcceptedCount > maxSnapshotPrefixes || len(s.snapshotTable.held) > maxSnapshotPrefixes {
			// Bound scanning as well as copying: rejected entries are held too.
			reason := fmt.Sprintf("Table exceeds the %d held/accepted-prefix snapshot limit.", maxSnapshotPrefixes)
			r.Reason = &reason
		} else {
			keys = make([]prefixKey, 0, r.AcceptedCount)
			for key, rejected := range s.snapshotTable.held {
				if !rejected {
					keys = append(keys, key)
				}
			}
			r.Status = "complete"
		}
	}
	s.mu.Unlock()

	// The copy is independent of further updates or a session reset. Numeric
	// address/length order is deterministic and does not depend on map order.
	slices.Sort(keys)
	for _, key := range keys {
		var address [4]byte
		binary.BigEndian.PutUint32(address[:], uint32(uint64(key)>>8))
		r.Prefixes = append(r.Prefixes, netip.PrefixFrom(netip.AddrFrom4(address), int(key&255)).String())
	}
	return r
}

func listenSnapshots(path string) (*net.UnixListener, error) {
	// The sink may run as container root while its host reader is an
	// unprivileged operator. Access is restricted by the private bind dir,
	// not an assumed shared UID mapping for the socket inode.
	parent, err := os.Stat(filepath.Dir(path))
	if err != nil {
		return nil, err
	}
	if !parent.IsDir() || parent.Mode().Perm() != 0o700 {
		return nil, fmt.Errorf("snapshot socket requires a mode-0700 parent directory")
	}
	// ListenUnix fails on any preexisting path. In particular, never remove a
	// stale socket or follow/overwrite a preexisting filesystem entry.
	ln, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, err
	}
	ln.SetUnlinkOnClose(false)
	if err := os.Chmod(path, 0o666); err != nil {
		ln.Close()
		return nil, err
	}
	return ln, nil
}

func (s *sink) serveSnapshots(ln *net.UnixListener) {
	// A single accept loop bounds simultaneous table copies and response
	// allocations. A reader that stops reading occupies it for at most 2s.
	for {
		connection, err := ln.AcceptUnix()
		if err != nil {
			return
		}
		connection.SetWriteDeadline(time.Now().Add(2 * time.Second))
		json.NewEncoder(connection).Encode(s.prefixSnapshot())
		connection.Close()
	}
}
