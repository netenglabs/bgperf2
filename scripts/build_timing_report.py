#!/usr/bin/env python3
# Copyright (C) 2026 bgperf2 contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''The campaign's final report, rendered from documents that already exist.

Block 12 publishes what the campaign measured.  Everything numeric in it comes
out of `timing_variance_review.py`'s series documents, which came out of
`summary.py`, which is the same module each block used to summarise its own
passes.  This file computes **no statistic of its own** -- not a median, not a
percentage, not a difference between two medians -- and that is the single rule
it is built around.  A report that re-derived its own numbers would disagree
with the blocks eventually, on exactly the rows a reader cared about, and there
would be no way to tell which of the two was wrong.

So what is left to do is arrangement and claiming, and the claiming is where a
report goes wrong.  The narrative lives in a claims document, written by hand,
in which **every claim cites the figures it rests on** -- series, cell, metric,
field, and the value the author believes is there.  This resolves each citation
against the review and refuses the report if any of them is absent or
disagrees.  That is the plan's "calculation and source QA" as code: a claim
whose number moved when a block was re-measured stops the build instead of
being published beside a table that contradicts it.

Four refusals, each of which is a way a benchmark report lies:

- **A claim with no citation is refused.**  Prose with no figure under it is
  the part of a report nobody can check, and it is where the conclusions are.
- **A citation that does not match the review is refused**, and the message
  names both values.  Never rounded into agreement: the review's own rounding
  is what the value is compared against, and anything else is this file having
  an opinion about a number.
- **`testers (s)` may not be published or cited.**  It is in every stats row
  and it is the legacy field whose interpretation this campaign exists to
  replace; the plan's exit criterion is that no claim depends on it.  The
  decomposition (`first_prefix_s`, `injection_s`, `post_injection_tail_s`,
  `convergence_s`, `assurance_s`) is published in its place.
- **A dispersion over fewer than two observations is not published as a
  dispersion.**  `summary.py` already withholds it; this carries the
  withholding through to the page rather than printing an empty cell that
  reads as zero.

