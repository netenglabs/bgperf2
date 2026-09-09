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
    return facts


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


def mrt_facts(paths):
    facts = {}
    for path in paths:
        entry = {'path': path, 'exists': os.path.exists(path)}
        if entry['exists']:
            entry['size_bytes'] = os.path.getsize(path)
        facts[os.path.basename(path)] = entry
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
