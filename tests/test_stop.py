"""Stopping a run on purpose: the reason is kept, and a stop always raises.

Deciding when to stop, such as watching for a host being reclaimed, is the
caller's job; the engine only honours SIGTERM.
"""
import threading

import pytest

from stop import StopRequested, StopSignal


class TestTheReasonIsRecordedOnce:
    def test_the_first_reason_wins(self):
        stop = StopSignal()
        assert stop.request('first')
        assert not stop.request('SIGTERM')
        assert stop.reason == 'first'

    def test_nothing_is_set_until_it_is_asked_for(self):
        stop = StopSignal()
        assert not stop.is_set()
        assert stop.reason is None
        stop.raise_if_set()

    def test_raise_carries_the_reason(self):
        stop = StopSignal()
        stop.request('SIGTERM')
        with pytest.raises(StopRequested) as excinfo:
            stop.raise_if_set()
        assert excinfo.value.reason == 'SIGTERM'

    def test_a_waiter_finds_the_reason_already_readable(self):
        """Set outside the lock, so a woken thread never reads None."""
        stop = StopSignal()
        seen = []

        def waiter():
            stop.wait(5)
            seen.append(stop.reason)

        t = threading.Thread(target=waiter)
        t.start()
        stop.request('SIGTERM')
        t.join(5)
        assert seen == ['SIGTERM']
