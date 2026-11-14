# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Delay optional runtime imports/connections until an operation needs them."""
import importlib
import threading


class LazyValue:
    def __init__(self, factory):
        self._factory = factory
        self._value = None
        self._lock = threading.RLock()

    def __getattr__(self, name):
        with self._lock:
            if self._value is None:
                self._value = self._factory()
            return getattr(self._value, name)


def module(name):
    return LazyValue(lambda: importlib.import_module(name))