Pure: no Docker, no results directories, no network.  Review documents in,
`report.json` and `report.html` out.
'''
import argparse
import datetime
import html
import json
import os
import sys

REPORT_SCHEMA = 'bgperf2/timing-report/v1alpha1'
REVIEW_SCHEMA = 'bgperf2/timing-variance-review/v1alpha1'
CLAIMS_SCHEMA = 'bgperf2/timing-report-claims/v1alpha1'

# The legacy field, named once so the refusal and the withheld note cannot
# drift apart. It is a real column in every stats row; what it is not is a
# send time, which is the reading the campaign was built to retire.
LEGACY_METRIC = 'testers (s)'

# What the report publishes per cell, in this order, and where each comes from.
# `elapsed (s)` is the decision metric and leads; the rest are the plan's "CPU
# and memory comparisons" and its low-memory and contention findings.
PUBLISHED_METRICS = (
    ('elapsed (s)', 'end to end'),
    ('max cpu %', 'peak target CPU'),
    ('max mem (GB)', 'peak target memory'),
    ('min free mem (GB)', 'lowest free memory on the host'),
    ('max foreign cpu %', 'peak CPU from processes that are not bgperf2'),
)

# The decomposition, which is the point of the campaign: the interval each
# published second belongs to, rather than one number nobody can attribute.
# Names are the review's own keys, so a renamed interval fails here instead of
# being silently dropped from the report.
PUBLISHED_INTERVALS = (
    ('first_prefix_s', 'to the first prefix at the monitor'),
    ('injection_s', 'generator send, where a table crossed it'),
    # Not an interval, and published anyway: it is how many offered prefixes
    # crossed the span `injection_s` measures, and without it that span cannot
    # be read at all. The review carries it for exactly this reason.
    ('offered_in_interval', 'prefixes that crossed that span'),
    ('post_injection_tail_s', 'after the send finished (signed)'),
    ('convergence_s', 'to the converged table'),
    ('assurance_s', 'held steady after converging'),
    ('delivery_complete_s', 'to the completed export series'),
)

# An interval is a duration of something only if something crossed it. A BIRD
# 2.19 generator's offered count is queue-side and saturates before the first
# poll, so `injection_s` comes back 0.0 with nothing having crossed it -- a
# span nothing crossed, not a send that took no time. Published as a bare `0`
# it is the most confident wrong number on the page, and it appeared 34 times
# in the first real build, on a page whose own preamble promises that nothing
# absent is printed as a zero.
WITNESSED_INTERVALS = {'injection_s': 'offered_in_interval'}

# The readings `order_relation()` returns that actually are a relation. Its
# other answers are sentences saying why there is none ('too few
# observations', and the withheld-by-name case for a series whose passes ran
# matrices of different sizes), so they are prose rather than vocabulary and
# cannot be matched on. An allowlist is the only form of this test that does
# not have to guess at wording that may change.
ORDER_RELATIONS = ('rises with position', 'falls with position', 'neither',
                   'tied')

# Intervals a series carries only when its workload has them. Published where
# they exist and left out of the table entirely where they do not -- a column
# of `withheld` in every row of six other series says nothing except that a
# BIRD policy reload is not part of an MRT playback, which the workload label
# already said.
OPTIONAL_INTERVALS = (
    ('reload_s', 'to recalculate policy after a reload'),
    ('reload_resolution_s', 'the reload sampler\'s own resolution'),
)


def read_json(path):
    with open(path, 'r') as handle:
        return json.load(handle)


def load_review(review_dir, problems):
    '''Every series document in the review directory, keyed by series name.'''
    series = {}
    blocks = None
    if not os.path.isdir(review_dir):
        problems.append('no review at {0}; the report is rendered from the '
                        'variance review and cannot be written without '
                        'one'.format(review_dir))
        return series, blocks
    for name in sorted(os.listdir(review_dir)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(review_dir, name)
        try:
            document = read_json(path)
        except (ValueError, OSError) as failure:
            problems.append('{0} is not readable JSON: {1}'.format(
                path, failure))
            continue
        if name == 'blocks.json':
            blocks = document
            continue
        if name == 'problems.json':
            continue
        if document.get('schema') != REVIEW_SCHEMA:
            problems.append('{0} is not a {1} document'.format(
                path, REVIEW_SCHEMA))
            continue
        name_of = document.get('series')
        if not isinstance(name_of, str) or not name_of.strip():
            # Reported rather than raised. Everything below this function is
            # the refusal the report exists to print, and a `KeyError`
            # traceback in its place is the refusal not printed.
            problems.append('{0} declares no `series`, so nothing can cite '
                            'it'.format(path))
            continue
        if name_of in series:
            problems.append('{0} and {1} both declare the series {2!r}; one '
                            'would silently replace the other and every '
                            'citation would resolve against whichever was '
                            'read last'.format(series[name_of]['_path'],
                                               os.path.basename(path),
                                               name_of))
            continue
        document['_path'] = os.path.basename(path)
        series[name_of] = document
    if not series:
        problems.append('{0} holds no series documents; there is nothing to '
                        'report'.format(review_dir))
    return series, blocks


def cell_of(document, description):
    for cell in document.get('cells') or []:
        if cell.get('description') == description:
            return cell
    return None


def summary_cell_of(document, description):
    for cell in (document.get('summary') or {}).get('cells') or []:
        if cell.get('description') == description:
            return cell
    return None


def figure(series_doc, citation, problems, where):
    '''One cited number, resolved against the review.

    Returns `(value, source)` or `(None, None)` having reported why.  The
    source travels with the value everywhere below: a figure in the report
    that cannot name the document it came from is a figure this file invented.
    '''
    description = citation.get('cell')
    metric = citation.get('metric')
    interval = citation.get('interval')
    field = citation.get('field', 'median')
    if metric and interval:
        problems.append('{0}: cites both a metric and an interval; one figure '
                        'has one source'.format(where))
        return None, None
    if not metric and not interval:
        # Named as malformed rather than left to fall through: untouched, it
        # reached the metric branch and reported "<cell> publishes no None",
        # which sends an author looking for a missing figure instead of a
        # missing key.
        problems.append('{0}: cites neither a metric nor an interval, so '
                        'there is no figure to resolve'.format(where))
        return None, None
    if metric == LEGACY_METRIC:
        problems.append('{0}: cites {1!r}, the legacy field this campaign '
                        'exists to replace; cite the decomposition '
                        'instead'.format(where, LEGACY_METRIC))
        return None, None

    if interval:
        cell = cell_of(series_doc, description)
        if cell is None:
            problems.append('{0}: {1!r} is not a cell of {2}'.format(
                where, description, series_doc['series']))
            return None, None
        block = (cell.get('intervals') or {}).get(interval)
        source = '{0}#cells[{1}].intervals.{2}.{3}'.format(
            series_doc['_path'], description, interval, field)
    else:
        cell = summary_cell_of(series_doc, description)
        if cell is None:
            problems.append('{0}: {1!r} is not a cell of {2}'.format(
                where, description, series_doc['series']))
            return None, None
        block = (cell.get('metrics') or {}).get(metric)
        source = '{0}#summary.cells[{1}].metrics.{2}.{3}'.format(
            series_doc['_path'], description, metric, field)
    if not isinstance(block, dict):
        problems.append('{0}: {1} publishes no {2}'.format(
            where, description, interval or metric))
        return None, None
    if field not in block:
        problems.append('{0}: {1}.{2} has no {3}'.format(
            where, description, interval or metric, field))
        return None, None
    value = block[field]
    if field in ('stdev', 'cv_percent') and block.get('n', 0) < 2:
        # Carried through rather than printed. `summary.py` withholds a
        # dispersion over one observation; a report that prints the withheld
        # value anyway is the one place the rule could be undone.
        problems.append('{0}: {1}.{2} has n={3}, so it has no {4}'.format(
            where, description, interval or metric, block.get('n'), field))
        return None, None
    return value, source


def check_claims(claims, series, problems):
    '''Every claim, against the review it says it rests on.'''
    if claims.get('schema') != CLAIMS_SCHEMA:
        problems.append('the claims document is not {0}: {1!r}'.format(
            CLAIMS_SCHEMA, claims.get('schema')))
        return []
    checked = []
    entries = claims.get('claims')
    if not isinstance(entries, list) or not entries:
        problems.append('the claims document holds no claims; a report with '
                        'no answer in it is a table dump')
        return []
    seen = set()
    for index, entry in enumerate(entries):
        where = 'claim {0}'.format(entry.get('id') if isinstance(entry, dict)
                                   else index)
        if not isinstance(entry, dict):
            problems.append('{0}: is {1}, not an object'.format(
                where, type(entry).__name__))
            continue
        name = entry.get('id')
        if not isinstance(name, str) or not name.strip():
            problems.append('{0}: has no usable `id`'.format(where))
            continue
        if name in seen:
            problems.append('{0}: two claims share this id, so one of them '
                            'cannot be cited or corrected'.format(where))
        seen.add(name)
        text = str(entry.get('text') or '').strip()
        if not text:
            problems.append('{0}: has no text'.format(where))
            continue
        if LEGACY_METRIC in text:
            problems.append('{0}: names {1!r}; the plan\'s exit criterion is '
                            'that no claim depends on it'.format(
                                where, LEGACY_METRIC))
        citations = entry.get('cites')
        if not isinstance(citations, list) or not citations:
            # The rule this file exists for. Prose with no figure under it is
            # the part of a report nobody can check, and it is where the
            # conclusions live.
            problems.append('{0}: cites nothing; a claim with no figure under '
                            'it is the part of a report nobody can '
                            'check'.format(where))
            continue
        resolved = []
        for citation in citations:
            if not isinstance(citation, dict):
                problems.append('{0}: a citation is {1}, not an object'.format(
                    where, type(citation).__name__))
                continue
            series_name = citation.get('series')
            document = series.get(series_name)
            if document is None:
                problems.append('{0}: cites series {1!r}, which the review '
                                'does not hold'.format(where, series_name))
                continue
            value, source = figure(document, citation, problems, where)
            if source is None:
                continue
            if 'value' not in citation:
                # The headline refusal is not opt-in. Without the value the
                # author believes is there, nothing compares the prose to the
                # review -- the citation resolves, publishes whatever the
                # review says, and the claim above it is unchecked. That is
                # the whole mechanism, made absent by omitting one key.
                problems.append('{0}: cites {1} without saying what value it '
                                'rests on, so nothing checks the claim against '
                                'the review'.format(where, source))
                continue
            stated = citation['value']
            if value is None:
                # A claim may not rest on a figure the review withheld. It
                # resolved, so it would have rendered as "= withheld" directly
                # beneath the conclusion it supposedly supports.
                problems.append('{0}: cites {1}, which the review '
                                'withheld'.format(where, source))
                continue
            if not values_agree(stated, value):
                # Named both ways round, deliberately. "A citation does not
                # match" sends an author to look for a typo; the two numbers
                # side by side usually say which block moved.
                problems.append(
                    '{0}: cites {1} as {2!r} and the review says {3!r}'.format(
                        where, source, stated, value))
                continue
            resolved.append({'source': source, 'value': value,
                             'series': series_name,
                             'cell': citation.get('cell'),
                             'of': citation.get('metric')
                             or citation.get('interval')})
        # Where it will be rendered, checked rather than defaulted. The page
        # emits a claim under the summary or under its own series and nowhere
        # else, so a section that is neither -- a typo, or the old
        # `'findings'` default -- passed every check, was counted in
        # "N claim(s) checked", was written to report.json, and then silently
        # never appeared on the page. A conclusion that is validated and
        # invisible is worse than one that is missing.
        section = entry.get('section')
        if section not in ('summary',) + tuple(sorted(series)):
            problems.append(
                '{0}: section {1!r} is neither `summary` nor a series the '
                'review holds, so the claim would be checked and then never '
                'rendered'.format(where, section))
            continue
        if resolved:
            checked.append({'id': name, 'section': section,
                            'text': text, 'cites': resolved})
    return checked


def values_agree(stated, found):
    '''Equality on the review's own terms.

    Never a tolerance. The review has already rounded these, and a report that
    accepted "close enough" would be deciding how much a published number may
    differ from the one it cites -- which is exactly the judgement this file
    is built not to make.
    '''
    if isinstance(stated, bool) or isinstance(found, bool):
        return stated is found
    if isinstance(stated, (int, float)) and isinstance(found, (int, float)):
        return float(stated) == float(found)
    return stated == found


def withheld_reason(block, field, fallback):
    '''Why a figure is absent, in the words the review used.

    `summary.py` already distinguishes five reasons -- nothing was observed, a
    pass reported the never-sampled sentinel, a non-numeric value, a mean that
    is not positive, and fewer than two observations -- and writes them per
    statistic. Deriving a reason here from `n` instead gets all but the last
    one wrong, and gets the sentinel wrong in the direction that matters:
    `min free mem (GB)` unsampled at n=3 is exactly what that sentinel exists
    for, and "a dispersion needs at least two observations" said of it is a
    false explanation of a real absence.
    '''
    reason = (block.get('withheld') or {}).get(field)
    return reason or fallback


def describe_figure(block, field_name, name, missing):
    '''One published figure of one cell: its median, its dispersion where it
    has one, and the review's own reason where it does not.

    `withheld` and `dispersion_withheld` are separate keys, because they are
    different statements and the report publishes an inventory of the first.
    Conflated, 132 of the first build's 207 "not published" notes were about
    figures that *are* published and merely have no dispersion, which drowns
    the section the plan asks for in notes about a withholding the report does
    not make.
    '''
    if not isinstance(block, dict):
        return {field_name: name, 'median': None, 'withheld': missing}
    entry = {field_name: name, 'median': block.get('median'),
             'n': block.get('n'), 'min': block.get('min'),
             'max': block.get('max'), 'values': block.get('values'),
             'stdev': None, 'cv_percent': None}
    if entry['median'] is None:
        entry['withheld'] = withheld_reason(block, 'median', missing)
        return entry
    if block.get('n', 0) < 2:
        # Carried through rather than printed. `summary.py` withholds a
        # dispersion over one observation; a report that printed the withheld
        # value anyway is the one place that rule could be undone.
        entry['dispersion_withheld'] = withheld_reason(
            block, 'stdev', 'a dispersion needs at least two observations; '
            'this cell has {0}'.format(block.get('n')))
    else:
        entry['stdev'] = block.get('stdev')
        entry['cv_percent'] = block.get('cv_percent')
        if entry['stdev'] is None:
            entry['dispersion_withheld'] = withheld_reason(
                block, 'stdev', 'no stdev was published')
    return entry


def describe_metric(cell, metric):
    block = (cell.get('metrics') or {}).get(metric)
    return describe_figure(block, 'metric', metric,
                           'the passes published no {0}'.format(metric))


def describe_interval(cell, interval):
    block = (cell.get('intervals') or {}).get(interval)
    # Withheld, never zero. A daemon with no gauge publishes nothing, and a
    # missing interval printed as 0 is a daemon that answered instantly.
    entry = describe_figure(block, 'interval', interval,
                            'this cell published no {0}'.format(interval))
    witness = WITNESSED_INTERVALS.get(interval)
    if witness and entry.get('median') is not None:
        crossed = (cell.get('intervals') or {}).get(witness) or {}
        if crossed.get('median') == 0:
            # The span is real and nothing crossed it, so it is not a duration
            # of anything. Withheld with the witness named, rather than
            # published as a confident zero.
            entry['median'] = None
            entry['withheld'] = (
                'nothing crossed this span: {0} is 0, so it is not a send '
                'time'.format(witness))
    return entry


def section_intervals(document):
    '''The intervals this series publishes: the common ones, plus any optional
    one some cell of it actually measured.'''
    published = list(PUBLISHED_INTERVALS)
    for interval, label in OPTIONAL_INTERVALS:
        for cell in document.get('cells') or []:
            block = (cell.get('intervals') or {}).get(interval)
            if isinstance(block, dict) and block.get('median') is not None:
                published.append((interval, label))
                break
    return tuple(published)


def build_section(document):
    '''One series as a section of the report.'''
    intervals = section_intervals(document)
    cells = []
    for cell in document.get('cells') or []:
        description = cell.get('description')
        summary_cell = summary_cell_of(document, description) or {}
        cells.append({
            'description': description,
            'ordinal': cell.get('ordinal'),
            'metrics': [describe_metric(summary_cell, metric)
                        for metric, _label in PUBLISHED_METRICS],
            'intervals': [describe_interval(cell, interval)
                          for interval, _label in intervals],
            'passes': cell.get('passes'),
            'expansion': cell.get('expansion'),
            'limiting_component': cell.get('limiting_component'),
            'limiting_reason': cell.get('limiting_reason'),
            'order_relation': cell.get('order_relation'),
        })
    return {
        'series': document.get('series'),
        'interval_labels': [{'interval': interval, 'label': label}
                            for interval, label in intervals],
        'workload': document.get('workload'),
        'scope': document.get('scope'),
        'decision_metric': document.get('decision_metric'),
        'metric_resolution': document.get('metric_resolution'),
        'variance_rule': (document.get('summary') or {}).get('variance_rule'),
        'passes': [{'repetition': one['repetition'], 'block': one['block'],
                    'test': one['test'], 'seed': one['seed'],
                    'order': one['order'], 'rows': one['rows']}
                   for one in document.get('passes') or []],
        'cells': cells,
        'source': document['_path'],
    }


def build_chart(section):
    '''One chart per section: the decision metric, median per cell.

    The labels are the cells' full descriptions -- every axis of the workload,
    not the daemon name -- because the plan asks for "useful graphs with full
    workload labels" and a bar chart of five daemons with no workload on it is
    the shape every one of this project's own earlier graphs had. The values
    and the labels are built from one list, so they cannot come apart in
    length, which is the failure `create_graph()` has by construction.
    '''
    bars = []
    for cell in section['cells']:
        published = [entry for entry in cell['metrics']
                     if entry['metric'] == section['decision_metric']]
        if not published or published[0].get('median') is None:
            continue
        entry = published[0]
        bars.append({'label': cell['description'],
                     'value': entry['median'],
                     'low': entry.get('min'),
                     'high': entry.get('max'),
                     'n': entry.get('n')})
    return {'title': '{0} -- median {1}'.format(
        section['workload'], section['decision_metric']),
        'metric': section['decision_metric'], 'bars': bars}


def render_chart(chart):
    '''An inline SVG bar chart, with the range drawn as a whisker.

    Inline and hand-drawn rather than a library: the page has to open from a
    file with nothing fetched, and a median printed without its range beside
    it is the chart that made three of this campaign's comparisons look
    settled when they were not.
    '''
    bars = chart['bars']
    if not bars:
        return '<p class="withheld">No cell of this series published a '\
               'median, so there is no chart.</p>'
    row_height = 34
    left = 430
    width = 900
    plot = width - left - 70
    height = row_height * len(bars) + 24
    top = max([bar['high'] if bar['high'] is not None else bar['value']
               for bar in bars] + [1])
    parts = ['<svg class="chart" viewBox="0 0 {0} {1}" role="img" '
             'aria-label="{2}">'.format(width, height,
                                        html.escape(chart['title']))]
    for index, bar in enumerate(bars):
        y = 12 + index * row_height
        length = max(1.0, plot * (float(bar['value']) / float(top)))
        parts.append(
            '<text x="0" y="{0}" class="bar-label">{1}</text>'.format(
                y + 15, html.escape(str(bar['label']))))
        parts.append(
            '<rect x="{0}" y="{1}" width="{2:.1f}" height="16" '
            'class="bar"/>'.format(left, y + 4, length))
        if bar['low'] is not None and bar['high'] is not None \
                and bar['high'] != bar['low']:
            low = left + plot * (float(bar['low']) / float(top))
            high = left + plot * (float(bar['high']) / float(top))
            parts.append(
                '<line x1="{0:.1f}" y1="{1}" x2="{2:.1f}" y2="{1}" '
                'class="whisker"/>'.format(low, y + 12, high))
            parts.append('<line x1="{0:.1f}" y1="{1}" x2="{0:.1f}" y2="{2}" '
                         'class="whisker"/>'.format(low, y + 6, y + 18))
            parts.append('<line x1="{0:.1f}" y1="{1}" x2="{0:.1f}" y2="{2}" '
                         'class="whisker"/>'.format(high, y + 6, y + 18))
        label = '{0}'.format(bar['value'])
        if bar['n']:
            label += ' (n={0})'.format(bar['n'])
        parts.append('<text x="{0:.1f}" y="{1}" class="bar-value">{2}</text>'
                     .format(left + length + 6, y + 17, html.escape(label)))
    parts.append('</svg>')
    return ''.join(parts)


def number(value):
    if value is None:
        return '<span class="withheld">withheld</span>'
    if isinstance(value, float):
        return html.escape('{0:g}'.format(value))
    return html.escape(str(value))


def render_html(report):
    out = ['<title>{0}</title>'.format(html.escape(report['title'])),
           '<style>', STYLE, '</style>',
           '<h1>{0}</h1>'.format(html.escape(report['title'])),
           '<p class="meta">Run {0} &middot; rendered {1} &middot; bgperf2 '
           '{2}</p>'.format(html.escape(report['run_id']),
                            html.escape(report['generated_utc']),
                            html.escape(str(report['revision'])))]

    out.append('<h2>What the campaign found</h2>')
    for claim in report['claims']:
        if claim['section'] != 'summary':
            continue
        out.append(render_claim(claim))

    out.append('<h2>How to read this</h2><ul>')
    out.append('<li>Every number here is read from the variance review, which '
               'read it from the block that measured it. Nothing on this page '
               'is computed here.</li>')
    out.append('<li>A withheld figure is marked <span class="withheld">'
               'withheld</span> and says why. Nothing absent is printed as a '
               'zero.</li>')
    out.append('<li>{0} is not published: it is the legacy field whose '
               'reading this campaign replaced, and the decomposition below '
               'is what stands in its place.</li>'.format(
                   html.escape(LEGACY_METRIC)))
    out.append('<li>Rows measured here may not be read against '
               '<code>benchmarks/baseline/baseline-benchmark.csv</code>, '
               'which was produced on a different CPU.</li></ul>')

    for section in report['sections']:
        out.append('<h2>{0}</h2>'.format(html.escape(section['series'])))
        out.append('<p class="workload">{0}</p>'.format(
            html.escape(section['workload'])))
        out.append('<p class="meta">{0} pass(es): {1}. Decision metric {2}, '
                   'resolution {3}. {4}.</p>'.format(
                       len(section['passes']),
                       html.escape(', '.join(
                           '{0} in {1}'.format(one['repetition'], one['block'])
                           for one in section['passes'])),
                       html.escape(str(section['decision_metric'])),
                       number(section['metric_resolution']),
                       html.escape(str(section['variance_rule']))))
        out.append(render_chart(section['chart']))
        out.append(render_metric_table(section))
        out.append(render_interval_table(section))
        for claim in report['claims']:
            if claim['section'] == section['series']:
                out.append(render_claim(claim))

    out.append('<h2>Where these rows were measured</h2>')
    out.append(render_blocks(report['blocks']))

    out.append('<h2>What is not published, and why</h2><ul>')
    for entry in report['withheld']:
        out.append('<li>{0}</li>'.format(html.escape(entry)))
    out.append('</ul>')
    return '\n'.join(out)


def render_claim(claim):
    cites = ' '.join(
        '<li><code>{0}</code> = {1}</li>'.format(
            html.escape(one['source']), number(one['value']))
        for one in claim['cites'])
    return ('<div class="claim"><p>{0}</p><details><summary>the figures this '
            'rests on</summary><ul>{1}</ul></details></div>'.format(
                html.escape(claim['text']), cites))


def render_metric_table(section):
    head = ''.join('<th>{0}<br><span class="sub">{1}</span></th>'.format(
        html.escape(metric), html.escape(label))
        for metric, label in PUBLISHED_METRICS)
    rows = []
    for cell in section['cells']:
        cells_html = []
        for entry in cell['metrics']:
            if entry.get('median') is None:
                cells_html.append('<td><span class="withheld">withheld</span>'
                                  '<br><span class="sub">{0}</span></td>'
                                  .format(html.escape(str(entry.get(
                                      'withheld', '')))))
                continue
            spread = ''
            if entry.get('stdev') is None:
                # `dispersion_withheld`, not `withheld`: this figure *is*
                # published and it is only the spread that is missing. Reading
                # the other key here printed an empty reason under a published
                # median, because a published figure has no `withheld`.
                spread = '<br><span class="sub withheld">{0}</span>'.format(
                    html.escape(str(entry.get('dispersion_withheld')
                                    or 'no dispersion was published')))
            else:
                spread = ('<br><span class="sub">{0}&ndash;{1}, '
                          'CV {2}%</span>').format(
                    number(entry.get('min')), number(entry.get('max')),
                    number(entry.get('cv_percent')))
            cells_html.append('<td>{0}<span class="sub"> (n={1})</span>{2}</td>'
                              .format(number(entry['median']),
                                      number(entry.get('n')), spread))
        rows.append('<tr><th class="cell">{0}</th>{1}</tr>'.format(
            html.escape(str(cell['description'])), ''.join(cells_html)))
    return ('<div class="scroll"><table><thead><tr><th>cell</th>{0}</tr>'
            '</thead><tbody>{1}</tbody></table></div>'.format(
                head, ''.join(rows)))


def render_interval_table(section):
    head = ''.join('<th>{0}<br><span class="sub">{1}</span></th>'.format(
        html.escape(entry['interval']), html.escape(entry['label']))
        for entry in section['interval_labels'])
    rows = []
    for cell in section['cells']:
        cells_html = []
        for entry in cell['intervals']:
            if entry.get('median') is None:
                cells_html.append('<td><span class="withheld">withheld</span>'
                                  '</td>')
                continue
            cells_html.append('<td>{0}</td>'.format(number(entry['median'])))
        rows.append('<tr><th class="cell">{0}</th>{1}</tr>'.format(
            html.escape(str(cell['description'])), ''.join(cells_html)))
    return ('<h3>Timing decomposition, medians</h3>'
            '<p class="meta">In place of {0}. A blank is a withheld figure, '
            'never a zero.</p>'
            '<div class="scroll"><table><thead><tr><th>cell</th>{1}</tr>'
            '</thead><tbody>{2}</tbody></table></div>'.format(
                html.escape(LEGACY_METRIC), head, ''.join(rows)))


def render_blocks(blocks):
    if not blocks:
        return '<p class="withheld">The review published no block '\
               'provenance.</p>'
    rows = []
    for key in sorted(blocks.get('blocks') or {}):
        entry = blocks['blocks'][key]
        host = entry.get('host') or {}
        instance = host.get('instance') or {}
        rows.append(
            '<tr><th class="cell">{0}</th><td>{1}</td><td>{2}</td>'
            '<td>{3}</td><td>{4}</td></tr>'.format(
                html.escape(key),
                'accepted' if entry.get('accepted') else 'not accepted',
                html.escape(str(instance.get('id') or 'not recorded')),
                html.escape(str(host.get('cpu_model') or 'not recorded')),
                html.escape(str(entry.get('revision') or 'not recorded'))))
    return ('<div class="scroll"><table><thead><tr><th>block</th>'
            '<th>state</th><th>instance</th><th>CPU</th><th>revision</th>'
            '</tr></thead><tbody>{0}</tbody></table></div>'.format(
                ''.join(rows)))


STYLE = '''
:root { color-scheme: light dark; --ink: #16181d; --paper: #fbfbf9;
        --rule: #d8d6cf; --dim: #5d6068; --bar: #4a6fa5; --warn: #8a5a00; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e8e8e4; --paper: #16181d; --rule: #343740; --dim: #9aa0aa;
          --bar: #7fa3d8; --warn: #d0a24c; }
}
body { margin: 0 auto; padding: 24px 16px 64px; max-width: 1100px;
       background: var(--paper); color: var(--ink);
       font: 14px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.15rem; margin: 32px 0 6px; border-bottom: 1px solid
     var(--rule); padding-bottom: 4px; }
