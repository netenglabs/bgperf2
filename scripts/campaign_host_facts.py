#!/usr/bin/env python3
'''Host, tool and image facts for a campaign manifest, as one JSON object.

The 64 GB timing validation plan requires the manifest to capture the actual
host memory, CPU, kernel, Docker version, image identities, Git revision and
measurement schema version -- and then says, in the same paragraph, "Do not
assume those facts from this plan." So they are read from the machine at the
moment a block starts rather than restated anywhere.

Image identity is the image **ID**, not the tag. `prepare` skips a tag that
already exists, so `bgperf/frr_c:10.7` is a name that outlives several
different binaries -- which is exactly how the gcov trap survived for years
and how a rebuilt exabgp image became indistinguishable from its predecessor.
The tag says what was asked for; the ID says what ran.

Prints JSON to stdout. Never raises on a fact it cannot collect: a manifest
missing the Docker version is worth more than a block that refused to start
because `docker version` was slow.
'''
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, '{0}: {1}'.format(type(exc).__name__, exc)
    if out.returncode != 0:
        return None, (out.stderr or out.stdout or '').strip()[:400]
    return out.stdout, None


def host_facts():
    facts = {}
    uname = os.uname()
    facts['kernel'] = '{0} {1}'.format(uname.sysname, uname.release)
    facts['machine'] = uname.machine
    facts['hostname'] = uname.nodename

    try:
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    facts['memory_total_kb'] = int(line.split()[1])
                elif line.startswith('SwapTotal:'):
                    facts['swap_total_kb'] = int(line.split()[1])
    except (OSError, ValueError, IndexError) as exc:
        facts['memory_error'] = '{0}: {1}'.format(type(exc).__name__, exc)

    try:
        models = set()
        cores = 0
        with open('/proc/cpuinfo', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('model name'):
                    models.add(line.split(':', 1)[1].strip())
                    cores += 1
        facts['cpu_model'] = sorted(models)[0] if models else None
        facts['cpu_threads'] = cores
    except (OSError, IndexError) as exc:
        facts['cpu_error'] = '{0}: {1}'.format(type(exc).__name__, exc)

    facts['instance'] = instance_facts()
    return facts


def instance_facts():
    '''Cloud instance identity, best effort, or None off a cloud host.

    The campaign's host-class rule is "a replacement of the same shape
    continues the campaign, anything else is a second experiment", and on a
    spot host replacements are ordinary. Instance *type* is the fact that rule
    turns on and it is the one fact not visible from the kernel: two
    `m7a.4xlarge` report the same CPU model, core count and memory as an
    `m7a.8xlarge` would report a different one, but nothing under /proc names
    the shape. Recorded so the rule is checkable from the artifact it points
    at, rather than asserted in a plan nobody can verify against.

    Read from DMI first, which needs no network: EC2 writes the instance ID to
    `board_asset_tag`. The type needs IMDS, so it is asked for with a short
    timeout and a token (IMDSv2), and its absence is recorded rather than
    raised -- a manifest missing the instance type is worth more than a block
    that refused to start because a link-local address did not answer.

    Returns None only where nothing was learned and nothing failed, which is
    a machine with neither DMI nor a link-local route. A failure is a fact
    about the reading and is recorded: **each** leaf keeps its own reason,
    because one shared slot means the second failure is dropped and an absent
    availability zone carries no explanation at all.
    '''
    facts = {}
    try:
        with open('/sys/devices/virtual/dmi/id/board_asset_tag',
                  'r', encoding='utf-8') as f:
            tag = f.read().strip()
        if tag and tag.startswith('i-'):
            facts['id'] = tag
    except OSError:
        pass

    # `-f` is load-bearing: without it curl exits 0 on an HTTP error and hands
    # back the error body as though it were the answer. An IMDS 401 would then
    # become the value of the token header on the next two calls, and a 404
    # would reach `facts['type']` -- or, filtered out for looking like HTML,
    # would leave `type` simply absent with `error` never set, which reads
    # identically to a host where IMDS was never asked. Instance type is the
    # one fact the host-class rule turns on, so "missing" and "missing because
    # X" must not look the same.
    base = 'http://169.254.169.254'
    token, token_error = _run(['curl', '-fsS', '--max-time', '2', '-X', 'PUT',
                               base + '/latest/api/token',
                               '-H', 'X-aws-ec2-metadata-token-ttl-seconds: 60'])
    headers = []
    if token and token.strip():
        headers = ['-H', 'X-aws-ec2-metadata-token: ' + token.strip()]
    elif token_error:
        facts['token_error'] = token_error
    for key, leaf in (('type', 'instance-type'),
                      ('availability_zone', 'placement/availability-zone')):
        value, error = _run(['curl', '-fsS', '--max-time', '2']
                            + headers
                            + [base + '/latest/meta-data/' + leaf])
        if value and value.strip():
            facts[key] = value.strip()
        else:
            facts['{0}_error'.format(key)] = error or 'no answer from IMDS'
    return facts or None


def docker_facts():
    facts = {}
    version, error = _run(['docker', 'version', '--format',
                           '{{.Server.Version}}'])
    facts['server_version'] = version.strip() if version else None
    if error:
        facts['version_error'] = error

    # Every bgperf image on the host, by ID. Listing them all rather than only
    # the ones this block names keeps the manifest honest about what a later
    # block could have run: the campaign's 14 configurations are resolved from
    # this same set.
    listing, error = _run(['docker', 'images', '--format',
                           '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}',
                           '--filter', 'reference=bgperf/*'])
    images = {}
    if listing:
        for line in listing.splitlines():
            parts = line.split(' ', 2)
            if len(parts) == 3:
                images[parts[0]] = {'id': parts[1], 'created': parts[2]}
    facts['bgperf_images'] = images
    if error:
        facts['images_error'] = error
    return facts


def tool_facts():
    try:
        import bgperf2
        return bgperf2.tool_provenance()
    except Exception as exc:  # noqa: BLE001 -- a manifest fact, not a run
        return {'error': '{0}: {1}'.format(type(exc).__name__, exc)}


# 1 MiB, so a 1.35 GB RIB is ~1300 reads rather than one allocation that size.
MRT_DIGEST_CHUNK = 1 << 20


def mrt_digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(MRT_DIGEST_CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def mrt_facts(paths):
    """What each MRT input was, by content and not only by length.

    The three MRT repetitions are read together as the dispersion of one cell,
    which is only true if all three replayed the same bytes -- and the RIB is
    an out-of-band download that lives outside the repository, on a volume that
    outlives the instance but is not immutable. A size alone cannot settle
    that: a re-downloaded or substituted RIB of the same length is
    indistinguishable from the original, and a reviewer checking the manifest
    for that agreement would read a match that was never tested.

    Hashing 1.35 GB costs a second or two once per block, against blocks of
    hours. It is not fatal: a digest that could not be read is recorded as the
    error, because a manifest missing one fact is worth more than a block that
    refused to start -- and `exists` plus `size_bytes` still say something,
    where an aborted block says nothing at all.
    """
    facts = {}
    for path in paths:
        entry = {'path': path, 'exists': os.path.exists(path)}
        if entry['exists']:
            entry['size_bytes'] = os.path.getsize(path)
            try:
                entry['sha256'] = mrt_digest(path)
            except OSError as exc:
                entry['digest_error'] = '{0}: {1}'.format(
                    type(exc).__name__, exc)
        # Keyed by the path, not the basename. While only one file could ever
        # be passed a basename was unambiguous; the list now comes from a
        # block's configs and can hold several, and the natural shape of a
        # re-download -- `mrt/rib.20260808.0000` beside
        # `/data/mrt-alt/rib.20260808.0000` -- collides under a basename and
        # silently records one entry. The manifest would then carry a digest
        # that appears to cover both files, which is exactly the match that
        # was never tested this digest exists to rule out.
        facts[path] = entry
    return facts


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    doc = {
        'host': host_facts(),
        'docker': docker_facts(),
        'bgperf2': tool_facts(),
    }
    if argv:
        doc['mrt_inputs'] = mrt_facts(argv)
    json.dump(doc, sys.stdout, indent=2, sort_keys=True, allow_nan=False)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
