"""Stopping on purpose, before the host is taken away.

The campaign runs on an EC2 spot instance that is reclaimed without warning:
SIGTERM, then SIGKILL about two minutes later, with the metadata notice a
little earlier still. None of those windows finishes a cell, so what is tested
here is that the *stop* is orderly -- nothing half-done recorded as done, and
nothing left running.

Pure: no EC2, no network, no signals, no Docker. The transport is injected.
"""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reclaim
from reclaim import (StopRequested, StopSignal, parse_instance_action,
                     poll_instance_action, watch_for_interruption)


class TestTheReasonIsRecordedOnce:
    def test_the_first_reason_wins(self):
        """A reclaim delivers the notice first and SIGTERM second."""
        stop = StopSignal()
        assert stop.request('EC2 spot interruption notice: terminate at X')
        assert not stop.request('SIGTERM')
        assert stop.reason == 'EC2 spot interruption notice: terminate at X'

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


class TestWhatIMDSSays:
    def test_404_is_the_normal_answer_and_is_not_an_interruption(self):
        """This is what the endpoint returns for the whole life of an
        instance nobody is reclaiming. Treating it as an error would log
        every five seconds forever."""
        assert parse_instance_action(404, '') is None

    def test_a_notice_names_the_action_and_the_time(self):
        body = json.dumps({'action': 'terminate',
                           'time': '2026-09-13T12:00:00Z'})
        assert parse_instance_action(200, body) == (
            'EC2 spot interruption notice: terminate at 2026-09-13T12:00:00Z')

    def test_stop_and_hibernate_are_notices_too(self):
        for action in ('stop', 'hibernate'):
            got = parse_instance_action(200, json.dumps({'action': action}))
            assert got == 'EC2 spot interruption notice: {0}'.format(action)

    def test_an_unreadable_200_is_still_an_interruption(self):
        """Discarding a real notice because the body changed shape is the one
        failure that costs the thing this module exists for."""
        assert parse_instance_action(200, 'not json') == (
            'EC2 spot interruption notice (unreadable body)')
        assert parse_instance_action(200, '{}') == (
            'EC2 spot interruption notice (unreadable body)')

    def test_a_server_error_is_not_read_as_a_notice(self):
        """And is not read as 'nothing scheduled' either -- it is a read that
        did not answer, so the caller counts it as a failure."""
        with pytest.raises(reclaim.MetadataUnavailable):
            parse_instance_action(500, 'oops')

    def test_an_unauthenticated_read_is_not_silence(self):
        """The case this rule exists for. On an instance with IMDSv2 enforced,
        a token request that does not return 200 leaves the action read
        unauthenticated, and IMDS answers 401. Read as 'nothing scheduled',
        that is a watcher which polls a reclaimable host for the life of the
        run and never fires."""
        for status in (401, 403, 429, 503):
            with pytest.raises(reclaim.MetadataUnavailable):
                parse_instance_action(status, '')

    def test_an_enforced_imdsv2_host_counts_failures_rather_than_polling_on(self):
        """End to end through the poll, not just the parser."""
        def read(path, headers):
            if path == reclaim.TOKEN_PATH:
                return 429, ''
            assert headers is None
            return 401, ''

        with pytest.raises(reclaim.MetadataUnavailable):
            poll_instance_action(read)

    def test_the_token_is_fetched_first_and_then_carried(self):
        seen = []

        def read(path, headers):
            seen.append((path, headers))
            if path == reclaim.TOKEN_PATH:
                return 200, 'TOKEN123'
            return 404, ''

        assert poll_instance_action(read) is None
        assert seen[0][0] == reclaim.TOKEN_PATH
        assert seen[1][0] == reclaim.INSTANCE_ACTION_PATH
        assert seen[1][1] == {'X-aws-ec2-metadata-token': 'TOKEN123'}

    def test_a_host_with_no_token_endpoint_still_asks(self):
        """IMDSv1 answers the action path without a token."""
        def read(path, headers):
            if path == reclaim.TOKEN_PATH:
                return 403, ''
            assert headers is None
            return 200, json.dumps({'action': 'terminate'})

        assert poll_instance_action(read) == (
            'EC2 spot interruption notice: terminate')


class TestTheWatcher:
    def test_a_notice_stops_the_run_and_is_announced_once(self):
        announced = []
        stop = StopSignal()

        def read(path, headers):
            if path == reclaim.TOKEN_PATH:
                return 200, 'T'
            return 200, json.dumps({'action': 'terminate', 'time': 'T0'})

        watch_for_interruption(stop, read, interval_s=0.01,
                               on_notice=announced.append)
        assert stop.is_set()
        assert announced == ['EC2 spot interruption notice: terminate at T0']

    def test_a_non_ec2_host_gives_up_silently(self):
        """Every developer machine is 'not EC2'. A warning nobody can act on
        is a warning everybody learns to skip."""
        announced = []
        stop = StopSignal()
        calls = []

        def read(path, headers):
            calls.append(path)
            raise OSError('no route to host')

        watch_for_interruption(stop, read, interval_s=0.01,
                               on_notice=announced.append)
        assert not stop.is_set()
        assert announced == []
        # Gave up rather than polling forever, and not on the first failure.
        assert 1 < len(calls) <= 2 * reclaim.FAILURES_BEFORE_GIVING_UP

    def test_a_single_dropped_read_does_not_disable_it(self):
        stop = StopSignal()
        state = {'n': 0}

        def read(path, headers):
            if path == reclaim.TOKEN_PATH:
                return 200, 'T'
            state['n'] += 1
            if state['n'] == 1:
                raise OSError('transient')
            return 200, json.dumps({'action': 'terminate'})

        watch_for_interruption(stop, read, interval_s=0.01)
        assert stop.is_set()

    def test_it_keeps_watching_a_host_that_has_answered_once(self):
        """Giving up is for a host that is not EC2 at all. Three consecutive
        failures is fifteen seconds at the real interval, which an IMDS blip
        reaches easily -- and giving up there disables reclaim detection for
        the remaining hours of a batch with nothing recorded and nothing to
        see."""
        stop = StopSignal()
        state = {'n': 0}

        def read(path, headers):
            if path == reclaim.TOKEN_PATH:
                return 200, 'T'
            state['n'] += 1
            # One answer, then a long outage -- longer than the give-up
            # count -- and then the notice.
            if state['n'] == 1:
                return 404, ''
            if state['n'] <= 1 + 3 * reclaim.FAILURES_BEFORE_GIVING_UP:
                raise OSError('IMDS unavailable')
            return 200, json.dumps({'action': 'terminate'})

        watch_for_interruption(stop, read, interval_s=0.001)
        assert stop.is_set()
        assert 'terminate' in stop.reason

    def test_a_host_that_never_answers_is_still_abandoned(self):
        """The other half of the same rule: the give-up is not removed, it is
        scoped to a host that has never answered."""
        stop = StopSignal()
        calls = []

        def read(path, headers):
            calls.append(path)
            raise OSError('no route to host')

        watch_for_interruption(stop, read, interval_s=0.001)
        assert not stop.is_set()
        assert 1 < len(calls) <= 2 * reclaim.FAILURES_BEFORE_GIVING_UP

    def test_a_finished_run_does_not_hold_the_process_open(self):
        """It waits on the stop rather than sleeping, so a run that ends
        normally ends the watcher with it."""
        stop = StopSignal()

        def read(path, headers):
            return 404, ''

        stop.request('run finished')
        watch_for_interruption(stop, read, interval_s=30)
