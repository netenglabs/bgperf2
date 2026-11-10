#!/usr/bin/env python3
"""Prepare source-bound MRT prefix profiles offline; never launch a route worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mrt_inventory import inspect_file
from mrt_profiles import PrefixProfiles


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate selection key: '+key)
        result[key] = value
    return result


def write_json(path, value):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w+') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
        size = os.fstat(stream.fileno()).st_size
        os.lseek(stream.fileno(), 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while chunk := os.read(stream.fileno(), 1024**2): digest.update(chunk)
    return dict(path=str(path), bytes=size, sha256=digest.hexdigest())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--expected-bytes', type=int, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--profile-spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        if ':' in args.input:
            raise ValueError('MRT bind paths cannot contain colon')
        output = args.output
        if (not output.is_absolute() or output.parent.resolve(strict=True) != output.parent
                or output.exists() or output.is_symlink()):
            raise ValueError('Fresh absolute output in a canonical existing directory required')
        destination = output.parent/'workloads'
        if destination.exists() or destination.is_symlink():
            raise ValueError('Fresh workloads directory required')
        if args.profile_spec.stat().st_size > 64*1024:
            raise ValueError('Profile selection exceeds 64 KiB')
        encoded = args.profile_spec.read_bytes()
        observer = PrefixProfiles(json.loads(encoded, object_pairs_hook=unique_object))
        inventory = inspect_file(args.input, expected_size=args.expected_bytes,
            expected_sha256=args.expected_sha256, timeout_seconds=args.timeout_seconds,
            attributes=observer)
        report = inventory.pop('attribute_inventory')
        inventory['prefix_profiles'] = report
        inventory['profile_selection_sha256'] = hashlib.sha256(encoded).hexdigest()
        inventory['implementation_sha256'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in ('mrt_inventory.py', 'mrt_attributes.py', 'mrt_profiles.py',
                         'scripts/prepare_mrt_profiles.py', 'recipe_mrt.py')}
        report['workloads'] = []
        if report['status'] == 'prepared':
            destination.mkdir(mode=0o700)
            for count, profile, workload in observer.workloads(inventory['input']):
                from recipe_mrt import validate_spec
                validate_spec(workload, dict(neighbors=count,
                    prefixes_per_peer=max(p['prefixes'] for p in workload['peers'])))
                path = destination/f'peers-{count}-{profile}.mrt.json'
                artifact = write_json(path, workload)
                report['workloads'].append(dict(group_size=count, profile=profile,
                    expected_prefixes=len(workload['expected_prefixes']), artifact=artifact))
        write_json(output, inventory)
        print(json.dumps(dict(status=report['status'], output=str(output),
                              workloads=len(report['workloads']))))
        return 0 if report['status'] == 'prepared' else 2
    except (OSError, ValueError) as exc:
        print('REFUSED: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
