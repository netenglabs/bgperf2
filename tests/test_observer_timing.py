"""Count-crossing bounds are conservative, independent of nominal write cadence."""
import hashlib
import json

import pytest

import observer_timing
import recipes
from recipe_assertions import default_assertions
from recipe_comparison import make_comparison_plan
from recipe_targets import supplied_target
from test_recipe_comparison_report import package, ROOT


def log_text(step_ns=20_000_000):
    lines = ['V 1 1 SIMULATED', 'B 2 100', 'S 3 established outbound 1', 'C 5 0 0 0']
    lines += [f'C {5 + i * step_ns} {i} {i} 0' for i in range(1, 101)]
    # Teardown is routinely retained after collection; it is outside delivery.
    lines += [f'C {6 + 100 * step_ns} 0 0 0', f'S {7 + 100 * step_ns} down outbound 1 EOF']
    return '\n'.join(lines) + '\n'


def test_bounds_and_shutdown_scope():
    observed = observer_timing.crossing_window(log_text(), 100)
    assert observed['span_seconds'] == pytest.approx(1.6)
    assert observed['lower_seconds'] == pytest.approx(1.58)
    assert observed['upper_seconds'] == pytest.approx(1.62)
    assert observed['bracket_width_seconds'] == pytest.approx(0.04)
    assert observed['interior_increasing_records'] == 79
    assert observer_timing.resolution_gate(observed)['outcome'] == 'passed'


def test_coalesced_crossing_uses_observed_gap_not_nominal_ten_ms():
    text = ('V 1 1 SIMULATED\nB 2 100\nS 3 established outbound 1\n'
            'C 5 0 0 0\nC 2000000000 50 1 0\nC 3000000000 100 2 0\n')
    observed = observer_timing.crossing_window(text, 100)
    assert observed['lower_seconds'] == 0
    assert observed['upper_seconds'] == pytest.approx(3)
    assert observer_timing.resolution_gate(observed)['outcome'] == 'blocked'


@pytest.mark.parametrize('replacement', [
    'C 400000005 2 20 0',  # count resets
    'C 400000005 20 0 0',  # UPDATE counter resets
    'C 400000005 -20 20 0',
    'C 400000005 101 20 0',
    'C 4 20 20 0',  # timestamp inversion
    'C 99999999999999999999999999999999 20 20 0',
    'C 400000005 twenty 20 0',
    'H 400000005 20 20 0',  # disagrees with preceding C
    'E 400000005 20 20',
    'V 400000005 1 restarted',
    'S 400000005 down outbound 1',
    'S 400000005 established outbound 2',
    'M 400000005 attribute-discard',
    'X 400000005 unknown',
])
def test_invalid_or_interrupted_delivery_is_withheld(replacement):
    with pytest.raises(recipes.ContractError):
        observer_timing.crossing_window(log_text().replace('C 400000005 20 20 0', replacement), 100)


def test_truncated_or_missing_delivery_is_withheld():
    with pytest.raises(recipes.ContractError, match='Incomplete'):
        observer_timing.crossing_window(log_text().split('C 400000005')[0] + 'C 400', 100)
    with pytest.raises(recipes.ContractError, match='No exact'):
        observer_timing.crossing_window(log_text().split('C 400000005')[0], 100)
    with pytest.raises(recipes.ContractError, match='preceding'):
        observer_timing.crossing_window('V 1 1 SIMULATED\nB 2 100\nS 3 established outbound 1\nC 4 100 1 0\n', 100)


def test_a_long_wall_clock_does_not_make_fast_delivery_resolved():
    observed = observer_timing.crossing_window(log_text(step_ns=1_000_000), 100)
    assert observer_timing.resolution_gate(observed)['outcome'] == 'blocked'


@pytest.fixture
def result_package(tmp_path):
    recipe = recipes.read_document(ROOT / 'examples/recipes/synthetic-ipv4.recipe.json')
    target = supplied_target(recipe, 'sha256:' + '4' * 64)
    plan = make_comparison_plan(recipe, baseline_target=target, candidate_target=target, repetitions=1)
    path = package(tmp_path / 'attempt', plan, plan['sequence'][0])
    additions = {
        'work/owned/monitor/sink.log': log_text(),
        'work/artifacts/bird_mon-sink.events.json': json.dumps({'instrument': {'sink_log': {
            'processes': 1, 'sessions_established': 1, 'sessions_lost': 0,
            'malformed_lines': 0, 'refused_messages': 0, 'kept_messages': 0, 'accepted': 100}}})}
    result = json.loads(path.read_text())
    for relative, data in additions.items():
        f = path.parent / relative
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(data)
        result['artifacts'].append({'path': relative, 'availability': 'present', 'reason': None,
                                   'kind': 'log' if relative.endswith('.log') else 'events',
                                   'sha256': hashlib.sha256(f.read_bytes()).hexdigest()})
    path.write_text(json.dumps(result))
    spec = default_assertions(recipe)
    spec['assertions'] = spec['assertions'][:4]
    assertions = tmp_path / 'assertions.json'
    assertions.write_text(json.dumps(spec))
    return path, assertions


