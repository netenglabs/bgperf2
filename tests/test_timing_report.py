'''The report, and the four ways a benchmark report lies.

`build_timing_report.py` renders Block 12 from the variance review and
computes no statistic of its own, so what is worth testing is not arithmetic
-- there is none -- but the refusals: a claim with no figure under it, a claim
whose figure does not match the review, a claim that leans on the legacy
`testers (s)` reading, and a dispersion printed over one observation.

The repository's own claims document and its own review are exercised too
where they exist, because that pair is what actually renders.
'''
import importlib.util
import json
import sys

import pytest

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    'build_timing_report', REPO_ROOT / 'scripts' / 'build_timing_report.py')
builder = importlib.util.module_from_spec(spec)
sys.modules['build_timing_report'] = builder
spec.loader.exec_module(builder)

CLAIMS = (REPO_ROOT / 'results' / '2026' / '2026-timing-validation'
          / 'metadata' / 'block12-claims.json')


def a_series(series='synthetic', description='bird 2.19.2, peers=50',
             median=90.0, values=(90, 90, 90), reload_s=None):
    metrics = {'elapsed (s)': {'median': median, 'n': len(values),
                               'min': min(values), 'max': max(values),
                               'mean': median, 'stdev': 0.0,
                               'cv_percent': 0.0, 'values': list(values)},
               'max cpu %': {'median': 101.0, 'n': len(values), 'min': 101,
                             'max': 101, 'stdev': 0.0, 'cv_percent': 0.0,
                             'values': [101] * len(values)},
               # Present in every real stats row, which is the point: the
               # refusal has to work against a document that carries it.
               'testers (s)': {'median': 42.0, 'n': len(values), 'min': 42,
                               'max': 42, 'stdev': 0.0, 'cv_percent': 0.0,
                               'values': [42] * len(values)}}
    intervals = {'convergence_s': {'median': 80.5, 'n': len(values),
                                   'values': [80.5] * len(values)}}
    if reload_s is not None:
        intervals['reload_s'] = {'median': reload_s, 'n': len(values),
                                 'values': [reload_s] * len(values)}
    document = {
        'schema': builder.REVIEW_SCHEMA,
        'series': series,
        'scope': 'matrix',
        'workload': '50 peers x 100,000 prefixes per peer',
        'decision_metric': 'elapsed (s)',
        'metric_resolution': 1.0,
        'passes': [{'repetition': 1, 'block': 'block2', 'test': 't',
                    'seed': 1, 'order': 'shuffle', 'rows': 1}],
        'cells': [{'description': description, 'ordinal': 0,
                   'intervals': intervals, 'passes': [],
                   'limiting_component': 'unresolved',
                   'limiting_reason': 'nothing crossed the interval',
                   'order_relation': 'withheld', 'expansion': None}],
        'summary': {'variance_rule': 'medians differ by more than the sum of '
                                     'the deviations',
                    'cells': [{'description': description,
                               'metrics': metrics}]},
        '_path': '{0}.json'.format(series),
    }
    return document


def a_claim(**overrides):
    claim = {'id': 'answer', 'section': 'summary',
             'text': 'BIRD 2.19.2 converges this table in 90s.',
             'cites': [{'series': 'synthetic',
                        'cell': 'bird 2.19.2, peers=50',
                        'metric': 'elapsed (s)', 'field': 'median',
                        'value': 90.0}]}
    claim.update(overrides)
    return claim


def check(claims, series=None):
    problems = []
    document = {'schema': builder.CLAIMS_SCHEMA, 'claims': claims}
    checked = builder.check_claims(
        document, series or {'synthetic': a_series()}, problems)
    return checked, problems


