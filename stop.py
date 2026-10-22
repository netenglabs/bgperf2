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

'''Stopping a run on purpose, without recording it as done.

A SIGTERM abandons the run in flight -- a long MRT cell cannot be finished in
the time a terminating host allows -- and the guarantee kept is that nothing
half-done is recorded as done. Whatever decides when to send that signal, and
how to continue afterwards, lives outside the engine.

Pure; the test suite exercises it with no signals.
'''

import threading


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

    **The first reason wins.** Whatever asked for the stop first is what a
    reader needs, not whatever touched it last.

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
