# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Operational boundaries outside native measurement clocks, never CSV metrics."""
from datetime import datetime, timezone
import json
import os
import socket
import time


class Journal:
    def __init__(self,path,attempt):
        self.path=path;self.attempt=attempt;self.start=time.monotonic_ns();self.sequence=0
        with self.path.open('x'):pass
        self.note('created')

    def note(self,phase,**details):
        now=time.monotonic_ns()
        value=dict(schema='bgperf2/native-phase/v1',attempt_id=self.attempt,sequence=self.sequence,
            phase=phase,monotonic_ns=now,elapsed_ns=now-self.start,
            utc=datetime.now(timezone.utc).isoformat(),host=socket.gethostname(),pid=os.getpid(),details=details)
        with self.path.open('a') as stream:
            stream.write(json.dumps(value,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
        self.sequence+=1