class TestWhatItRefuses:
    def test_a_claim_with_no_citation(self):
        _checked, problems = check([a_claim(cites=[])])
        assert any('cites nothing' in line for line in problems)

    def test_a_citation_that_does_not_match_the_review(self):
        """The one that matters, and the one that fired on the first real
        build: an author writing from a rounded table cites 71.936246 where
        the review says 71.906846. Both numbers are named, because that
        usually says which of the two moved."""
        claim = a_claim()
        claim['cites'][0]['value'] = 91.0
        _checked, problems = check([claim])
        assert any('cites' in line and '91.0' in line and '90.0' in line
                   for line in problems)

    def test_a_claim_that_names_the_legacy_field(self):
        claim = a_claim(text='The testers (s) column says 42.')
        _checked, problems = check([claim])
        assert any('exit criterion' in line for line in problems)

    def test_a_citation_of_the_legacy_field(self):
        """Refused even though the figure is really there and really matches:
        it is in every stats row, and the plan's exit criterion is that no
        claim depends on it."""
        claim = a_claim()
        claim['cites'][0].update({'metric': 'testers (s)', 'value': 42.0})
        _checked, problems = check([claim])
        assert any('legacy field' in line for line in problems)

    def test_a_dispersion_over_one_observation_is_not_published(self):
        """`summary.py` withholds it; this is the one place the withholding
        could be undone, by citing the field directly."""
        series = {'synthetic': a_series(values=(90,))}
        claim = a_claim()
        claim['cites'][0].update({'field': 'stdev', 'value': 0.0})
        _checked, problems = check([claim], series)
        assert any('has no stdev' in line for line in problems)

    def test_a_cell_the_review_does_not_hold(self):
        claim = a_claim()
        claim['cites'][0]['cell'] = 'bird 9.9.9, peers=50'
        _checked, problems = check([claim])
        assert any('is not a cell of' in line for line in problems)

    def test_a_series_the_review_does_not_hold(self):
        claim = a_claim()
        claim['cites'][0]['series'] = 'nonesuch'
        _checked, problems = check([claim])
        assert any('which the review does not hold' in line
                   for line in problems)

    def test_two_claims_with_one_id(self):
        _checked, problems = check([a_claim(), a_claim()])
        assert any('two claims share this id' in line for line in problems)

    def test_a_report_with_no_claims(self):
        _checked, problems = check([])
        assert any('table dump' in line for line in problems)


class TestWhatItPublishes:
    def test_a_matching_claim_carries_its_source(self):
        checked, problems = check([a_claim()])
        assert problems == []
        assert checked[0]['cites'][0]['source'] == (
            'synthetic.json#summary.cells[bird 2.19.2, peers=50]'
            '.metrics.elapsed (s).median')

    def test_a_withheld_dispersion_says_why_instead_of_printing_zero(self):
        section = builder.build_section(a_series(values=(90,)))
        elapsed = [entry for entry in section['cells'][0]['metrics']
                   if entry['metric'] == 'elapsed (s)'][0]
        assert elapsed['stdev'] is None
        # `dispersion_withheld`, not `withheld`: the median is published and
        # only the spread is missing, and the report keeps those apart.
        assert 'at least two observations' in elapsed['dispersion_withheld']

    def test_an_interval_a_cell_never_published_is_withheld_not_zero(self):
        section = builder.build_section(a_series())
        missing = [entry for entry in section['cells'][0]['intervals']
                   if entry['interval'] == 'assurance_s'][0]
        assert missing['median'] is None
        assert missing['withheld']

    def test_an_optional_interval_appears_only_where_it_was_measured(self):
        """`reload_s` belongs to one scenario. A column of `withheld` in six
        other series says nothing except that a policy reload is not part of
        an MRT playback, which the workload label already said."""
        without = builder.build_section(a_series())
        assert 'reload_s' not in [entry['interval'] for entry
                                  in without['interval_labels']]
        with_reload = builder.build_section(
            a_series(series='screen-reload', reload_s=11.8))
        assert 'reload_s' in [entry['interval'] for entry
                              in with_reload['interval_labels']]

    def test_the_chart_labels_carry_the_whole_workload(self):
        """A bar chart of daemon names with no workload on it is the shape
        every one of this project's earlier graphs had, and it is how two
        different workloads end up read as one comparison."""
        section = builder.build_section(a_series())
        chart = builder.build_chart(section)
        assert chart['bars'][0]['label'] == 'bird 2.19.2, peers=50'
        assert 'peers' in chart['title'] or 'peers' in chart['bars'][0]['label']

    def test_bars_and_labels_cannot_come_apart(self):
        """`create_graph()` pairs labels and heights positionally and has
        produced bars under the wrong labels; here one list is the source of
        both."""
        section = builder.build_section(a_series())
        chart = builder.build_chart(section)
        assert all(set(bar) >= {'label', 'value'} for bar in chart['bars'])
        assert len(chart['bars']) <= len(section['cells'])

    def test_a_cell_with_no_median_is_left_out_of_the_chart(self):
        document = a_series()
        document['summary']['cells'][0]['metrics']['elapsed (s)'] = {'n': 0}
        section = builder.build_section(document)
        assert builder.build_chart(section)['bars'] == []

    def test_the_withheld_inventory_names_the_legacy_field(self):
        section = builder.build_section(a_series())
        section['chart'] = builder.build_chart(section)
        notes = builder.collect_withheld([section])
        assert any(builder.LEGACY_METRIC in note for note in notes)
        assert any('no limiting component is named' in note for note in notes)


