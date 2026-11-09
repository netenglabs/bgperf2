#!/usr/bin/env python3
"""Inventory a frozen MRT file offline; no Docker, selection or route worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mrt_inventory import inspect_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--expected-bytes', type=int, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--timeout-seconds', type=int, default=1800)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    try:
        if (not output.is_absolute() or output.parent.resolve(strict=True) != output.parent
                or output.exists() or output.is_symlink()):
            raise ValueError('Fresh absolute output in a canonical existing directory required')
        value = inspect_file(args.input, expected_size=args.expected_bytes,
                             expected_sha256=args.expected_sha256,
                             timeout_seconds=args.timeout_seconds)
        value['implementation_sha256'] = hashlib.sha256((ROOT/'mrt_inventory.py').read_bytes()).hexdigest()
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        print(json.dumps(dict(status='complete', output=str(output), peers=len(value['peers']))))
        return 0
    except (OSError, ValueError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
