#!/usr/bin/env python3
"""Write one deterministic offline MRT protocol control and its declared spec."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mrt_controls import CASES, control


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=CASES)
    parser.add_argument('--target-asn', required=True, type=int)
    parser.add_argument('--observer-asn', required=True, type=int)
    parser.add_argument('--source-asn', required=True, type=int)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output_dir)
        if (not output.is_absolute() or output.parent.resolve(strict=True) != output.parent
                or output.exists() or output.is_symlink()):
            raise ValueError('Fresh absolute output directory with existing canonical parent required')
        data, spec = control(args.case, output/'input.mrt', target_asn=args.target_asn,
                             observer_asn=args.observer_asn, source_asn=args.source_asn)
        output.mkdir(mode=0o700)
        (output/'input.mrt').write_bytes(data)
        (output/'mrt-spec.json').write_text(json.dumps(spec, indent=2)+'\n')
        print(json.dumps({'status': 'prepared', 'output_dir': str(output),
                          'input': spec['input'], 'expected_count': len(spec['expected_prefixes']),
                          'scope': 'Offline fixture only; no route worker or attribute qualification.'}))
        return 0
    except (OSError, ValueError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