@pytest.mark.skipif(not CLAIMS.is_file(), reason='no claims document')
class TestTheRepositorysOwnClaims:
    def test_the_claims_document_is_readable_and_well_formed(self):
        document = json.loads(CLAIMS.read_text())
        assert document['schema'] == builder.CLAIMS_SCHEMA
        assert document['claims']
        for claim in document['claims']:
            assert claim['id'] and claim['text'] and claim['cites']
            assert builder.LEGACY_METRIC not in claim['text']

    def test_every_claim_cites_a_series_and_a_cell(self):
        document = json.loads(CLAIMS.read_text())
        for claim in document['claims']:
            for citation in claim['cites']:
                assert citation['series'] and citation['cell']
                assert citation.get('metric') or citation.get('interval')
                assert citation.get('metric') != builder.LEGACY_METRIC


class TestTheReviewsOwnWithholding:
    """The report carries the review's reason, never one derived from `n`.

    `summary.py` distinguishes five reasons and writes them per statistic.
    Deriving one here from the observation count gets four of the five wrong,
    and gets the never-sampled sentinel wrong in the direction that matters:
    that case has n=3 and is precisely what the sentinel exists for.
    """

    def a_cell_withholding(self, reason, n=3, field='median'):
        document = a_series()
        block = document['summary']['cells'][0]['metrics']['elapsed (s)']
        block['n'] = n
        block[field] = None
        block['withheld'] = {field: reason}
        return document

    def test_the_reviews_reason_is_published_not_one_derived_from_n(self):
        document = self.a_cell_withholding(
            'a pass reported the never-sampled sentinel in this column')
        section = builder.build_section(document)
        entry = [one for one in section['cells'][0]['metrics']
                 if one['metric'] == 'elapsed (s)'][0]
        assert entry['median'] is None
        assert 'never-sampled sentinel' in entry['withheld']
        assert 'two observations' not in entry['withheld']

    def test_an_unsampled_figure_at_n_three_still_says_why(self):
        """The case that had no `withheld` key at all, so the table printed
        the word `withheld` above an empty reason and the inventory left it
        out entirely."""
        document = self.a_cell_withholding('no observation: every pass of '
                                           'this cell failed or has not run')
        section = builder.build_section(document)
        section['chart'] = builder.build_chart(section)
        notes = builder.collect_withheld([section])
        assert any('no observation' in note for note in notes)
        html = builder.render_metric_table(section)
        assert 'no observation' in html

    def test_a_published_figure_with_no_dispersion_is_not_called_withheld(self):
        """Different statements, different keys. Conflated, 132 of the first
        build's 207 `not published` notes were about figures that are
        published and merely have no spread."""
        section = builder.build_section(a_series(values=(90,)))
        entry = [one for one in section['cells'][0]['metrics']
                 if one['metric'] == 'elapsed (s)'][0]
        assert entry['median'] == 90.0
        assert 'withheld' not in entry
        assert 'two observations' in entry['dispersion_withheld']
        section['chart'] = builder.build_chart(section)
        notes = builder.collect_withheld([section])
        assert not [note for note in notes if 'elapsed (s) --' in note]


class TestASpanNothingCrossed:
    """`injection_s` is a duration of something only if something crossed it.

    A BIRD 2.19 generator's offered count is queue-side and saturates before
    the first poll, so the span comes back 0.0 with nothing having crossed it.
    Published as a bare `0` that is the most confident wrong number on the
    page -- it appeared 34 times in the first real build.
    """

    def a_cell_with_injection(self, injection, crossed):
        document = a_series()
        document['cells'][0]['intervals'].update({
            'injection_s': {'median': injection, 'n': 3,
                            'values': [injection] * 3},
            'offered_in_interval': {'median': crossed, 'n': 3,
                                    'values': [crossed] * 3}})
        return document

    def test_a_span_nothing_crossed_is_withheld_not_zero(self):
        section = builder.build_section(
            self.a_cell_with_injection(0.0, 0))
        entry = [one for one in section['cells'][0]['intervals']
                 if one['interval'] == 'injection_s'][0]
        assert entry['median'] is None
        assert 'nothing crossed this span' in entry['withheld']

    def test_a_span_a_table_crossed_is_published(self):
        section = builder.build_section(
            self.a_cell_with_injection(40.0, 500000))
        entry = [one for one in section['cells'][0]['intervals']
                 if one['interval'] == 'injection_s'][0]
        assert entry['median'] == 40.0
        assert 'withheld' not in entry

    def test_the_witness_is_published_beside_the_interval(self):
        """Without it the span cannot be read at all, which is why the review
        carries it."""
        section = builder.build_section(self.a_cell_with_injection(40.0, 500))
        published = [one['interval'] for one in section['interval_labels']]
        assert 'offered_in_interval' in published
        assert published.index('offered_in_interval') == \
            published.index('injection_s') + 1