h3 { font-size: 1rem; margin: 22px 0 4px; }
.meta, .sub { color: var(--dim); font-size: 0.85em; }
.workload { font-weight: 600; margin: 2px 0 8px; }
.withheld { color: var(--warn); }
.claim { border-left: 3px solid var(--bar); padding: 2px 0 2px 12px;
         margin: 12px 0; }
.claim p { margin: 0 0 4px; }
details summary { cursor: pointer; color: var(--dim); font-size: 0.85em; }
code { font-size: 0.85em; word-break: break-all; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 4px;
        font-size: 0.9em; }
th, td { border: 1px solid var(--rule); padding: 5px 7px; text-align: left;
         vertical-align: top; }
th.cell { font-weight: 500; white-space: nowrap; }
.chart { width: 100%; height: auto; margin: 10px 0; }
.bar { fill: var(--bar); }
.whisker { stroke: var(--ink); stroke-width: 1.5; }
.bar-label { font-size: 12px; fill: var(--ink); }
.bar-value { font-size: 12px; fill: var(--dim); }
img { max-width: 100%; }
'''


def reason_text(reason):
    '''A review reason as prose, whatever shape it arrived in.

    `agreement()` returns *all* the distinct values when the passes of a cell
    disagree, so a reason is sometimes a list -- and `str()` of that publishes
    a Python list repr, brackets and quotes and all, in the middle of a
    sentence a reader is meant to take seriously. The disagreement is worth
    saying out loud rather than flattening, so it is said.
    '''
    if isinstance(reason, (list, tuple)):
        parts = [str(one) for one in reason if str(one).strip()]
        if not parts:
            return ''
        if len(parts) == 1:
            return parts[0]
        return 'the passes did not agree: {0}'.format('; '.join(parts))
    return str(reason)


def collect_withheld(sections):
    '''Everything the report declined to publish, said once each.

    Gathered rather than scattered through the tables: "what can and cannot be
    attributed to the target" is a section the plan asks for by name, and a
    reader who wants to know what is missing should not have to find every
    blank cell to learn it.
    '''
    notes = set()
    notes.add('{0} is not published anywhere in this report: it is the legacy '
              'field whose reading this campaign replaced.'.format(
                  LEGACY_METRIC))
    for section in sections:
        for cell in section['cells']:
            for entry in cell['metrics'] + cell['intervals']:
                if entry.get('withheld'):
                    notes.add('{0}: {1} -- {2}'.format(
                        cell['description'],
                        entry.get('metric') or entry.get('interval'),
                        entry['withheld']))
            if cell.get('limiting_component') in (None, 'unresolved',
                                                  'inconclusive'):
                notes.add('{0}: no limiting component is named ({1}){2}'.format(
                    cell['description'], cell.get('limiting_component'),
                    ' -- {0}'.format(reason_text(cell['limiting_reason']))
                    if cell.get('limiting_reason') else ''))
            relation = cell.get('order_relation')
            if relation not in ORDER_RELATIONS:
                # An order relation the review would not read is a thing this
                # report does not say, so it belongs here. It used to be a
                # bare `continue` as the last statement of the loop -- dead
                # code wearing the shape of an intention -- and the first
                # attempt at implementing it tested for `'withheld'`, which
                # this field never holds: the withheld cases are sentences
                # ("order withheld: the passes ran matrices of different
                # sizes", "too few observations"), so an allowlist of the four
                # readings that *are* a relation is the only way round that
                # does not have to guess at the wording.
                notes.add('{0}: no order relation is published -- {1}'.format(
                    cell['description'], reason_text(relation)
                    if relation else 'the review published none'))
    return sorted(notes)


def build(review_dir, claims_path, run_id, revision, problems):
    series, blocks = load_review(review_dir, problems)
    if problems:
        return None
    try:
        claims = read_json(claims_path)
    except (ValueError, OSError) as failure:
        problems.append('{0} is not readable JSON: {1}'.format(
            claims_path, failure))
        return None
    checked = check_claims(claims, series, problems)
    sections = [build_section(series[name]) for name in sorted(series)]
    for section in sections:
        section['chart'] = build_chart(section)
        if len(section['chart']['bars']) > len(section['cells']):
            # Cannot happen from `build_chart`, which builds both from one
            # list -- which is the point of asserting it here rather than
            # trusting it. `create_graph()` pairs labels and heights
            # positionally and has produced bars under the wrong labels.
            problems.append('{0}: the chart has more bars than the series has '
                            'cells'.format(section['series']))
    cited = {one['series'] for claim in checked for one in claim['cites']}
    for section in sections:
        if section['series'] not in cited:
            # A note, not a refusal: a series nobody claimed anything about is
            # still evidence, and the tables carry it. What it must not do is
            # pass unremarked, because a section with no claim is usually one
            # somebody forgot rather than one with nothing to say.
            problems.append('note: no claim cites the {0} series; its tables '
                            'are published and nothing is concluded from '
                            'them'.format(section['series']))
    if [entry for entry in problems if not entry.startswith('note: ')]:
        return None
    report = {
        'schema': REPORT_SCHEMA,
        'title': claims.get('title') or '2026 64 GB timing validation',
        'run_id': run_id,
        'revision': revision,
        'generated_utc': datetime.datetime.now(
            datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'review': os.path.basename(review_dir.rstrip('/')),
        'claims': checked,
        'sections': sections,
        'blocks': blocks,
    }
    report['withheld'] = collect_withheld(sections)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True,
                        help='the variance review directory to render')
    parser.add_argument('--claims', required=True,
                        help='the claims document: the report\'s prose, with '
                             'every claim citing the figures it rests on')
    parser.add_argument('--out', required=True,
                        help='where report.json and report.html are written')
    parser.add_argument('--run-id', default='2026-timing-validation')
    parser.add_argument('--revision', default=None,
                        help='the bgperf2 revision this was rendered from')
    args = parser.parse_args(argv)

    problems = []
    report = build(args.review, args.claims, args.run_id, args.revision,
                   problems)
    for line in problems:
        print(line if line.startswith('note: ') else 'error: {0}'.format(line),
              file=sys.stderr)
    if report is None:
        print('{0} problem(s); the report was not written'.format(
            len([p for p in problems if not p.startswith('note: ')])),
            file=sys.stderr)
        return 1
    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, 'report.json')
    with open(json_path, 'w') as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write('\n')
    html_path = os.path.join(args.out, 'report.html')
    with open(html_path, 'w') as handle:
        handle.write('<!doctype html>\n<html lang="en">\n<head>\n'
                     '<meta charset="utf-8">\n'
                     '<meta name="viewport" content="width=device-width, '
                     'initial-scale=1">\n')
        handle.write(render_html(report))
        handle.write('\n</html>\n')
    print('{0} claim(s) checked against {1} series; wrote {2} and {3}'.format(
        len(report['claims']), len(report['sections']), json_path, html_path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