def test_verified_package_and_separate_supplement(result_package, tmp_path):
    path, assertions = result_package
    before = path.read_bytes()
    report = observer_timing.review_result(path, assertions)
    assert report['resolution_gate']['outcome'] == 'passed'
    assert report['performance'] == 'not_assessed' and report['regression_policy'] == 'disabled'
    output = tmp_path / 'supplement.json'
    assert observer_timing.main(['--result', str(path), '--assertions', str(assertions),
                                 '--output', str(output)]) == 0
    assert json.loads(output.read_text()) == report
    assert path.read_bytes() == before
    assert observer_timing.main(['--result', str(path), '--assertions', str(assertions),
                                 '--output', str(output), '--verify']) == 0
    altered = json.loads(output.read_text())
    altered['window']['span_seconds'] = 100
    output.write_text(json.dumps(altered))
    with pytest.raises(SystemExit):
        observer_timing.main(['--result', str(path), '--assertions', str(assertions),
                              '--output', str(output), '--verify'])
    with pytest.raises(SystemExit):
        observer_timing.main(['--result', str(path), '--assertions', str(assertions), '--output', str(output)])


def test_modified_package_refused(result_package):
    path, assertions = result_package
    (path.parent / 'work/owned/monitor/sink.log').write_text(log_text(step_ns=10))
    with pytest.raises(recipes.ContractError, match='SHA-256 mismatch'):
        observer_timing.review_result(path, assertions)


def test_output_must_not_modify_original_package(result_package, tmp_path):
    path, assertions = result_package
    alias = tmp_path / 'alias'
    alias.symlink_to(path.parent, target_is_directory=True)
    for output in (path.parent / 'extra.json', alias / 'extra.json'):
        with pytest.raises(SystemExit):
            observer_timing.main(['--result', str(path), '--assertions', str(assertions), '--output', str(output)])


def test_unhealthy_instrument_refused_even_if_hashed(result_package):
    path, assertions = result_package
    f = path.parent / 'work/artifacts/bird_mon-sink.events.json'
    data = json.loads(f.read_text())
    data['instrument']['sink_log']['sessions_lost'] = 1
    f.write_text(json.dumps(data))
    result = json.loads(path.read_text())
    for item in result['artifacts']:
        if item['path'] == 'work/artifacts/bird_mon-sink.events.json':
            item['sha256'] = hashlib.sha256(f.read_bytes()).hexdigest()
    path.write_text(json.dumps(result))
    with pytest.raises(recipes.ContractError, match='instrument'):
        observer_timing.review_result(path, assertions)


def test_manifest_change_during_assertions_is_refused(result_package, monkeypatch):
    path, assertions = result_package
    evaluate = observer_timing.evaluate_assertions

    def change(*args):
        observed = evaluate(*args)
        path.write_text(path.read_text() + '\n')
        return observed

    monkeypatch.setattr(observer_timing, 'evaluate_assertions', change)
    with pytest.raises(recipes.ContractError, match='manifest changed'):
        observer_timing.review_result(path, assertions)


def test_output_directory_swap_cannot_write_into_package(result_package, tmp_path, monkeypatch):
    path, assertions = result_package
    destination = tmp_path / 'destination'
    destination.mkdir()
    relocated = tmp_path / 'relocated'
    review = observer_timing.review_result

    def swap(*args):
        report = review(*args)
        destination.rename(relocated)
        destination.symlink_to(path.parent, target_is_directory=True)
        return report

    monkeypatch.setattr(observer_timing, 'review_result', swap)
    assert observer_timing.main(['--result', str(path), '--assertions', str(assertions),
                                 '--output', str(destination / 'supplement.json')]) == 0
    assert (relocated / 'supplement.json').is_file()
    assert not (path.parent / 'supplement.json').exists()