class TestTheRefusalsAreNotOptIn:
    def test_a_citation_with_no_value_is_refused(self):
        """Omitting one key made the headline refusal absent: the citation
        resolved, published whatever the review said, and nothing compared it
        to the prose above it."""
        claim = a_claim()
        claim['cites'][0].pop('value')
        _checked, problems = check([claim])
        assert any('without saying what value it rests on' in line
                   for line in problems)

    def test_a_claim_may_not_rest_on_a_figure_the_review_withheld(self):
        document = a_series()
        document['summary']['cells'][0]['metrics']['elapsed (s)']['median'] = None
        claim = a_claim()
        claim['cites'][0]['value'] = None
        _checked, problems = check([claim], {'synthetic': document})
        assert any('which the review withheld' in line for line in problems)

    def test_a_citation_naming_neither_a_metric_nor_an_interval(self):
        claim = a_claim()
        claim['cites'][0].pop('metric')
        _checked, problems = check([claim])
        assert any('neither a metric nor an interval' in line
                   for line in problems)

    def test_a_claim_whose_section_would_never_render_is_refused(self):
        """It passed every check, was counted in `N claim(s) checked`, was
        written to report.json, and then never appeared on the page. A
        conclusion that is validated and invisible is worse than a missing
        one."""
        for section in ('findings', 'nonesuch', None):
            claim = a_claim(section=section) if section else a_claim()
            if section is None:
                claim.pop('section')
            _checked, problems = check([claim])
            assert any('never rendered' in line for line in problems), section

    def test_a_claim_under_the_summary_or_its_own_series_is_accepted(self):
        for section in ('summary', 'synthetic'):
            checked, problems = check([a_claim(section=section)])
            assert problems == [], section
            assert checked[0]['section'] == section


class TestAMalformedReviewIsRefusedNotRaised:
    def test_a_series_document_with_no_series_name(self, tmp_path):
        review = tmp_path / 'review'
        review.mkdir()
        document = a_series()
        document.pop('series')
        document.pop('_path')
        (review / 'one.json').write_text(json.dumps(document))
        problems = []
        builder.load_review(str(review), problems)
        assert any('declares no `series`' in line for line in problems)

    def test_two_documents_declaring_one_series(self, tmp_path):
        review = tmp_path / 'review'
        review.mkdir()
        for name in ('a.json', 'b.json'):
            document = a_series()
            document.pop('_path')
            (review / name).write_text(json.dumps(document))
        problems = []
        builder.load_review(str(review), problems)
        assert any('both declare the series' in line for line in problems)


class TestReasonsThatArriveAsLists:
    def test_disagreeing_passes_are_said_out_loud_not_repr_ed(self):
        """`agreement()` returns every distinct value when the passes of a
        cell disagree, and `str()` of that publishes a Python list repr in the
        middle of a sentence."""
        text = builder.reason_text(['the first reason', 'the second reason'])
        assert '[' not in text and "'" not in text
        assert 'did not agree' in text
        assert 'the first reason' in text and 'the second reason' in text

    def test_one_value_in_a_list_is_just_that_value(self):
        assert builder.reason_text(['only this']) == 'only this'

    def test_a_plain_string_is_unchanged(self):
        assert builder.reason_text('a reason') == 'a reason'


class TestTheOrderRelation:
    def test_a_relation_the_review_would_not_read_is_in_the_inventory(self):
        """The dead `continue` this replaced, and then the first attempt at
        replacing it, which tested for `'withheld'` -- a value this field
        never holds, because its withheld cases are sentences."""
        document = a_series()
        document['cells'][0]['order_relation'] = (
            'order withheld: the passes ran matrices of different sizes')
        section = builder.build_section(document)
        section['chart'] = builder.build_chart(section)
        notes = builder.collect_withheld([section])
        assert any('no order relation is published' in note for note in notes)

    def test_a_real_relation_is_not_reported_as_missing(self):
        for relation in builder.ORDER_RELATIONS:
            document = a_series()
            document['cells'][0]['order_relation'] = relation
            section = builder.build_section(document)
            section['chart'] = builder.build_chart(section)
            notes = builder.collect_withheld([section])
            assert not [note for note in notes
                        if 'no order relation' in note], relation
