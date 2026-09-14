# Copyright (C) 2026 bgperf2 contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''Stopping on purpose, before the machine is taken away.

The campaign host is an EC2 spot instance: it is reclaimed without warning,
with a SIGTERM about two minutes ahead of a SIGKILL, and the instance metadata
service publishes the same notice a little earlier still. Neither window is
long enough to finish a cell -- a 1.05M-prefix MRT cell runs for tens of
minutes -- so the goal here is never to save the cell in flight. It is to make
the *stop* orderly: no half-written checkpoint, no cell recorded as complete
that is not, and a run that says out loud why it ended.

Everything in this module is pure or injectable, so the test suite exercises it
with no EC2, no network and no signals.
'''

import json
import threading


# The IMDS paths, and the two-minute warning they carry. Not configurable:
# these are AWS's, and a wrong value here reads as "no interruption".
IMDS_BASE = 'http://169.254.169.254'
TOKEN_PATH = '/latest/api/token'
INSTANCE_ACTION_PATH = '/latest/meta-data/spot/instance-action'
TOKEN_TTL_SECONDS = 60

# How long a single metadata read may take. The link-local address answers in
# under a millisecond on EC2 and is a black hole everywhere else, so this is
# chosen to be short enough that a non-EC2 host is not delayed noticeably even
# once.
IMDS_TIMEOUT_S = 1.0

# How often to ask. The notice arrives ~120s ahead; polling every 5s spends
# nothing measurable and spots it with plenty of the window left.
POLL_INTERVAL_S = 5.0

# How many consecutive failures before the poller gives up for the life of the
# run. A non-EC2 host fails the very first read, and there is nothing for it to
# start succeeding at later -- but a single dropped packet on EC2 should not
# disable the thing, so it is not 1.
FAILURES_BEFORE_GIVING_UP = 3


class MetadataUnavailable(Exception):
    """A metadata read that answered, but not about this instance's end.

    **Only 404 is "nothing scheduled".** Every other non-200 -- a 401 from an
    instance with IMDSv2 enforced whose token request did not return a token, a
    429 under IMDS throttling, a 5xx -- says the endpoint did not answer the
    question, and reading those as "no interruption" is the one failure this
    module exists to avoid: the watcher would poll a reclaimable host forever,
    count no failures, and never fire. Raised so the caller counts a failed
    read instead.
    """


class StopRequested(Exception):
    '''Raised inside a run that must abandon what it is doing.

    Carries the reason so the caller can print it rather than inventing one.
    A run that raises this recorded no result and must not be checkpointed as
    though it had.
    '''

    def __init__(self, reason):
        super(StopRequested, self).__init__(reason)
        self.reason = reason


class StopSignal:
    '''Why this process is stopping, recorded once and readable everywhere.

    **The first reason wins.** A spot reclaim delivers the metadata notice
    first and SIGTERM second, so the later one would overwrite the informative
    reason ("EC2 spot interruption notice: terminate at ...") with the generic
    one ("SIGTERM"). What a reader needs is what started the stop, not what
    last touched it.

    A `threading.Event` is deliberately the backing store: the controller's
    sampler threads already wait on `controller_stop`, so anything that needs
    to be woken can wait on this the same way rather than polling a flag.
    '''

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = None

    def request(self, reason):
        '''Ask for a stop. Returns True if this call is the one that set it.'''
        with self._lock:
            first = self._reason is None
            if first:
                self._reason = reason
        # Outside the lock: a waiter waking up must find the reason already
        # readable, which it is, and nothing here may block holding the lock.
        self._event.set()
        return first

    def is_set(self):
        return self._event.is_set()

    @property
    def reason(self):
        with self._lock:
            return self._reason

    def wait(self, timeout=None):
        return self._event.wait(timeout)

    def raise_if_set(self):
        '''Abandon the current run if a stop has been asked for.

        Called from the loops that would otherwise run for tens of minutes.
        '''
        if self._event.is_set():
            raise StopRequested(self.reason)


def parse_instance_action(status, body):
    '''What IMDS says about this instance's imminent end.

    Returns a one-line description, or None for "nothing scheduled". **404 is
    the normal answer** and means exactly that -- it is what the endpoint
    returns for the whole life of an instance nobody is reclaiming, so it must
    never be treated as an error or logged.

    A 200 carries `{"action": "terminate", "time": "2026-09-13T12:00:00Z"}`;
    `action` is also `stop` or `hibernate`. Unparseable JSON on a 200 is still
    an interruption notice -- the endpoint does not answer 200 for anything
    else -- so it returns a description rather than None. Discarding a real
    notice because its body changed shape is the one failure that costs the
    thing this module exists for.

    **Every other status raises `MetadataUnavailable`**, and is therefore
    counted by the caller as a failed read rather than as a negative answer.
    The case that made this necessary is not exotic: on an instance with
    IMDSv2 enforced, a token request that does not return 200 leaves the
    `instance-action` GET unauthenticated, which answers 401 -- and read as
    "nothing scheduled" that is a watcher which polls a reclaimable host for
    the life of the run, counts no failures, never gives up and never fires.
    '''
    if status == 404:
        return None
    if status != 200:
        raise MetadataUnavailable(
            'instance-action answered {0}'.format(status))
    try:
        doc = json.loads(body)
        action = doc['action']
    except (ValueError, KeyError, TypeError):
        return 'EC2 spot interruption notice (unreadable body)'
    when = None
    try:
        when = doc['time']
    except (KeyError, TypeError):
        pass
    if when:
        return 'EC2 spot interruption notice: {0} at {1}'.format(action, when)
    return 'EC2 spot interruption notice: {0}'.format(action)


def poll_instance_action(read):
    '''One poll, given a `read(path, headers)` that returns `(status, body)`.

    The transport is injected so this is testable without a network, and so
    the one place that knows about `requests` stays in `bgperf2.py`.

    IMDSv2 wants a token first; a host that answers the token request but not
    the action request is not a state worth modelling, so any exception from
    either read is reported as a failure and the caller counts it.

    A token request that does not answer 200 is *not* fatal here, because a
    host still allowing IMDSv1 answers the action read without one. What
    decides it is the action read's own status, which is why the token is
    allowed to be absent and `parse_instance_action()` is strict.
    '''
    status, body = read(TOKEN_PATH, None)
    token = body if status == 200 else None
    headers = {'X-aws-ec2-metadata-token': token} if token else None
    status, body = read(INSTANCE_ACTION_PATH, headers)
    return parse_instance_action(status, body)


def watch_for_interruption(stop, read, interval_s=POLL_INTERVAL_S,
                           failures_before_giving_up=FAILURES_BEFORE_GIVING_UP,
                           on_notice=None):
    '''Poll IMDS until a notice arrives, the run ends, or the host proves not
    to be EC2.

    Runs as a daemon thread. It waits on `stop` rather than sleeping, so a run
    that finishes normally does not keep the process alive for one more
    interval.

    **Giving up is silent and permanent, and only before the first answer.**
    Every developer host and every CI runner is "not EC2", and a poller that
    complained about it once every five seconds would train everyone to ignore
    it -- so a host that never answers at all is abandoned after a few reads
    and says nothing.

    Once one read has succeeded the host is known to be EC2, and the same
    counter would then mean something entirely different: three consecutive
    failures is fifteen seconds, which an IMDS blip or a throttle reaches
    easily, and giving up there disables reclaim detection for the remaining
    hours of a batch with nothing recorded and nothing to see. So after the
    first answer this keeps polling, and only the run ending stops it.
    '''
    failures = 0
    answered = False
    while not stop.is_set():
        try:
            notice = poll_instance_action(read)
            failures = 0
            answered = True
        except Exception:
            failures += 1
            if not answered and failures >= failures_before_giving_up:
                return
            notice = None
        if notice:
            if stop.request(notice) and on_notice:
                on_notice(notice)
            return
        if stop.wait(interval_s):
            return
