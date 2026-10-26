# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Explicit operational pressure screens; no default host or performance policy."""
import math
from pathlib import Path
import re
import time

import recipes


def _finite(value, name, minimum=0, maximum=None):
    try:
        valid = (type(value) in (int, float) and math.isfinite(value) and
                 value >= minimum and (maximum is None or value <= maximum))
    except OverflowError:
        valid = False
    if not valid:
        raise recipes.ContractError(f'{name}: invalid finite numeric bound')


def validate_policy(policy):
    recipes._keys(policy, ('sample_seconds', 'max_gap_seconds', 'busy_percent',
                          'cpu_psi_percent', 'consecutive_intervals', 'min_memory_bytes'),
                  where='pressure policy')
    _finite(policy['sample_seconds'], 'sample_seconds', 1, 60)
    _finite(policy['max_gap_seconds'], 'max_gap_seconds', policy['sample_seconds'], 300)
    _finite(policy['busy_percent'], 'busy_percent', 0, 100)
    _finite(policy['cpu_psi_percent'], 'cpu_psi_percent', 0, 100)
    recipes._integer(policy['consecutive_intervals'], 'consecutive_intervals', 1)
    if policy['consecutive_intervals'] > 100:
        raise recipes.ContractError('consecutive_intervals exceeds implementation bound')
    recipes._integer(policy['min_memory_bytes'], 'min_memory_bytes', 0)
    return policy


def host_sample():
    """Read the Linux procfs exposed to this process, never claim namespace qualification."""
    # Preserve the source text used by this screen without copying every CPU's
    # counters into every observation on a many-core host.
    with Path('/proc/stat').open() as stream:
        aggregate = stream.readline()
    memory = ''.join(line for line in Path('/proc/meminfo').read_text().splitlines(keepends=True)
                     if line.startswith('MemAvailable:'))
    return {'monotonic_seconds': time.monotonic(), 'stat': aggregate,
            'meminfo': memory,
            'cpu_pressure': Path('/proc/pressure/cpu').read_text()}


def assess(samples, policy):
    validate_policy(policy)
    if not isinstance(samples, list) or not samples:
        raise recipes.ContractError('Missing pressure observations')
    observations, previous, streak, blocked = [], None, 0, False
    for sample in samples:
        try:
            recipes._keys(sample, ('monotonic_seconds', 'stat', 'meminfo', 'cpu_pressure'), where='pressure observation')
            at = sample['monotonic_seconds']
            _finite(at, 'sample time')
            line = sample['stat'].splitlines()[0].split()
            if line[0] != 'cpu' or len(line) < 9:
                raise ValueError('aggregate CPU counters missing')
            counters = [int(x) for x in line[1:9]]
            if min(counters) < 0:
                raise ValueError('negative CPU counter')
            memory = int(re.search(r'^MemAvailable:\s+(\d+) kB$', sample['meminfo'], re.M)[1]) * 1024
            psi = float(re.search(r'^some avg10=([\d.]+)(?:\s|$)', sample['cpu_pressure'], re.M)[1])
            _finite(psi, 'CPU PSI', 0, 100)
            busy = None
            if previous is not None:
                gap = at - previous[0]
                delta = [x - y for x, y in zip(counters, previous[1])]
                if gap <= 0 or gap > policy['max_gap_seconds'] or min(delta) < 0 or sum(delta) <= 0:
                    raise ValueError('invalid CPU interval or excessive observation gap')
                busy = 100 * (sum(delta) - delta[3] - delta[4]) / sum(delta)
                streak = streak + 1 if busy >= policy['busy_percent'] and psi >= policy['cpu_psi_percent'] else 0
            memory_block = memory < policy['min_memory_bytes']
            blocked = blocked or memory_block or streak >= policy['consecutive_intervals']
            observations.append({'monotonic_seconds': at, 'host_busy_percent': busy,
                                 'cpu_psi_percent': psi, 'memory_available_bytes': memory,
                                 'consecutive_intervals': streak, 'memory_below_floor': memory_block})
            previous = (at, counters)
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            raise recipes.ContractError(f'Unreadable pressure observation: {exc}') from exc
    return {'outcome': 'blocked' if blocked else 'passed', 'observations': observations,
            'scope': 'Explicit operational interruption screen, not host qualification or a calibrated regression policy.'}
