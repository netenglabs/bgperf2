"""Optional, post-measurement typed Parquet export of retained graph samples.

Run the converter in a separate PyArrow environment. The measurement environment
and source CSV remain unchanged; this table is a declared derived artifact.
"""
import argparse
from contextlib import nullcontext
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import sys

COLUMNS = ['elapsed_s', 'target_cpu_percent', 'target_memory_bytes',
           'monitor_received', 'neighbors_checked', 'host_idle_percent', 'host_memory_free_bytes']
INTEGERS = {'elapsed_s', 'target_memory_bytes', 'monitor_received', 'neighbors_checked', 'host_memory_free_bytes'}


def convert(source, output):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from artifact_store import safe_absolute, publish, fsync_dir
    source, output = safe_absolute(source), safe_absolute(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Parquet destination already exists')
    before = source.stat()
    raw_sha = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            raw_sha.update(block)
    schema = pa.schema([(name, pa.int64() if name in INTEGERS else pa.float64()) for name in COLUMNS],
                       metadata={b'bgperf2.schema': b'bgperf2/retained-samples-parquet/v1',
                                 b'bgperf2.source_sha256': raw_sha.hexdigest().encode(),
                                 b'bgperf2.writer_pyarrow': pa.__version__.encode(),
                                 b'bgperf2.scope': b'Retained graph samples; missing observations are not reconstructed.'})
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(dir=output.parent, prefix='.parquet-')
    os.close(fd)
    count = 0
    try:
        with source.open(newline='') as stream, pq.ParquetWriter(pending, schema, compression='zstd') as writer:
            rows = csv.DictReader(stream)
            if rows.fieldnames != COLUMNS:
                raise ValueError('Unsupported retained sample columns')
            batch = []
            for row in rows:
                if set(row) != set(COLUMNS) or any(v is None for v in row.values()):
                    raise ValueError('Malformed sample row')
                values = {}
                for name, value in row.items():
                    if value in ('', 'None', 'null'):
                        values[name] = None
                    elif name in INTEGERS:
                        try:
                            number = Decimal(value)
                        except InvalidOperation as exc:
                            raise ValueError('Invalid count or byte value') from exc
                        if not number.is_finite() or number != number.to_integral_value():
                            raise ValueError('Nonintegral count or byte value')
                        values[name] = int(number)
                    else:
                        values[name] = float(value)
                        if not math.isfinite(values[name]):
                            raise ValueError('Nonfinite sample value')
                batch.append(values)
                count += 1
                if len(batch) >= 65536:
                    writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                    batch = []
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Sample source changed during conversion')
        if pq.ParquetFile(pending).metadata.num_rows != count:
            raise ValueError('Parquet row count differs')
        with open(pending, 'rb') as stream:
            os.fsync(stream.fileno())
        os.link(pending, output)
        fsync_dir(output.parent)
    finally:
        os.unlink(pending)
    return {'schema': 'bgperf2/retained-samples-parquet/v1', 'rows': count,
            'source_sha256': raw_sha.hexdigest(), 'columns': COLUMNS,
            'writer_pyarrow': pa.__version__, 'derived': True}


def maybe_convert(work, *, held_fds=()):
    """Optional export failures retain the CSV and explicitly report unavailability."""
    python = os.environ.get('BGPERF_PARQUET_PYTHON')
    source = work / 'raw-samples.csv'
    if not python or not source.is_file():
        return
    try:
        if not Path(python).is_absolute() or not Path(python).is_file():
            raise ValueError('BGPERF_PARQUET_PYTHON must name an absolute existing interpreter')
        # A killed converter may leave staging behind. Keep all its output
        # outside the captured work tree until it has exited successfully.
        from artifact_store import configured_store
        store = configured_store()
        with store.locked() if store else nullcontext() as lease:
            directory_context = tempfile.TemporaryDirectory(prefix='.parquet-export-', dir=store.root / 'staging' if store else work.parent)
            with directory_context as directory:
                staged = Path(directory) / 'raw-samples.parquet'
                proc = subprocess.run([python, '-I', str(Path(__file__).resolve()),
                                       '--source', str(source), '--output', str(staged)],
                                      capture_output=True, text=True, timeout=120,
                                      pass_fds=tuple(held_fds) + ((lease,) if lease is not None else ()))
                if proc.returncode:
                    raise ValueError(proc.stderr[-4000:])
                result = {'status': 'exported', **json.loads(proc.stdout)}
                # The store and work may live on different volumes. Stage the
                # copy on the work volume before exclusive local publication.
                fd, pending = tempfile.mkstemp(prefix='.parquet-publish-', dir=work)
                try:
                    with os.fdopen(fd, 'wb') as output, staged.open('rb') as incoming:
                        shutil.copyfileobj(incoming, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.link(pending, work / 'raw-samples.parquet')
                finally:
                    os.unlink(pending)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {'status': 'unavailable', 'reason': str(exc), 'source_csv_retained': True}
    from artifact_store import publish, canonical
    try:
        publish(work / 'parquet-export.json', canonical(result))
    except (OSError, ValueError) as exc:
        print(f'Optional Parquet export receipt unavailable; source retained: {exc}', file=sys.stderr)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        # -I omits this script's directory; add only the explicit local checkout.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        print(json.dumps(convert(args.source, args.output)))
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(2, str(exc) + '\n')
