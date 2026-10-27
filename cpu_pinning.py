#
# Copyright (C) 2015, 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Pure CPU-list and role-pinning contracts; no host or runtime probes."""

PIN_ROLES = ('target', 'monitor', 'testers', 'receivers')


def parse_cpu_list(text):
    '''`0-3,8` -> frozenset({0, 1, 2, 3, 8}), the kernel's cpulist format.'''
    cpus = set()
    for part in text.split(','):
        part = part.strip()
        lo, sep, hi = part.partition('-')
        if not lo.isdigit() or (sep and not hi.isdigit()):
            raise ValueError('{0!r} is not a CPU number or range'.format(part))
        lo, hi = int(lo), int(hi) if sep else int(lo)
        if hi < lo:
            raise ValueError('{0!r} is a descending range'.format(part))
        cpus.update(range(lo, hi + 1))
    return frozenset(cpus)


def format_cpu_list(cpus):
    '''The shortest cpulist for a set: {0, 1, 2, 3, 8} -> `0-3,8`.'''
    runs = []
    for cpu in sorted(cpus):
        if runs and cpu == runs[-1][1] + 1:
            runs[-1][1] = cpu
        else:
            runs.append([cpu, cpu])
    return ','.join(str(lo) if lo == hi else '{0}-{1}'.format(lo, hi)
                    for lo, hi in runs)


def resolve_pin(spec, receivers, cpus):
    '''The validated per-role cpuset, as its canonical spec, or None.

    `spec` is `role=cpulist,...` -- `target=0-7,monitor=8-9,testers=10-15`.
    Commas separate both roles and CPUs, so a token without `=` extends the
    role before it: `target=0,2,monitor=4` gives the target CPUs 0 and 2.

    Every role the run has must be named. A pinned run is one in which no role
    can reach another's cores, and an unnamed role would float over every core
    -- the pinned ones included -- so a run that pinned the target and left the
    generators unpinned would be published as isolated when it was not. The
    sets must be disjoint for the same reason, and inside `cpus` because Docker
    refuses a cpuset naming a CPU the host does not have, but only once the
    previous run's containers are gone.

    The canonical form fixes the role order and writes each set as its
    shortest cpulist, so two spellings of one layout are one cell, one stem and
    one manifest entry.
    '''
    sets = parse_pin(spec)
    if sets is None:
        return None
    wanted = [r for r in PIN_ROLES if r != 'receivers' or receivers]
    missing = [r for r in wanted if r not in sets]
    if missing:
        raise ValueError(
            '--pin leaves {0} unpinned, and an unpinned role runs on every '
            'core, the pinned ones included. Name every role the run has: '
            '{1}'.format(', '.join(missing), ', '.join(wanted)))
    if 'receivers' in sets and not receivers:
        raise ValueError('--pin names receivers, but the run has none')
    roles = [r for r in PIN_ROLES if r in sets]
    for i, a in enumerate(roles):
        for b in roles[i + 1:]:
            shared = sets[a] & sets[b]
            if shared:
                raise ValueError('--pin gives {0} and {1} the same CPUs '
                                 '({2}); the sets must be disjoint'.format(
                                     a, b, format_cpu_list(shared)))
    absent = set().union(*sets.values()) - set(cpus)
    if absent:
        raise ValueError('--pin names CPUs this host does not have ({0}); it '
                         'has {1}'.format(format_cpu_list(absent),
                                          format_cpu_list(cpus)))
    return format_pin(sets)


def format_pin(sets):
    '''{role: cpus} as the canonical spec: fixed role order, shortest lists.'''
    return ','.join('{0}={1}'.format(r, format_cpu_list(sets[r]))
                    for r in PIN_ROLES if r in sets)


def parse_pin(spec):
    '''A `--pin` spec as {role: frozenset of CPUs}, or None when unset.

    Syntax only -- which roles a run needs, overlap and the host's CPUs are
    `resolve_pin()`'s.
    '''
    if spec is None or spec == '':
        return None
    if not isinstance(spec, str):
        raise ValueError('--pin must be role=cpus[,role=cpus...], got '
                         '{0!r}'.format(spec))
    texts = {}
    role = None
    for token in spec.split(','):
        token = token.strip()
        name, sep, value = token.partition('=')
        if sep:
            role = name.strip()
            if role not in PIN_ROLES:
                raise ValueError('--pin: unknown role {0!r}; the roles are '
                                 '{1}'.format(role, ', '.join(PIN_ROLES)))
            if role in texts:
                raise ValueError('--pin: {0} is named twice'.format(role))
            texts[role] = [value]
        elif role is None:
            raise ValueError('--pin must start with role=cpus, got '
                             '{0!r}'.format(spec))
        else:
            texts[role].append(token)
    sets = {}
    for role, parts in texts.items():
        try:
            sets[role] = parse_cpu_list(','.join(parts))
        except ValueError as e:
            raise ValueError('--pin: {0}: {1}'.format(role, e))
    return sets


def pin_cpusets(canonical):
    '''A canonical `--pin` spec as {role: cpuset string}; {} when unpinned.'''
    sets = {}
    role = None
    for token in canonical.split(',') if canonical else ():
        name, sep, cpus = token.partition('=')
        if sep:
            role = name
            sets[role] = cpus
        else:
            sets[role] += ',' + token
    return sets


def pin_stem(canonical):
    '''The artifact-name part for a pinned run: `pin.target0-7.monitor8-9...`.

    Commas become `+` so the stem stays one shell word; underscores are the
    stem's own separator and are not used.
    '''
    return 'pin.' + '.'.join(
        '{0}{1}'.format(role, cpus.replace(',', '+'))
        for role, cpus in pin_cpusets(canonical).items())
