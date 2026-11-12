"""Small receive qualification refuses incomplete, foreign and misattributed data."""
import copy
import json
from pathlib import Path
import time

import pytest
import recipe_diagnostics as diagnostics
import recipe_receive as receive
import recipes

CID = 'a' * 64


def fixture():
    recipe = recipes.read_document(Path(__file__).parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json')
    recipe['roles']['target']['adapter'] = 'maghemite'
    recipe['resolved'].update(neighbors=2, prefixes_per_peer=8)
    scenario = {'target': {'as': 64515}, 'testers': [{'neighbors': {
        str(i): {'local-address': f'10.10.0.{i + 3}', 'as': 1003 + i,
                 'paths': [f'100.0.0.{i * 8 + j}/32' for j in range(8)]}
        for i in range(2)}}]}
    expected = receive.expectation(recipe, scenario)
    rib = {prefix: [{'nexthop': peer['address'], 'shutdown': False, 'rib_priority': 20,
                    'bgp': {'peer': {'Ip': peer['address']}, 'origin_as': peer['asn'],
                            'id': 123, 'as_path': [peer['asn']]}}]
           for peer in expected['peers'] for prefix in peer['prefixes']}
    return recipe, expected, rib


def test_exact_identity_binds_every_source_peer():
    _, expected, rib = fixture()
    assert receive.parse_rib(json.dumps(rib).encode(), expected)['exact']
    first = next(iter(rib))
    rib[first][0]['bgp'].update(peer={'Ip': expected['peers'][1]['address']}, as_path=[1004])
    result = receive.parse_rib(json.dumps(rib).encode(), expected)
    assert not result['exact'] and not result['missing'] and not result['unexpected']
    assert result['peer_differences']['10.10.0.3']['missing'] == [first]


@pytest.mark.parametrize('change', ['empty_paths', 'static', 'unknown_peer', 'bad_as', 'bad_prefix', 'duplicate_path'])
def test_invalid_path_snapshots_are_unmeasured(change):
    _, expected, rib = fixture()
    first = next(iter(rib))
    if change == 'empty_paths': rib[first] = []
    if change == 'static': rib[first][0]['bgp'] = None
    if change == 'unknown_peer': rib[first][0]['bgp']['peer'] = {'Ip': '192.0.2.1'}
    if change == 'bad_as': rib[first][0]['bgp']['as_path'] = [True]
    if change == 'bad_prefix': rib['100.0.0.1/24'] = rib.pop(first)
    if change == 'duplicate_path': rib[first].append(copy.deepcopy(rib[first][0]))
    with pytest.raises(ValueError): receive.parse_rib(json.dumps(rib).encode(), expected)


@pytest.mark.parametrize('body', [b'{"100.0.0.0/32":[],"100.0.0.0/32":[]}', b'{' , b'\xff', b' ' * (receive.MAX_BYTES + 1)])
def test_malformed_duplicate_and_oversized_bodies_refuse(body):
    with pytest.raises(ValueError): receive.parse_rib(body, fixture()[1])


@pytest.mark.parametrize('case', ['large', 'many_peers', 'wrong_target', 'disabled_diagnostics', 'nonboolean'])
def test_qualification_limits_refuse_before_runtime(case):
    recipe, _, _ = fixture()
    enabled, mode = True, 'basic'
    if case == 'large': recipe['resolved']['prefixes_per_peer'] = 9
    if case == 'many_peers': recipe['resolved'].update(neighbors=3, prefixes_per_peer=1)
    if case == 'wrong_target': recipe['roles']['target']['adapter'] = 'bird'
    if case == 'disabled_diagnostics': mode = 'none'
    if case == 'nonboolean': enabled = 1
    with pytest.raises(recipes.ContractError): receive.validate_selection(recipe, enabled, mode)


@pytest.mark.parametrize('failure', [None, 'foreign', 'paused', 'truncated', 'http', 'missing', 'body', 'sessions', 'incomplete'])
def test_owned_capture_preserves_status_and_separate_identity(tmp_path, monkeypatch, failure):
    recipe, expected, rib = fixture()
    (tmp_path / 'recipe.json').write_text(json.dumps(recipe))
    (tmp_path / 'runtime.json').write_text(json.dumps({'row': {'tester errors': 0, 'tester timeouts': 0}}))
    (tmp_path / 'raw-events.json').write_text(json.dumps({'events': [{
        'event': 'tester_complete', 'producer': 'attempt_bgperf_bird_tester_bgperf_bird_tester',
        'counters': {'sessions': 2, 'sessions_measured': 2, 'configured_prefixes': 16,
                     'expected_prefixes': 16, 'offered_prefixes': 8 if failure == 'incomplete' else 16}}]}))
    if failure != 'missing':
        (tmp_path / 'receive-expectation.json').write_text(json.dumps(expected))
    monkeypatch.setattr(receive.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(receive, 'cgroup_sample', lambda pid: {'usage_usec': None, 'reason': 'modeled unavailable'})
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        if 'ps' in argv: data = CID.encode()
        elif 'inspect' in argv:
            data = json.dumps([{'Id': CID, 'Name': '/attempt_bgperf_maghemite_target',
                'Image': 'sha256:' + '1' * 64,
                'Config': {'Labels': {'bgperf2.recipe.attempt': 'foreign' if failure == 'foreign' else 'attempt'}},
                'State': {'Running': True, 'Paused': failure == 'paused', 'Pid': 123}}]).encode()
        elif 'logs' in argv: data = b''
        elif 'exec' in argv:
            uri = argv[-1]
            assert uri.startswith('http://127.0.0.1:4676/')
            assert 'api-version: 13.0.0' in argv and '--max-time' in argv
            if '/neighbors?' in uri:
                assert uri.endswith('asn=64515')
                body = {p['address']: {'fsm_state': 'Idle' if failure == 'sessions' else 'Established',
                        'asn': p['asn'], 'remote_ip': p['address']} for p in expected['peers']}
            else: body = rib
            data = (b'{' if failure == 'body' else json.dumps(body).encode()) + receive.HTTP_MARKER
            data += b'500' if failure == 'http' else b'200'
        else: pytest.fail('Unexpected query')
        return {'data': data, 'text': data.decode(), 'captured_bytes': len(data),
                'truncated': failure == 'truncated' and 'exec' in argv, 'exit_code': 0}
    report = diagnostics.collect_diagnostics(tmp_path, 'attempt', {}, command=command,
        memory_reader=lambda pid: {}, target_adapter='maghemite', maghemite_receive=True)
    if failure == 'foreign':
        assert not any('exec' in c for c in calls)
        return
    receipt = json.loads((tmp_path / 'maghemite-receive.json').read_text())
    assert receipt['status'] == ('passed' if failure is None else 'unmeasured')
    assert 'no receive or transit timing' in receipt['scope']
    if failure is None:
        assert len(receipt['queries']) == 5
        assert all(q['request_completed_ns'] >= q['request_started_ns'] for q in receipt['queries'])
        assert receipt['queries'][1]['response']['identity']['prefix_count'] == 16
    if failure in ('paused', 'missing', 'incomplete'):
        assert not any('exec' in c for c in calls)


def test_partial_identity_is_failed_not_successful(tmp_path):
    _, expected, rib = fixture()
    rib.pop(next(iter(rib)))
    result = receive.parse_rib(json.dumps(rib).encode(), expected)
    assert not result['exact'] and len(result['missing']) == 1
