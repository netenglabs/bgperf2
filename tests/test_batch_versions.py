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


class TestReviewFixes:
    '''Regressions caught by review of the version-selection commits.'''

    def test_explicit_label_still_separates_versions(self):
        '''An explicit label on a multi-version entry named every run the same
        thing: duplicate CSV rows, per-run PNGs overwriting each other, and
        create_graph() raising a shape mismatch because it de-duplicates labels
        (labels[stat[0]]) but appends data per run.
        '''
        out = bgperf2.expand_target_versions(
            [{'name': 'frr_c', 'versions': ['8.5', '9.1'], 'label': 'frr'}])
        assert [t['label'] for t in out] == ['frr 8.5', 'frr 9.1']
        assert len({t['label'] for t in out}) == len(out)

    def test_single_version_keeps_the_label_verbatim(self):
        '''One run, one label -- nothing to disambiguate against.'''
        out = bgperf2.expand_target_versions(
            [{'name': 'frr_c', 'versions': ['10.2'], 'label': 'candidate'}])
        assert [t['label'] for t in out] == ['candidate']

    def test_batch_checks_every_test_before_running_any(self, fake_img_exists, tmp_path):
        '''Checking per-test still let a missing image in test 3 surface only
        after tests 1 and 2 had run -- the multi-hour wait this prevents.
        '''
        import yaml
        config = tmp_path / 'b.yaml'
        config.write_text(yaml.safe_dump({'tests': [
            {'name': 'first', 'neighbors': [1], 'prefixes': [1], 'filter_test': ['None'],
             'targets': [{'name': 'bird'}]},
            {'name': 'second', 'neighbors': [1], 'prefixes': [1], 'filter_test': ['None'],
             'targets': [{'name': 'frr_c', 'versions': ['99.9']}]},
        ]}))
        fake_img_exists(lambda name: '99.9' not in name)

        ran = []
        original = bgperf2.bench
        bgperf2.bench = lambda a: ran.append(a) or []
        try:
            with pytest.raises(SystemExit) as e:
                bgperf2.batch(Namespace(batch_config=str(config), results_dir=str(tmp_path)))
        finally:
            bgperf2.bench = original
        assert 'frr_c:99.9' in str(e.value)
        assert ran == [], 'test 1 ran before the missing image in test 2 was reported'

    def test_batch_resume_skips_durable_cells(self, fake_img_exists, tmp_path, monkeypatch):
        import yaml
        config = tmp_path / 'resume.yaml'
        config.write_text(yaml.safe_dump({'tests': [{
            'name': 'resume-test',
            'neighbors': [1],
            'prefixes': [10],
            'filter_test': ['None'],
            'targets': [
                {'name': 'bird', 'label': 'first'},
                {'name': 'bird', 'label': 'second'},
            ],
        }]}))
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)

        calls = []

        def interrupted(a):
            calls.append(a.label)
            if a.label == 'second':
                raise RuntimeError('interrupted')
            return ['first-result']

        monkeypatch.setattr(bgperf2, 'bench', interrupted)
        args = Namespace(batch_config=str(config), results_dir=str(tmp_path), resume=True)
        with pytest.raises(RuntimeError, match='interrupted'):
            bgperf2.batch(args)
        assert calls == ['first', 'second']

        calls.clear()
        monkeypatch.setattr(
            bgperf2, 'bench', lambda a: calls.append(a.label) or ['second-result'])
        bgperf2.batch(args)

        assert calls == ['second']
        csv_text = (tmp_path / 'resume-test.csv').read_text()
        assert 'first-result' in csv_text
        assert 'second-result' in csv_text

    def test_batch_resume_keeps_duplicate_cells_distinct(
            self, fake_img_exists, tmp_path, monkeypatch):
        import yaml
        config = tmp_path / 'duplicates.yaml'
        config.write_text(yaml.safe_dump({'tests': [{
            'name': 'duplicate-test',
            'neighbors': [1],
            'prefixes': [10],
            'filter_test': ['None'],
            'targets': [{'name': 'bird'}, {'name': 'bird'}],
        }]}))
        fake_img_exists(lambda name: True)
        monkeypatch.setattr(bgperf2, 'create_batch_graphs', lambda *a, **k: None)

        calls = []
        monkeypatch.setattr(
            bgperf2, 'bench', lambda a: calls.append(a.target) or ['result'])
        args = Namespace(batch_config=str(config), results_dir=str(tmp_path), resume=True)

        bgperf2.batch(args)
        assert calls == ['bird', 'bird']

        calls.clear()
        bgperf2.batch(args)
        assert calls == []


class TestBuildImageKwargs:
    def test_base_build_image_tolerates_version_kwargs(self, monkeypatch):
        '''build_version() always passes checkout=/version=. Forwarding them into
        build_dockerfile() raised TypeError, so a daemon that did not override
        build_image -- the case CLAUDE.md tells you to write -- could not build.
        '''
        seen = {}

        class Bare(base.Container):
            IMAGE_REPO = 'bgperf/bare'
            dockerfile = 'FROM scratch\n'

            @classmethod
            def build_dockerfile(cls, dockerfile, force, tag, nocache=False, buildargs=None):
                seen['tag'] = tag

        Bare.build_version('1.0')
        assert seen['tag'] == 'bgperf/bare:1.0'


class TestSecondRoundFixes:
    '''Regressions caught by review of the first round of review fixes.'''

    def test_image_resolves_before_containers_are_torn_down(self, monkeypatch):
        '''Moving resolution after the config parse also moved it after
        remove_target_containers() and the config-dir wipe, so a typo'd
        --version destroyed the previous run's containers before failing.
        CLAUDE.md keeps those around deliberately for investigation.
        '''
        order = []
        monkeypatch.setattr(bgperf2, 'remove_target_containers',
                            lambda: order.append('teardown'))
        monkeypatch.setattr(bgperf2, 'remove_old_containers', lambda: order.append('teardown'))
        monkeypatch.setattr(bgperf2, 'target_image',
                            lambda *a, **k: order.append('resolve') or 'img')

        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version='99.9', image=None, repeat=True)
        with pytest.raises(Exception):
            bgperf2.bench(args)
        assert order and order[0] == 'resolve', \
            'containers were torn down before the image was resolved: {0}'.format(order)

    def test_batch_skips_image_check_for_scenario_files(self, fake_img_exists):
        '''A -f scenario can declare the target remote, which has no local
        image; checking one aborted the whole batch before anything ran.
        '''
        fake_img_exists(lambda name: False)
        bgperf2.check_batch_images([{'name': 'bird', 'file': 'scenario.yaml'}])

    def test_batch_still_checks_normal_targets(self, fake_img_exists):
        fake_img_exists(lambda name: False)
        with pytest.raises(SystemExit):
            bgperf2.check_batch_images([{'name': 'bird'}])
