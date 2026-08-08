'''Cheap checks that catch whole classes of breakage without running anything.

graphs.py sat broken for a long time because it imported a module that no longer
existed -- nothing ever imported it, so nothing ever noticed.
'''
import importlib
import warnings

import pytest

from conftest import REPO_ROOT

MODULES = sorted(
    p.stem for p in REPO_ROOT.glob('*.py')
    if p.stem not in {'graphs', 'settings'}
)


@pytest.mark.parametrize('name', MODULES)
def test_module_imports(name):
    '''Catches undefined names at module scope, bad imports, and syntax errors.'''
    importlib.import_module(name)


@pytest.mark.parametrize('name', MODULES)
def test_module_compiles_without_warnings(name):
    '''SyntaxWarnings are deprecations -- invalid escape sequences today are
    errors in a future Python.
    '''
    source = (REPO_ROOT / f'{name}.py').read_text()
    with warnings.catch_warnings():
        warnings.simplefilter('error', SyntaxWarning)
        compile(source, f'{name}.py', 'exec')


def test_graphs_script_compiles():
    '''graphs.py is a __main__ script; compile it rather than import it.'''
    source = (REPO_ROOT / 'graphs.py').read_text()
    with warnings.catch_warnings():
        warnings.simplefilter('error', SyntaxWarning)
        compile(source, 'graphs.py', 'exec')


def test_graphs_imports_resolve():
    '''graphs.py imported `bgperf` (nonexistent) instead of `bgperf2`.'''
    import bgperf2
    assert hasattr(bgperf2, 'create_batch_graphs')
    assert hasattr(bgperf2, 'DEFAULT_RESULTS_DIR')


def test_benchmark_configs_reference_supported_targets():
    '''batch() assigns args.target straight from the yaml, bypassing argparse's
    choices validation -- so a typo here only surfaces mid-run.
    '''
    yaml = pytest.importorskip('yaml')
    import bgperf2

    parser = bgperf2.create_args_parser()
    bench = parser._subparsers._group_actions[0].choices['bench']
    supported = set(next(a for a in bench._actions if a.dest == 'target').choices)

    for config in sorted((REPO_ROOT / 'benchmarks').glob('*.yaml')):
        data = yaml.safe_load(config.read_text())
        for i, test in enumerate(data.get('tests') or []):
            # a stray '-' in the yaml yields a null entry, which crashes batch()
            # partway through the run
            assert test is not None, f"{config.name}: tests[{i}] is empty"
            for target in test.get('targets') or []:
                assert target is not None, f"{config.name}: tests[{i}] has an empty target"
                assert target['name'] in supported, \
                    f"{config.name}: target '{target['name']}' is not in {sorted(supported)}"
