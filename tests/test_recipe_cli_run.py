"""Public runtime dispatch keeps contract validation before any execution."""
import json
from pathlib import Path
import sys
import types

import recipes


FIXTURE = Path(__file__).resolve().parents[1] / 'examples/recipes/synthetic-ipv4.recipe.json'


def test_run_dispatch(tmp_path, monkeypatch, capsys):
    calls = []
    def run(document, **kwargs):
        calls.append((document, kwargs))
        return {'exit_code': 4, 'status': 'experiment_failed'}
    monkeypatch.setitem(sys.modules, 'recipe_run', types.SimpleNamespace(run_recipe=run))
    assert recipes.main(['run', str(FIXTURE), '--workdir', '/work/new',
                         '--results-dir', '/results/new', '--timeout', '12']) == 4
    assert calls[0][1] == {'workdir': '/work/new', 'results_dir': '/results/new', 'timeout': 12.0}
    assert json.loads(capsys.readouterr().out)['status'] == 'experiment_failed'


def test_invalid_recipe_never_dispatches(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'bad.json'
    path.write_text('{}')
    monkeypatch.setitem(sys.modules, 'recipe_run', None)
    assert recipes.main(['run', str(path), '--workdir', '/work/new',
                         '--results-dir', '/results/new']) == 2
    assert 'missing' in capsys.readouterr().err


def test_verify_dispatch(monkeypatch, capsys):
    calls = []
    def verify(path):
        calls.append(path)
        return {'verified': True}
    monkeypatch.setitem(sys.modules, 'recipe_results', types.SimpleNamespace(verify_result_package=verify))
    assert recipes.main(['result-verify', str(FIXTURE)]) == 0
    assert calls == [str(FIXTURE)]
    assert json.loads(capsys.readouterr().out) == {'verified': True}


def test_verify_fifo_manifest_refused_without_blocking(tmp_path):
    import os
    import subprocess
    path = tmp_path / 'result.json'
    os.mkfifo(path)
    result = subprocess.run([sys.executable, str(FIXTURE.parents[2] / 'recipes.py'),
                             'result-verify', str(path)], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 2
    assert 'regular' in result.stderr
    assert 'Traceback' not in result.stderr
