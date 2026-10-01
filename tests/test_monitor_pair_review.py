'''`scripts/monitor_pair_review.py`: pairing a cell's two instruments and
the rules that say the sink passed. No Docker.'''
import importlib.util

import pytest

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    'monitor_pair_review', REPO_ROOT / 'scripts' / 'monitor_pair_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def doc(monitor='gobgp', count=500000, status='converged', sink_log=None,
        receivers=None):
    events = [
        {'event': 'monitor_first_prefix', 'phase': 'convergence',
         'monotonic_s': 1.0, 'counters': {'accepted_prefixes': 10}},
        {'event': 'convergence_confirmed', 'phase': 'assurance',
         'monotonic_s': 9.0, 'counters': {'accepted_prefixes': count}},
    ]
    d = {'status': status, 'events': events, 'run': {'monitor': monitor},
         'measurements': {'convergence_s': 3.0}}
    if monitor == 'sink':
        d['instrument'] = {'sink_log': sink_log if sink_log is not None else {
            'processes': 1, 'sessions_lost': 0, 'malformed_lines': 0,
            'refused_messages': 0, 'clock_offset_ns': 1500,
            'max_line_gap_ns': 10**9}}
    if receivers is not None:
        d['export'] = {'sessions': {n: {'accepted_prefixes': c}
                                    for n, c in receivers.items()}}
    return d


def test_the_sink_stem_pairs_with_the_unmarked_one():
    assert review.pair_key('/r/bird_bird_50000_10_mon-sink.events.json') == \
        ('bird_bird_50000_10', 'sink')
    assert review.pair_key('/r/bird_bird_50000_10.events.json') == \
        ('bird_bird_50000_10', None)


def test_a_matching_pair_passes():
    assert review.compare(doc(), doc('sink')) == (True, [])


def test_a_different_final_count_fails():
    passed, reasons = review.compare(doc(), doc('sink', count=499999))
    assert not passed and 'final count' in reasons[0]


def failed(monitor, final):
    d = doc(monitor, status='failed')
    d['events'] = d['events'][:1]
    d['target_table'] = {'samples': [{'monitor_accepted': 5},
                                     {'monitor_accepted': final}]}
    return d


def test_runs_that_end_differently_fail():
    passed, reasons = review.compare(failed('gobgp', 500000), doc('sink'))
    assert not passed and 'status gobgp failed vs sink converged' in reasons


def test_runs_that_both_failed_on_one_count_pass():
    assert review.compare(failed('gobgp', 950000), failed('sink', 950000))[0]
    passed, reasons = review.compare(failed('gobgp', 950000),
                                     failed('sink', 949000))
    assert not passed and 'final count' in reasons[0]


def test_a_failed_run_is_never_read_off_its_first_event():
    '''`monitor_first_prefix` is from the first second of the run.'''
    d = doc(status='failed')
    d['events'] = d['events'][:1]
    assert review.final_accepted(d) is None
    assert review.final_accepted(failed('sink', 7)) == 7


@pytest.mark.parametrize('field,value,needle', [
    ('sessions_lost', 1, 'session(s) lost'),
    ('processes', 2, 'sink processes'),
    ('malformed_lines', 3, 'malformed'),
    ('refused_messages', 1, 'refused'),
    ('clock_offset_ns', 5 * 10**6, 'clock offset'),
    ('clock_offset_ns', None, 'no clock offset'),
])
def test_what_the_sink_log_says_can_fail_a_pair(field, value, needle):
    log = dict(doc('sink')['instrument']['sink_log'], **{field: value})
    passed, reasons = review.compare(doc(), doc('sink', sink_log=log))
    assert not passed and any(needle in r for r in reasons)


def test_a_sink_run_without_its_log_section_fails():
    s = doc('sink')
    del s['instrument']
    assert not review.compare(doc(), s)[0]


def test_receivers_must_agree_too():
    passed, reasons = review.compare(doc(receivers={'r0': 5, 'r1': 5}),
                                     doc('sink', receivers={'r0': 5, 'r1': 4}))
    assert not passed and 'receivers' in reasons[0]


def test_an_unpaired_cell_fails_and_a_misnamed_one_is_refused(tmp_path):
    import json
    (tmp_path / 'a.events.json').write_text(json.dumps(doc()))
    assert review.main([str(tmp_path)]) == 1
    (tmp_path / 'a_mon-sink.events.json').write_text(json.dumps(doc('sink')))
    assert review.main([str(tmp_path)]) == 0
    (tmp_path / 'b.events.json').write_text(json.dumps(doc('sink')))
    with pytest.raises(SystemExit):
        review.main([str(tmp_path)])


def test_nothing_to_compare(tmp_path):
    assert review.main([str(tmp_path)]) == 2
