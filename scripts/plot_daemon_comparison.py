#!/usr/bin/env python3
"""Render the 2026 comparison from saved summaries; never run a benchmark.

No statistics are recomputed. CSV pass values are checked against the batch
summaries; the historical BIRD panels read the accepted variance review.
Selections, replacements and exclusions are specific to this campaign.
Requires matplotlib. Run from any directory with --root pointing at the repo.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path


COMPARISON = 'results/2026/2026-comparison'
HISTORY = 'results/2026/2026-timing-validation/block12-final-report/review'
PEERS = (10, 17, 24, 31, 38)
LABELS = {
    'bird 2.19.2': ('BIRD', '2.19.2'),
    'bird 3.3.2 (default threads)': ('BIRD', '3.3.2 default'),
    'bird 3.3.2 (4 threads)': ('BIRD', '3.3.2 / 4 threads'),
    'bird default': ('BIRD', 'dev 292a46adc54d'),
    'frr_c 8.5': ('FRR', '8.5'),
    'frr_c 9.1': ('FRR', '9.1'),
    'frr_c 10.0': ('FRR', '10.0'),
    'frr_c 10.7': ('FRR', '10.7'),
    'frr default': ('FRR', '10.8.0-dev'),
    'openbgp 8.8': ('OpenBGPD', '8.8'),
    'openbgp 9.2': ('OpenBGPD', '9.2'),
    'openbgp 9.3': ('OpenBGPD', '9.3'),
    'rustybgp 2026-02': ('RustyBGP', '2026-02'),
    'rustybgp 2026-08': ('RustyBGP', '2026-08'),
    'rustybgp 2026-09': ('RustyBGP', '2026-09'),
}
FAMILY_COLORS = {'BIRD': '#2463a0', 'FRR': '#d06c16',
                 'OpenBGPD': '#18846c', 'RustyBGP': '#8953a6'}
COLORS = ['#2463a0', '#d06c16', '#18846c', '#8953a6', '#b54453']


def canonical(name):
    return 'rustybgp 2026-08' if name == 'rustybgp default' else name


class Evidence:
    def __init__(self, root):
        self.root = Path(root)
        self.documents = {}
        self.claims = {}
        self.raw_rows = {}

    def read(self, source):
        if source not in self.documents:
            self.documents[source] = json.loads((self.root / source).read_text())
        return self.documents[source]

    def statistic(self, source, cell, metric, field, scope='metrics'):
        value = cell[scope][metric][field]
        if value is None:
            raise ValueError(f'Withheld: {source}: {cell["description"]}: {metric}.{field}')
        key = (source, cell['description'], scope, metric, field)
        self.claims[key] = {'source': source, 'cell': cell['description'],
                            'scope': scope, 'metric': metric, 'field': field, 'value': value}
        return value

    def batch(self, step, test=None, omit=()):
        test = test or f'2026-comparison-{step}'
        source = f'{COMPARISON}/{step}/{test}.summary.json'
        doc = self.read(source)
        csv_source = source.replace('.summary.json', '.csv')
        with (self.root / csv_source).open(newline='') as stream:
            reader = csv.DictReader(stream, skipinitialspace=True)
            rows = [{k.strip(): v.strip() for k, v in row.items()} for row in reader]
        result = []
        for cell in doc['cells']:
            if canonical(cell['name']) in omit:
                continue
            observed = []
            for p in cell['passes']:
                name = cell['name'] + f' #{p["repetition"]}'
                matches = [r for r in rows if r['name'] == name]
                if len(matches) != 1:
                    raise ValueError(f'{csv_source}: expected one row for {name}')
                row = matches[0]
                failed = row['failed'] == 'FAILED'
                if failed != (p['state'] == 'failed') or p['state'] not in ('observed', 'failed'):
                    raise ValueError(f'{csv_source}: pass state mismatch for {name}')
                if not failed:
                    observed.append(row)
            for metric in ('elapsed (s)', 'max mem (GB)', 'max cpu %', 'received', 'min free mem (GB)'):
                if [float(r[metric]) for r in observed] != cell['metrics'][metric]['values']:
                    raise ValueError(f'{csv_source}: values disagree for {cell["name"]}: {metric}')
            self.raw_rows[(source, cell['name'])] = [r for r in rows if
                any(r['name'] == cell['name'] + f' #{p["repetition"]}' for p in cell['passes'])]
            result.append(self.record(source, cell, test if step == 'rustybgp-head' else step))
        return result

    def record(self, source, cell, series):
        name = canonical(cell['name'])
        family, build = LABELS[name]
        excluded = series == 'rrc00-n38' and name == 'rustybgp 2026-08'
        record = {'series': series, 'source': source, 'source_cell': cell['name'],
                  'name': name, 'family': family, 'build': build,
                  'peers': cell['identity']['peers'], 'excluded': excluded,
                  'status': 'excluded_time_memory_diagnostic' if excluded else 'included',
                  'reason': 'Below 15% host free-memory guardrail' if excluded else '',
                  'passes': cell['passes'], 'metrics': {}}
        for metric in ('elapsed (s)', 'max mem (GB)', 'max cpu %', 'received', 'min free mem (GB)'):
            if excluded and metric in ('elapsed (s)', 'max cpu %'):
                continue
            record['metrics'][metric] = {field: self.statistic(source, cell, metric, field)
                for field in ('median', 'min', 'max', 'n', 'values')}
        return record

    def validate_existing_claims(self):
        doc = self.read('docs/2026-daemon-comparison-report.claims.json')
        for claim in doc['figures']:
            source = self.read(claim['source'])
            cells = [c for c in source['cells'] if c['name'] == claim['cell']]
            if len(cells) != 1 or cells[0]['metrics'][claim['metric']][claim['field']] != claim['value']:
                raise ValueError(f'Existing report claim mismatch: {claim}')


def load_comparison(evidence):
    synth = evidence.batch('synth')
    curve = []
    for peers in PEERS:
        rows = evidence.batch(f'rrc00-n{peers}',
                              omit=('rustybgp 2026-08',) if peers == 24 else ())
        if peers == 24:
            replacement = evidence.batch('rrc00-n24-rustybgp-rerun')[0]
            rows.append(replacement)
        curve.extend(rows)
    return synth, curve


def style_axis(ax, xlabel):
    ax.set_xlabel(xlabel)
    ax.set_axisbelow(True)
    ax.grid(alpha=.20)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)


def save(fig, out, name, title, subtitle, footnote):
    fig.suptitle(title, fontsize=19, fontweight='bold', x=.03, ha='left', y=.985)
    fig.text(.03, .935, subtitle, fontsize=10, va='top')
    fig.text(.03, .022, footnote, fontsize=9, va='bottom', color='#414b57')
    fig.tight_layout(rect=(.015, .09, .985, .89), w_pad=2.5)
    fig.savefig(out / f'{name}.png', dpi=150, facecolor='white')
    fig.savefig(out / f'{name}.svg', facecolor='white')
    import matplotlib.pyplot as plt
    plt.close(fig)


def overview(rows, out, name, title, subtitle):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(16, 9), sharey=True)
    labels = [f'{r["family"]} {r["build"]}' for r in rows]
    for ax, metric, field, label in zip(axes,
            ('elapsed (s)', 'max mem (GB)', 'max cpu %'), ('median', 'max', 'median'),
            ('Elapsed seconds · lower is better', 'Peak sampled target memory (GB)',
             'Median of per-pass peak CPU (%)')):
        for y, row in enumerate(rows):
            m = row['metrics'].get(metric)
            if not m:
                ax.text(.03, y, 'excluded: memory pressure', transform=ax.get_yaxis_transform(),
                        fontsize=8, color='#8c3941')
                continue
            value, color = m[field], FAMILY_COLORS[row['family']]
            ax.hlines(y, m['min'], m['max'], color=color, linewidth=2)
            ax.scatter(value, y, s=50, edgecolors=color,
                       facecolors='white' if row['excluded'] else color, zorder=3)
            ax.annotate(f'{value:g}' + ('*' if row['excluded'] else ''), (max(value, m['max']), y),
                        xytext=(6, 0), textcoords='offset points', va='center', fontsize=9)
        ax.set_xlim(left=0)
        ax.margins(x=.19)
        style_axis(ax, label)
    axes[0].set_yticks(range(len(rows)), labels)
    axes[0].invert_yaxis()
    save(fig, out, name, title, subtitle,
         'Whiskers: sampled pass range, not confidence intervals. Time: median; memory: maximum across passes.\n'
         'CPU is a sampled peak, not CPU-seconds or sustained utilization. 100% = one core. * Memory diagnostic from excluded runs.')


def family_curves(curve, out, family):
    import matplotlib.pyplot as plt
    rows = [r for r in curve if r['family'] == family]
    names = list(dict.fromkeys(r['name'] for r in rows))
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.5))
    for i, name in enumerate(names):
        selected = [r for r in rows if r['name'] == name]
        for ax, metric, field in zip(axes, ('elapsed (s)', 'max mem (GB)'), ('median', 'max')):
            accepted = [r for r in selected if not r['excluded']]
            x = [r['peers'] for r in accepted]
            y = [r['metrics'][metric][field] for r in accepted]
            ax.plot(x, y, marker=('o', 's', '^', 'D', 'v')[i],
                    linestyle=('-', '--', '-.', ':', '--')[i],
                    markerfacecolor='white', color=COLORS[i], label=accepted[0]['build'])
            ax.fill_between(x, [r['metrics'][metric]['min'] for r in accepted],
                            [r['metrics'][metric]['max'] for r in accepted], color=COLORS[i], alpha=.12)
            if metric == 'max mem (GB)':
                for r in selected:
                    if r['excluded']:
                        ax.scatter(r['peers'], r['metrics'][metric]['max'], marker='X',
                                   s=100, facecolors='white', edgecolors=COLORS[i], zorder=4)
                        ax.annotate('110.789 GB\nexcluded timing', (38, 110.789),
                                    xytext=(-90, -5), textcoords='offset points', fontsize=9)
        axes[0].legend(fontsize=9, loc='upper left')
    for ax, ylabel in zip(axes, ('Median elapsed (s)', 'Maximum sampled target memory (GB)')):
        style_axis(ax, 'Full-table peers (1.05M offered prefixes per peer)')
        ax.set_ylabel(ylabel)
        ax.set_xticks(PEERS)
        ax.set_ylim(bottom=0)
    if family == 'RustyBGP':
        axes[1].axhline(61.44, color='#8c3941', linestyle=':', linewidth=1.4)
        axes[1].text(10.3, 63.5, 'Entire smaller host: 61.44 GB; all roles must fit', fontsize=8)
    caveat = ('RustyBGP August at 24 peers uses the replacement cell; its 38-peer time is excluded.'
              if family == 'RustyBGP' else
              'Overlapping lines indicate similar observations; they do not establish an extra release improvement.')
    save(fig, out, 'versions-' + family.lower(), family + ': release behavior as peer count grows',
         'rrc00 · sink monitor · m7a.8xlarge · target 8 cores · 3 passes per point · separate scales for time and memory',
         'Bands: sampled pass range. Curves show measured points only. No projected capacity or fitted scaling law.\n'
         + caveat)


def cross_daemon(curve, out):
    import matplotlib.pyplot as plt
    names = ['bird 2.19.2', 'bird 3.3.2 (default threads)', 'frr_c 10.7',
             'openbgp 9.3', 'rustybgp 2026-02', 'rustybgp 2026-08']
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for i, name in enumerate(names):
        rows = [r for r in curve if r['name'] == name and not r['excluded']]
        family, build = LABELS[name]
        color = FAMILY_COLORS[family]
        dash = '--' if i in (1, 5) else '-'
        for ax, metric, field in zip(axes, ('elapsed (s)', 'max mem (GB)'), ('median', 'max')):
            ax.plot([r['peers'] for r in rows], [r['metrics'][metric][field] for r in rows],
                    marker='o', linestyle=dash, color=color, label=f'{family} {build}')
    for ax, ylabel in zip(axes, ('Median elapsed (s)', 'Maximum sampled target memory (GB)')):
        style_axis(ax, 'Full-table peers')
        ax.set_ylabel(ylabel)
        ax.set_xticks(PEERS)
        ax.set_ylim(bottom=0)
    axes[0].legend(fontsize=8)
    save(fig, out, 'rrc00-shared-scales', 'Selected builds on the same time and memory scales',
         'rrc00 · sink monitor · m7a.8xlarge · target 8 cores · medians from 3 passes',
         'Selection is explicit; all tested releases appear in the version figures and 38-peer overview.\n'
         'Unequal export counts and protocol behavior prevent a universal ranking. See version figures for pass ranges.')


def historical_bird(evidence, out):
    import matplotlib.pyplot as plt
    panels = [('screen-peers', '250 sessions × 2,000 prefixes\n5 passes', 'elapsed (s)', 'metrics'),
              ('screen-diversity', '50 paths per prefix\n3 passes', 'elapsed (s)', 'metrics'),
              ('screen-reload', 'Policy recalculation only\n3 passes', 'reload_s', 'intervals')]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.5))
    for ax, (series, title, metric, scope) in zip(axes, panels):
        source = f'{HISTORY}/{series}.json'
        doc = evidence.read(source)
        cells = doc['summary']['cells'] if scope == 'metrics' else doc['cells']
        if series == 'screen-peers':
            cells = [c for c in cells if c['identity']['peers'] == 250]
        for i, c in enumerate(cells):
            stats = {f: evidence.statistic(source, c, metric, f, scope)
                     for f in ('median', 'min', 'max', 'n', 'values')}
            ax.hlines(i, stats['min'], stats['max'], color=COLORS[i], linewidth=2)
            ax.scatter(stats['values'], [i] * len(stats['values']), s=30, alpha=.55, color=COLORS[i])
            ax.scatter(stats['median'], i, s=90, marker='|', linewidths=2.5, color='black', zorder=4)
            label = f'{stats["median"]:.2f}' if scope == 'intervals' else f'{stats["median"]:g}'
            ax.annotate(label, (stats['max'], i), xytext=(6, 0),
                        textcoords='offset points', va='center', fontsize=9)
        ax.set_yticks(range(3), ['2.19.2', '3.3.2 default', '3.3.2 / 4 threads'])
        ax.set_title(title, fontsize=11)
        ax.invert_yaxis()
        ax.set_ylim(2.55, -.55)
        ax.set_xlim(left=0)
        ax.margins(x=.25)
        style_axis(ax, 'Seconds · lower is better')
    save(fig, out, 'bird-earlier-workloads', 'BIRD: different jobs reward different releases and thread settings',
         'Historical September screen · GoBGP monitor · m7a.4xlarge · never pooled with the sink comparison',
         'Dots: individual observations; black tick: published median. Peer timing is not separated by the review at 5 passes.\n'
         'Reload is the measured recalculation interval (~2 s sampling), not initial table loading or whole-run elapsed time.')


def rusty_arrangements(evidence, out):
    import matplotlib.pyplot as plt
    panels = [('synth', 'Synthetic · pinned'), ('synth-unpinned', 'Synthetic · unpinned'),
              ('mrt', 'Route Views MRT · pinned')]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.5))
    records = []
    for ax, (suffix, title) in zip(axes, panels):
        rows = evidence.batch('rustybgp-head', '2026-comparison-rustybgp-head-' + suffix)
        if suffix == 'synth-unpinned':
            rows += evidence.batch('rustybgp-head-unpinned-rerun')
        records.extend(rows)
        for i, row in enumerate(rows):
            m = row['metrics']['elapsed (s)']
            ax.hlines(i, m['min'], m['max'], color=COLORS[i], linewidth=2)
            ax.scatter(m['values'], [i] * len(m['values']), color=COLORS[i], alpha=.65)
            ax.scatter(m['median'], i, marker='|', color='black', s=100, linewidths=2)
            ax.annotate(f'{m["median"]:g} s', (m['max'], i), xytext=(5, 0),
                        textcoords='offset points', va='center', fontsize=9)
        labels = [r['build'] + (' rerun' if i == 2 else '') for i, r in enumerate(rows)]
        ax.set_yticks(range(len(rows)), labels)
        ax.set_title(title, fontsize=12)
        ax.set_ylim(len(rows) - .45, -.55)
        ax.set_xlim(0, 200 if suffix == 'synth' else 65 if suffix == 'synth-unpinned' else 35)
        style_axis(ax, 'Elapsed seconds · separate panel scales')
    save(fig, out, 'rustybgp-arrangements', 'RustyBGP: CPU arrangement matters more here than the dated-head change',
         'm7a.8xlarge only · August 9eeeebbd50 vs September 783d6dfd00 · 5 attempted passes per cell',
         'September unpinned: 4 successes and 1 failed pass; failure is not a zero. Its separate rerun has 5 successes.\n'
         'Pinned synthetic sessions expired in both builds. Source and dependency graph changed together; this is not a source-only test.')
    return records


def write_data(evidence, records, out):
    fields = ['series', 'family', 'build', 'peers', 'status', 'reason', 'source', 'source_cell',
              'metric', 'median', 'min', 'max', 'n', 'values', 'passes']
    with (out / 'comparison-data.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in records:
            for metric in ('elapsed (s)', 'max mem (GB)', 'max cpu %', 'received', 'min free mem (GB)'):
                m = row['metrics'].get(metric, {})
                entry = {k: row[k] for k in fields[:8]}
                entry.update(metric=metric, **m)
                entry['values'] = json.dumps(m.get('values'))
                entry['passes'] = json.dumps(row['passes'])
                writer.writerow(entry)
    rows = []
    for record in records:
        for row in evidence.raw_rows[(record['source'], record['source_cell'])]:
            published = {key: value for key, value in row.items() if key != 'testers (s)'}
            rows.append(dict(published, source=record['source'].replace('.summary.json', '.csv'),
                             selection_status='failed' if row['failed'] == 'FAILED' else record['status'],
                             selection_reason=row['MSG'] if row['failed'] == 'FAILED' else record['reason']))
    fields = list(rows[0])
    with (out / 'comparison-passes.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {'schema': 'bgperf2/comparison-plot-evidence/v1',
                'note': 'Statistics copied from summaries/reviews; no new medians or speedups. Excluded raw rows retain selection_status.',
                'sources': {s: hashlib.sha256((evidence.root / s).read_bytes()).hexdigest()
                            for s in sorted(evidence.documents)},
                'figures': list(evidence.claims.values())}
    (out / 'plot-evidence.json').write_text(json.dumps(manifest, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('docs/2026-daemon-comparison-assets'))
    args = parser.parse_args()
    out = args.output if args.output.is_absolute() else args.root / args.output
    evidence = Evidence(args.root)
    evidence.validate_existing_claims()
    synth, curve = load_comparison(evidence)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.fonttype': 'none'})
    out.mkdir(parents=True, exist_ok=True)
    overview(synth, out, 'synthetic-comparison', 'Five million distinct prefixes: time, memory and CPU',
             '50 BIRD generators × 100,000 prefixes · sink monitor · m7a.4xlarge · target 8 cores · 3 passes')
    overview([r for r in curve if r['peers'] == 38], out, 'rrc00-38-comparison',
             '38 full-table peers: compare every tested build',
             'rrc00 · sink monitor · m7a.8xlarge · target 8 cores · 3 passes · final export counts differ slightly')
    for family in FAMILY_COLORS:
        family_curves(curve, out, family)
    cross_daemon(curve, out)
    historical_bird(evidence, out)
    extra = rusty_arrangements(evidence, out)
    write_data(evidence, synth + curve + extra, out)
    print(f'Wrote 9 figures (PNG + SVG), two CSVs and plot-evidence.json to {out}')
    count = len(evidence.read('docs/2026-daemon-comparison-report.claims.json')['figures'])
    print(f'Validated {count} existing claims; captured {len(evidence.claims)} plotted source fields.')


if __name__ == '__main__':
    main()
