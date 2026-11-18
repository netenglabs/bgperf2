# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Saved inputs for offline reconstruction of the six native bench graphs."""
import hashlib
import json
import math
from pathlib import Path

COLUMNS = ['elapsed_s','target_cpu_percent','target_memory_bytes','observer_prefixes',
           'neighbors_checked','host_idle_percent','host_available_bytes']


def validate(document):
    if set(document) != {'schema','prefix','columns','samples','samples_sha256'} or document['schema'] != 'bgperf2/bench-graph-data/v1':
        raise ValueError('Unsupported bench graph data')
    if document['columns'] != COLUMNS or Path(document['prefix']).name != document['prefix'] or not document['prefix']:
        raise ValueError('Invalid graph columns/prefix')
    rows=document['samples']
    if not isinstance(rows,list) or any(not isinstance(row,list) or len(row)!=7 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in row) for row in rows):
        raise ValueError('Invalid graph samples')
    digest=hashlib.sha256(json.dumps(rows,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if digest != document['samples_sha256']:raise ValueError('Graph sample checksum differs')
    return document


def save(runtime, samples, prefix, results_dir):
    rows=[list(row) for row in samples]
    doc=dict(schema='bgperf2/bench-graph-data/v1',prefix=prefix,columns=COLUMNS,samples=rows,
        samples_sha256=hashlib.sha256(json.dumps(rows,separators=(',',':'),allow_nan=False).encode()).hexdigest())
    validate(doc)
    runtime.atomic_write_json(str(Path(results_dir)/(prefix+'.graph-data.json')),doc)


def render(runtime,args):
    path=Path(args.input)
    if path.is_symlink():raise ValueError('Symlink graph input refused')
    if path.is_dir():
        files=sorted(path.rglob('*.graph-data.json'))
        if not files:raise ValueError('No saved graph data')
        from types import SimpleNamespace
        for source in files:
            render(runtime,SimpleNamespace(input=str(source),results_dir=str(Path(args.results_dir)/source.parent.relative_to(path))))
        return
    if path.stat().st_size>256*1024**2:raise ValueError('Graph data exceeds 256 MiB')
    doc=validate(json.loads(path.read_text()))
    if not doc['samples']:raise ValueError('No measured graph samples')
    Path(args.results_dir).mkdir(parents=True,exist_ok=True)
    runtime.create_bench_graphs(doc['samples'],prefix=doc['prefix'],results_dir=args.results_dir)
