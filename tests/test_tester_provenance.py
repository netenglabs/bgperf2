import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bgperf2
import base
from base import Tester
from bgpdump2 import Bgpdump2Tester
from mrt_tester import ExaBGPMrtTester, GoBGPMRTTester
from tester import BIRDTester, ExaBGPTester


class FixtureTester(Tester):
    CONTAINER_NAME_PREFIX = 'bgperf_fixture_tester_'
    GUEST_DIR = '/fixture'


class FakeDocker:
    def containers(self, **kwargs):
        return []

    def create_host_config(self, **kwargs):
        return kwargs

    def create_container(self, **kwargs):
        return {'Id': 'container-id'}

    def inspect_container(self, container_id):
        return {'Name': '/docker-returned-name', 'Image': 'sha256:image-id'}

    def networks(self, names):
        return [{
            'Name': names[0],
            'Id': 'network-id',
            'IPAM': {'Config': [{'Subnet': '10.0.0.0/24'}]},
        }]

    def connect_container_to_network(self, *args, **kwargs):
        pass

    def start(self, **kwargs):
        pass


class TesterProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_log(self, directory, name, contents):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(contents, encoding='utf-8')

    def test_all_tester_names_apply_their_prefix_once(self):
        conf = {'neighbors': {}}
        cases = (
            (ExaBGPTester, 'bgperf_exabgp_tester_row'),
            (BIRDTester, 'bgperf_bird_tester_row'),
            (ExaBGPMrtTester, 'bgperf_exabgp_mrttester_row'),
            (GoBGPMRTTester, 'bgperf_gobgp_mrttester_row'),
            (Bgpdump2Tester, 'bgperf_bgpdump2_tester_row'),
        )

        for tester_class, expected_name in cases:
            with self.subTest(tester_class=tester_class.__name__):
                host_dir = self.root / tester_class.__name__
                tester = tester_class('row', str(host_dir), conf)
                self.assertEqual(expected_name, tester.name)

    def test_base_diagnostics_are_instance_local(self):
        own_dir = self.root / 'own'
        sibling_dir = self.root / 'sibling'
        tester = FixtureTester('row', str(own_dir), {'neighbors': {}}, 'fixture:image')
        self.write_log(own_dir, 'tester.log', 'ERROR one\nTimeout one\nordinary line\n')
        self.write_log(own_dir, 'ignored.txt', 'ERROR two\nTimeout two\n')
        self.write_log(sibling_dir, 'tester.log', 'ERROR three\nTimeout three\n')

        self.assertEqual(1, tester.find_errors())
        self.assertEqual(1, tester.find_timeouts())

    def test_bird_expected_messages_are_not_errors(self):
        host_dir = self.root / 'bird'
        tester = BIRDTester('row', str(host_dir), {'neighbors': {}})
        self.write_log(
            host_dir,
            'bird.log',
            '\n'.join((
                'RMT Connection collision resolution',
                'RMT Invalid NEXT_HOP attribute',
                'RMT malformed attribute',
                'RMT hold timeout',
            )),
        )

        self.assertEqual(2, tester.find_errors())
        self.assertEqual(1, tester.find_timeouts())

    def test_mrt_and_bgpdump_diagnostics_use_their_own_rows(self):
        gobgp_dir = self.root / 'gobgp-mrt'
        bgpdump_dir = self.root / 'bgpdump-mrt'
        gobgp = GoBGPMRTTester('gobgp', str(gobgp_dir), {'neighbors': {}})
        bgpdump = Bgpdump2Tester('bgpdump', str(bgpdump_dir), {'neighbors': {}})
        self.write_log(gobgp_dir, 'gobgpd.log', 'peer expired\nrequest timeout\n')
        self.write_log(bgpdump_dir, 'bgpdump2.log', 'ERROR decode\nTIMEOUT connect\n')

        self.assertEqual(1, gobgp.find_errors())
        self.assertEqual(1, gobgp.find_timeouts())
        self.assertEqual(1, bgpdump.find_errors())
        self.assertEqual(1, bgpdump.find_timeouts())

    def test_diagnostics_aggregate_every_instance(self):
        testers = (
            SimpleNamespace(find_errors=lambda: 1, find_timeouts=lambda: 2),
            SimpleNamespace(find_errors=lambda: 3, find_timeouts=lambda: 4),
        )
        self.assertEqual(
            {'errors': 4, 'timeouts': 6},
            bgperf2.collect_tester_diagnostics(testers),
        )

    def test_container_run_retains_docker_returned_provenance(self):
        host_dir = self.root / 'runtime'
        tester = FixtureTester(
            'row',
            str(host_dir),
            {'neighbors': {'peer': {'local-address': '10.0.0.2'}}},
            'fixture:tag',
        )

        with patch.object(base, 'dckr', FakeDocker()):
            base.Container.run(tester, 'row-br')

        self.assertEqual('row', tester.configured_name)
        self.assertEqual('docker-returned-name', tester.name)
        self.assertEqual('container-id', tester.ctn_id)
        self.assertEqual('sha256:image-id', tester.image_id)
        self.assertEqual('row-br', tester.network_name)
        self.assertEqual('network-id', tester.network_id)
        manifest_path = bgperf2.write_runtime_manifest(
            self.temporary_directory.name, (('tester', tester),),
        )
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        self.assertEqual('docker-returned-name', manifest['instances'][0]['container_name'])

    def test_runtime_manifest_uses_actual_instance_values_atomically(self):
        row_dir = self.root / 'row'
        row_dir.mkdir()
        instances = (
            ('monitor', SimpleNamespace(
                name='bgperf_monitor', ctn_id='monitor-id', image='monitor:image', image_id='monitor-image-id',
                network_name='row-br', network_id='network-id',
                host_dir=str(row_dir / 'monitor'),
            )),
            ('tester', SimpleNamespace(
                name='bgperf_bird_tester_row', ctn_id='tester-id', image='tester:image', image_id='tester-image-id',
                network_name='row-br', network_id='network-id',
                configured_name='row',
                host_dir=str(row_dir / 'tester'),
            )),
            ('target', SimpleNamespace(
                name='bgperf_target', ctn_id='target-id', image='target:image', image_id='target-image-id',
                network_name='row-br', network_id='network-id',
                host_dir=str(row_dir / 'target'),
            )),
        )

        with patch.object(bgperf2.os, 'replace', wraps=os.replace) as replace:
            manifest_path = bgperf2.write_runtime_manifest(
                str(row_dir), instances,
            )

        replace.assert_called_once()
        self.assertFalse((row_dir / 'runtime-manifest.json.tmp').exists())
        self.assertEqual(str(row_dir / 'runtime-manifest.json'), manifest_path)
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        self.assertEqual(['monitor', 'tester', 'target'], [row['role'] for row in manifest['instances']])
        self.assertEqual(
            {
                'container_name': 'bgperf_bird_tester_row',
                'container_id': 'tester-id',
                'configured_image': 'tester:image',
                'image_id': 'tester-image-id',
                'network_name': 'row-br',
                'network_id': 'network-id',
                'host_dir': str((row_dir / 'tester').resolve()),
                'role': 'tester',
                'configured_name': 'row',
            },
            manifest['instances'][1],
        )

    def test_runtime_manifest_refuses_missing_or_duplicate_identity(self):
        row_dir = self.root / 'row'
        row_dir.mkdir()
        missing = SimpleNamespace(
            name='missing', image='image', host_dir=str(row_dir / 'missing'),
        )
        duplicate_a = SimpleNamespace(
            name='a', ctn_id='same-id', image='image:a', image_id='image-a-id',
            network_name='row-br', network_id='net', host_dir=str(row_dir / 'a'),
        )
        duplicate_b = SimpleNamespace(
            name='b', ctn_id='same-id', image='image:b', image_id='image-b-id',
            network_name='row-br', network_id='net', host_dir=str(row_dir / 'b'),
        )

        with self.assertRaisesRegex(RuntimeError, 'no container ID'):
            bgperf2.write_runtime_manifest(str(row_dir), (('tester', missing),))
        with self.assertRaisesRegex(RuntimeError, 'duplicate container identity'):
            bgperf2.write_runtime_manifest(
                str(row_dir), (('tester', duplicate_a), ('tester', duplicate_b)),
            )
        self.assertFalse((row_dir / 'runtime-manifest.json').exists())

    def assert_bench_repeat_rejected_before_mutation(self, value):
        run_root = self.root / 'bench'
        args = SimpleNamespace(repeat=value, dir=str(run_root), bench_name='row')
        with patch.object(
            bgperf2,
            'remove_target_containers',
            side_effect=AssertionError('mutation reached'),
        ) as remove:
            with self.assertRaisesRegex(ValueError, 'run a fresh row'):
                bgperf2.bench(args)
        remove.assert_not_called()
        self.assertFalse(run_root.exists())

    def test_bench_rejects_repeat_true_before_mutation(self):
        self.assert_bench_repeat_rejected_before_mutation(True)

    def test_bench_rejects_repeat_false_before_mutation(self):
        self.assert_bench_repeat_rejected_before_mutation(False)

    def assert_batch_repeat_rejected_by_whole_file_preflight(self, value):
        batch_file = self.root / 'batch.yaml'
        batch_file.write_text(
            'tests:\n'
            '  - name: clean-test\n'
            '    neighbors: [1]\n'
            '    prefixes: [1]\n'
            "    filter_test: ['None']\n"
            '    targets:\n'
            '      - name: clean-target\n'
            '  - name: destructive-proof\n'
            '    neighbors: [1]\n'
            '    prefixes: [1]\n'
            "    filter_test: ['None']\n"
            '    targets:\n'
            '      - name: bad-target\n'
            '        repeat: {0}\n'.format('true' if value else 'false'),
            encoding='utf-8',
        )
        args = SimpleNamespace(batch_config=str(batch_file))
        old_cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with patch.object(bgperf2, 'bench', side_effect=AssertionError('row executed')) as bench:
                with self.assertRaisesRegex(
                    ValueError,
                    "test 'destructive-proof' target 'bad-target'.*fresh tester instances",
                ):
                    bgperf2.batch(args)
            bench.assert_not_called()
            self.assertFalse((self.root / 'destructive-proof.csv').exists())
        finally:
            os.chdir(old_cwd)

    def test_batch_rejects_repeat_true_before_any_row_or_output(self):
        self.assert_batch_repeat_rejected_by_whole_file_preflight(True)

    def test_batch_rejects_repeat_false_before_any_row_or_output(self):
        self.assert_batch_repeat_rejected_by_whole_file_preflight(False)

    def test_diagnostic_methods_are_instances_without_shell_or_global_tmp(self):
        for tester_class in (Tester, BIRDTester, GoBGPMRTTester, Bgpdump2Tester):
            with self.subTest(tester_class=tester_class.__name__):
                self.assertEqual(
                    ['self'],
                    list(inspect.signature(tester_class.find_errors).parameters),
                )

        repository = Path(__file__).resolve().parents[1]
        for relative_path in ('base.py', 'tester.py', 'mrt_tester.py', 'bgpdump2.py'):
            source = (repository / relative_path).read_text(encoding='utf-8')
            self.assertNotIn('/tmp/bgperf2', source)
            self.assertNotIn('shell=True', source)
            self.assertNotIn('Popen', source)


if __name__ == '__main__':
    unittest.main()
