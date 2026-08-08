'''Batch configs that name several versions of one daemon.

batch() is the reason versions exist -- one config, one run per release, and
results that can tell the releases apart afterwards.
'''
from argparse import Namespace

import pytest

import base
import bgperf2


class TestExpandTargetVersions:
    def test_one_entry_per_version(self):
        out = bgperf2.expand_target_versions(
            [{'name': 'frr_c', 'versions': ['8.0', '9.0', '10.3'], 'tester_type': 'bird'}])
        assert [t['version'] for t in out] == ['8.0', '9.0', '10.3']
        # everything else on the entry is carried through unchanged
        assert all(t['tester_type'] == 'bird' for t in out)
        assert all('versions' not in t for t in out)

    def test_labels_default_to_name_and_version(self):
        '''Without this the CSV has three rows all called frr_c.'''
        out = bgperf2.expand_target_versions([{'name': 'frr_c', 'versions': ['8.0', '9.0']}])
        assert [t['label'] for t in out] == ['frr_c 8.0', 'frr_c 9.0']

    def test_explicit_label_is_not_overwritten(self):
        out = bgperf2.expand_target_versions(
            [{'name': 'frr_c', 'version': '10.2', 'label': 'candidate'}])
        assert out == [{'name': 'frr_c', 'version': '10.2', 'label': 'candidate'}]

    def test_targets_without_versions_are_untouched(self):
        entry = {'name': 'bird', 'tester_type': 'bird'}
        assert bgperf2.expand_target_versions([entry]) == [entry]

    def test_numeric_yaml_values_become_strings(self):
        '''yaml hands back ints and floats; the tag was built from a string.'''
        out = bgperf2.expand_target_versions([{'name': 'frr_c', 'versions': [8.0, 10]}])
        assert [t['version'] for t in out] == ['8.0', '10']

    def test_does_not_mutate_the_input(self):
        entry = {'name': 'frr_c', 'versions': ['8.0']}
        bgperf2.expand_target_versions([entry])
        assert entry == {'name': 'frr_c', 'versions': ['8.0']}


def test_batch_yaml_keeps_versions_as_strings():
    '''Plain yaml reads 10.10 as the float 10.1, which would quietly bench the
    wrong release -- FRR has both a stable/10.1 and a stable/10.10.
    '''
    import yaml
    doc = '''
tests:
  - name: t
    neighbors: [10, 50]
    prefixes: [800_000]
    filter_test: [None]
    targets:
      - {name: frr_c, versions: [10.1, 10.10]}
'''
    test = yaml.load(doc, Loader=bgperf2.BatchLoader)['tests'][0]
    assert test['targets'][0]['versions'] == ['10.1', '10.10']
    # ints, including underscored ones, still parse as ints
    assert test['neighbors'] == [10, 50]
    assert test['prefixes'] == [800000]


@pytest.fixture
def fake_img_exists(monkeypatch):
    '''Patch img_exists in both modules.

    bgperf2 does `from base import *`, so it holds its own reference -- patching
    only one of them leaves half the lookups real.
    '''
    def _install(predicate):
        monkeypatch.setattr(base, 'img_exists', predicate)
        monkeypatch.setattr(bgperf2, 'img_exists', predicate)
    return _install


class TestCheckBatchImages:
    def test_reports_every_missing_image_at_once(self, fake_img_exists):
        fake_img_exists(lambda name: False)
        targets = bgperf2.expand_target_versions(
            [{'name': 'frr_c', 'versions': ['8.0', '9.0']}])
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_images(targets)
        # a batch is hours of work; one message should name all of it
        assert 'bgperf/frr_c:8.0' in str(e.value)
        assert 'bgperf/frr_c:9.0' in str(e.value)

    def test_passes_when_everything_is_built(self, fake_img_exists):
        fake_img_exists(lambda name: True)
        bgperf2.check_batch_images(
            bgperf2.expand_target_versions([{'name': 'frr_c', 'versions': ['8.0']}]))

    def test_explicit_image_is_checked_as_given(self, fake_img_exists):
        fake_img_exists(lambda name: name == 'my/frr:custom')
        bgperf2.check_batch_images([{'name': 'frr_c', 'image': 'my/frr:custom'}])
        with pytest.raises(SystemExit):
            bgperf2.check_batch_images([{'name': 'frr_c', 'image': 'my/frr:missing'}])

    def test_unknown_target_name(self, fake_img_exists):
        fake_img_exists(lambda name: True)
        with pytest.raises(SystemExit) as e:
            bgperf2.check_batch_images([{'name': 'frrouting'}])
        assert 'frrouting' in str(e.value)


class TestRunName:
    '''The name column and the graph filenames have to separate versions.'''
    def _args(self, **kw):
        base_args = {'target': 'frr_c', 'label': None, 'version': None}
        base_args.update(kw)
        return Namespace(**base_args)

    def test_version_appears_in_the_name(self):
        assert bgperf2.run_name(self._args(version='10.1')) == 'frr_c 10.1'

    def test_label_wins(self):
        assert bgperf2.run_name(self._args(version='10.1', label='candidate')) == 'candidate'

    def test_plain_target(self):
        assert bgperf2.run_name(self._args()) == 'frr_c'

    def test_works_without_a_version_attribute(self):
        '''bench() may be called with a Namespace that predates --version.'''
        assert bgperf2.run_name(Namespace(target='bird', label=None)) == 'bird'


def test_stats_row_names_the_version(bench_args, bench_stats):
    bench_args.version = '10.1'
    bench_args.target = 'frr_c'
    row = bgperf2.create_output_stats(bench_args, '10.1-my-manual-build', bench_stats)
    assert row[0] == 'frr_c 10.1'
    assert row[1] == 'frr_c'


def test_batch_passes_version_through_to_bench():
    '''batch() builds its Namespace from a field list; a field missing from
    that list is silently dropped at runtime.
    '''
    import inspect
    source = inspect.getsource(bgperf2.batch)
    assert "'version'" in source, 'batch() must copy version onto the bench args'
