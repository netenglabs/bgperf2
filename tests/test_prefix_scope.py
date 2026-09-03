'''Peer scaling: raising the session count without raising the route count.

`gen_conf()` gives every neighbour its own `gen_paths(p)` off a shared
iterator, so the peers get disjoint prefixes and the table is `n * p`. Sessions
and table size are therefore one axis, and a batch sweeping `neighbors:
[10, 25, 50]` at a fixed `prefixes` sweeps both at once -- nothing downstream
can separate "50 sessions were slower" from "five times the routes were
slower". `benchmarks/2026-core-synth.yaml` is exactly that shape: its four
cells hold 500k, 1M, 2.5M and 5M routes.

`--prefix-scope total` reads `-p` as the whole table instead, and the result is
normalised to a per-peer count before anything reads it, because the two forms
are the same workload and must produce the same row.
'''
from argparse import Namespace

import pytest

import bgperf2


def a_test(**overrides):
    test = {
        'name': 'scale',
        'neighbors': [10],
        'prefixes': [100_000],
        'filter_test': ['None'],
        'targets': [{'name': 'bird'}],
    }
    test.update(overrides)
    return test


class TestResolvingTheScope:
    def test_per_peer_is_what_it_has_always_been(self):
        assert bgperf2.resolve_prefix_scope('per-peer', 50, 100_000) == 100_000

    def test_an_absent_scope_is_per_peer(self):
        '''Every existing config and every existing command line.'''
        assert bgperf2.resolve_prefix_scope(None, 50, 100_000) == 100_000

    def test_total_splits_the_table_across_the_peers(self):
        assert bgperf2.resolve_prefix_scope('total', 50, 100_000) == 2_000

    def test_the_table_stays_the_size_it_was_asked_for(self):
        for peers in (10, 25, 50, 100):
            assert peers * bgperf2.resolve_prefix_scope(
                'total', peers, 100_000) == 100_000

    def test_one_peer_takes_the_whole_table(self):
        assert bgperf2.resolve_prefix_scope('total', 1, 100_000) == 100_000

    def test_an_inexact_division_is_refused(self):
        """A remainder means the peers do not all offer the same table, so
        `prefixes per peer` is a number true of none of them, each neighbour's
        check-point differs, and the monitor's stops being `n * p`.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 3, 100_000)
        assert 'do not divide evenly' in str(raised.value)

    def test_the_refusal_offers_counts_that_would_work(self):
        """A message that only says the division failed leaves the operator
        doing arithmetic on a 1,050,000-prefix RIB.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 3, 100_000)
        message = str(raised.value)
        assert '99999' in message and '100002' in message
        for suggested in (2, 4):
            assert str(suggested) in message

    def test_more_peers_than_prefixes_is_refused(self):
        '''A session that offers nothing is not a peer under test.'''
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 100, 50)
        assert 'leaves peers with none' in str(raised.value)

    @pytest.mark.parametrize('tester', bgperf2.MRT_TESTER_TYPES)
    def test_an_mrt_tester_has_nothing_to_divide(self, tester):
        """`gen_conf()` sets the monitor check-point straight from `-p` for
        these, so it is already the whole table. Silently accepting the scope
        would halve nothing and look like it worked.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 10, 1_050_000, tester)
        assert 'MRT file' in str(raised.value)

    def test_an_mrt_tester_is_fine_without_the_scope(self):
        assert bgperf2.resolve_prefix_scope(
            'per-peer', 10, 1_050_000, 'bgpdump2') == 1_050_000

    def test_an_unknown_scope_is_refused(self):
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('half', 10, 100)
        assert 'unknown prefix scope' in str(raised.value)


class TestTheScenarioItProduces:
    """The two forms are the same workload, so they must produce the same
    scenario -- not merely an equivalent one. Everything downstream is keyed on
    the per-peer count: the CSV column is `prefixes per peer`,
    `bench_output_prefix()` names artifacts from `prefix_num`, and
    `create_graph()` groups bars by it.
    """

    def scenario(self, **overrides):
        args = Namespace(
            neighbor_num=50, prefix_num=2_000, filter_type='in',
            as_path_list_num=0, prefix_list_num=0, community_list_num=0,
            ext_community_list_num=0, single_table=False,
            target_config_file=None, local_address_prefix='10.10.0.0/16',
            target_local_address=None, target_router_id=None,
            monitor_local_address=None, monitor_router_id=None,
            filter_test=None, license_file=None, threads=None,
            tester_type='bird', mrt_file=None, prefix_scope='per-peer')
        for name, value in overrides.items():
            setattr(args, name, value)
        args.prefix_num = bgperf2.resolve_prefix_scope(
            args.prefix_scope, args.neighbor_num, args.prefix_num,
            args.tester_type)
        return bgperf2.gen_conf(args)

    def test_the_two_forms_produce_the_same_scenario(self):
        assert self.scenario(prefix_num=100_000, prefix_scope='total') == \
            self.scenario(prefix_num=2_000)

    def test_the_monitor_checkpoint_covers_the_whole_table(self):
        '''99% of 100,000, not of 5,000,000.'''
        import yaml
        from mako.template import Template
        conf = yaml.safe_load(Template(
            self.scenario(prefix_num=100_000, prefix_scope='total')).render())
        assert conf['monitor']['check-points'] == [99_000]
        assert len(conf['testers'][0]['neighbors']) == 50
        assert all(n['count'] == 2_000
                   for n in conf['testers'][0]['neighbors'].values())


class TestTheBatchAxis:
    def test_a_matrix_holds_the_table_size_while_the_peers_move(self):
        """The axis that did not exist. Without it a peer sweep is a table
        sweep, and the two cannot be told apart afterwards.
        """
        test = a_test(prefix_scope='total', neighbors=[10, 25, 50])
        cells = bgperf2.expand_batch_cells(test, test['targets'])
        assert [(c['neighbors'], c['prefixes']) for c in cells] == [
            (10, 10_000), (25, 4_000), (50, 2_000)]
        assert {c['neighbors'] * c['prefixes'] for c in cells} == {100_000}

    def test_without_the_scope_a_peer_sweep_is_still_a_table_sweep(self):
        '''Unchanged behaviour for every existing config.'''
        test = a_test(neighbors=[10, 25, 50])
        cells = bgperf2.expand_batch_cells(test, test['targets'])
        assert {c['neighbors'] * c['prefixes'] for c in cells} == {
            1_000_000, 2_500_000, 5_000_000}

    def test_an_inexact_cell_is_refused_before_the_first_container(self):
        """A matrix is where an inexact split is easy to write: 1,050,000
        divides by 10 and 25 but not by 9. Finding that out at cell three is
        hours lost to arithmetic.
        """
        test = a_test(prefix_scope='total', neighbors=[10, 25, 9],
                      prefixes=[1_050_000])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'do not divide evenly' in str(raised.value)
        assert "test 'scale'" in str(raised.value)

    def test_every_combination_is_checked_not_just_the_first(self):
        test = a_test(prefix_scope='total', neighbors=[10],
                      prefixes=[100_000, 100_001])
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(test)

    def test_a_misspelt_scope_is_refused(self):
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(prefix_scopes='total'))
        assert 'unrecognised' in str(raised.value)

    def test_the_key_is_recognised(self):
        bgperf2.check_batch_test(a_test(prefix_scope='total'))


class TestWhatTheBatchPathMustNotAccept:
    """Three defects review found after the CLI path was right. The batch path
    is the one that matters: a CLI mistake costs one run, a batch mistake costs
    a matrix, and nobody is watching it.
    """

    def test_an_mrt_target_is_refused_on_the_batch_path_too(self):
        """The CLI refused this and the batch accepted it, because
        `check_batch_test()` and `expand_batch_cells()` never passed the
        tester. `gen_conf()` sets the monitor check-point straight from `-p`
        for these, so a 1,050,000-prefix table divided by 10 peers reports
        CONVERGED at 103,950 -- a tenth of the table, with nothing in the row
        or the artifacts saying so.
        """
        test = a_test(prefix_scope='total', prefixes=[1_050_000],
                      targets=[{'name': 'bird', 'tester_type': 'bgpdump2',
                                'mrt_file': '/x.mrt'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'MRT file' in str(raised.value)

    def test_one_mrt_target_poisons_the_whole_test(self):
        """`prefixes` is a single axis shared by every target, so a test mixing
        an MRT generator with a synthetic one under `total` cannot be right for
        both.
        """
        test = a_test(prefix_scope='total', prefixes=[1_050_000],
                      targets=[{'name': 'bird', 'tester_type': 'bird'},
                               {'name': 'frr_c', 'tester_type': 'bgpdump2',
                                'mrt_file': '/x.mrt'}])
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(test)

    def test_an_mrt_target_without_the_scope_is_untouched(self):
        test = a_test(prefixes=[1_050_000],
                      targets=[{'name': 'bird', 'tester_type': 'bgpdump2',
                                'mrt_file': '/x.mrt'}])
        bgperf2.check_batch_test(test)
        cells = bgperf2.expand_batch_cells(test, test['targets'])
        assert cells[0]['prefixes'] == 1_050_000

    @pytest.mark.parametrize('axis', ['neighbors', 'prefixes'])
    def test_a_quoted_axis_is_named_rather_than_a_traceback(self, axis):
        """The bare-`TypeError` failure mode `check_batch_test()` exists to
        eliminate, reintroduced by arithmetic that runs before anything checks
        the type.
        """
        test = a_test(prefix_scope='total', **{axis: ['10']})
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'must be whole numbers' in str(raised.value)
        assert axis in str(raised.value)

    def test_a_boolean_is_not_a_count(self):
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(a_test(neighbors=[True]))

    @pytest.mark.parametrize('axis', ['neighbors', 'prefixes'])
    @pytest.mark.parametrize('value', [0, -5])
    def test_a_cell_with_no_peers_or_no_prefixes_is_refused(self, axis, value):
        """Zero and negative pass a bare type check, and `resolve_prefix_scope()`
        catches them only under `total`. Under the default scope nothing did:
        `gen_conf()` built a scenario with no testers and a monitor check-point
        of `int(0 * 0.99)`, satisfied at zero routes, so the cell wrote a row
        that reads as a converged run.
        """
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(**{axis: [value]}))
        assert '1 or more' in str(raised.value)

    def test_one_bad_value_among_good_ones_is_still_refused(self):
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(a_test(neighbors=[10, 0, 50]))

    def test_an_unusable_peer_suggestion_is_not_offered(self):
        """`below` fell through to 1 and `above` walked to `prefix_num`, so a
        prime-ish table was answered with "or 1 or 4999999 peers" after a fifth
        of a second of scanning. A suggestion the operator cannot act on is
        worse than none: it reads as the tool having thought about it.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 3, 4_999_999)
        message = str(raised.value)
        assert 'peers' not in message.split('untrue of every peer;')[1]
        assert '4999998' in message and '5000001' in message

    def test_a_usable_peer_suggestion_still_is(self):
        message = ''
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 3, 100_000)
        message = str(raised.value)
        assert 'or 2 or 4 peers' in message

    def test_the_search_for_one_is_bounded(self):
        """It scanned to `prefix_num`, which is the table size."""
        assert bgperf2._divisors_near(4_999_999, 3) == []
        assert all(n <= bgperf2.MAX_SUGGESTED_PEERS
                   for n in bgperf2._divisors_near(1_050_000, 9))

    def test_a_peer_per_prefix_is_not_a_suggestion(self):
        """A peer count equal to the table size divides it exactly and gives
        each session one route -- the same unusable advice as suggesting five
        million peers, reached from the other end.
        """
        with pytest.raises(ValueError) as raised:
            bgperf2.resolve_prefix_scope('total', 400, 600)
        assert '600 peers' not in str(raised.value)
        assert 'or 300 peers' in str(raised.value)

    def test_the_cap_is_a_distance_not_an_absolute_ceiling(self):
        """An absolute one offers nothing at all to anybody who asked for more
        than the cap: 513 peers got no upward suggestion even though 625
        divides 1,000,000 exactly.
        """
        assert bgperf2._divisors_near(1_000_000, 513) == [500, 625]

    def test_the_cap_bounds_how_far_above_the_asked_for_count_it_looks(self):
        """Only upward, and only past what was asked for. A large peer count
        would otherwise get no suggestion at all, having asked for more than
        the cap -- and a divisor below what was asked for is by construction a
        number the operator was willing to be near.
        """
        near = bgperf2._divisors_near(999_999, 1_500)
        assert near and all(n < 1_500 for n in near)
        assert max(near) > bgperf2.MAX_SUGGESTED_PEERS

    def test_a_test_key_written_under_a_target_is_refused(self):
        """Every other knob is a target key -- `threads`, `tester_type`,
        `mrt_file`, `image`, `version` -- so writing this one level too deep is
        the natural slip, and it fails silently and expensively: the target is
        run at `neighbors x prefixes`, which at 50 peers is 5,000,000 routes
        instead of 100,000. It converges, and writes rows and bars that read as
        a peer sweep.
        """
        test = a_test(neighbors=[10, 50],
                      targets=[{'name': 'bird', 'tester_type': 'bird'},
                               {'name': 'frr_c', 'tester_type': 'bird',
                                'prefix_scope': 'total'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'prefix_scope' in str(raised.value)
        assert 'up one level' in str(raised.value)

    @pytest.mark.parametrize('key,value', [
        ('repetitions', 3), ('order', 'shuffle'), ('seed', 7),
        ('neighbors', [10]), ('prefixes', [100]), ('filter_test', ['None'])])
    def test_every_test_only_key_is_refused_under_a_target(self, key, value):
        """Each fails silently: a misplaced `repetitions` runs one pass of a
        matrix somebody asked three of, a misplaced `order` runs the matrix
        order it says it is not running.
        """
        test = a_test(targets=[{'name': 'bird', key: value}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert key in str(raised.value)

    def test_the_target_keys_that_belong_there_are_untouched(self):
        """No allowlist of target keys: `batch()` reads a fixed field list and
        ignores the rest, and enumerating them here would reject configs this
        has no business rejecting.
        """
        bgperf2.check_batch_test(a_test(targets=[{
            'name': 'bird', 'label': 'bird 3', 'version': '3.3.2',
            'threads': 4, 'tester_type': 'bird', 'image': 'x',
            'single_table': True, 'license_file': 'l'}]))
        # `mrt_file` belongs on a target too -- with a generator that reads it.
        bgperf2.check_batch_test(a_test(targets=[{
            'name': 'bird', 'tester_type': 'bgpdump2', 'mrt_file': '/x.mrt',
            'mrt_injector': 'bgpdump2'}]))


class TestTheScopeUnderAScenarioFile:
    def test_a_scope_with_nothing_to_divide_is_refused(self):
        """`-n`/`-p` are already ignored under `-f` and this would be too, but
        the whole point of the flag is that the number means something
        different, so accepting it where it does nothing is worse than the
        existing silence about the two it joins.
        """
        args = Namespace(file='scenario.yaml', prefix_scope='total',
                         dir='/tmp', bench_name='x', docker_network_name=None,
                         target='bird', version=None, image=None, repeat=True)
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(args)
        assert 'nothing to divide under -f' in str(raised.value)

    @pytest.mark.parametrize('flag,value', [
        ('neighbor_num', 0), ('neighbor_num', -1),
        ('prefix_num', 0), ('prefix_num', -1)])
    def test_the_cli_refuses_a_run_that_would_converge_on_nothing(self, flag,
                                                                  value):
        """`check_batch_test()` refuses these on the batch path and nothing did
        here: `resolve_prefix_scope()` is the single normalisation point, but it
        only rejects them under `total`, so `bench -n 0` reached `gen_conf()`
        untouched and the run wrote a row that reads as converged.
        """
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=True, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird')
        setattr(args, flag, value)
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(args)
        assert '1 or more' in str(raised.value)

    def test_config_refuses_a_scenario_that_converges_on_nothing(self):
        """`bench -f` deliberately skips the positive-count guard, on the
        reasoning that a scenario file states its own neighbours. A scenario
        stating *none* -- `check-points: [0]` and no testers, satisfied at zero
        routes -- passes straight through it, and the tool that would have
        produced that file is this one.
        """
        args = Namespace(neighbor_num=0, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         output='/dev/null')
        with pytest.raises(SystemExit) as raised:
            bgperf2.config(args)
        assert '1 or more' in str(raised.value)

    def test_a_scenario_target_has_nothing_to_divide(self):
        """`bench()` refuses this and its refusal is unreachable from the batch
        path, because `batch()` pins `per-peer` on the synthesized args once
        the division has happened. The cell would carry a divided count in its
        id, its `prefixes per peer` column and every artifact name while
        running whatever the file describes.
        """
        test = a_test(prefix_scope='total',
                      targets=[{'name': 'bird', 'file': 'scenario.yaml'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'nothing to divide' in str(raised.value)

    def test_a_scenario_target_without_the_scope_is_untouched(self):
        bgperf2.check_batch_test(
            a_test(targets=[{'name': 'bird', 'file': 'scenario.yaml'}]))


class TestAnUnstatedGenerator:
    def test_an_absent_tester_type_defaults_the_way_the_cli_does(self):
        """`batch()` gave every unset field `None`, and `gen_conf()` routes
        anything that is not `exa` or `bird` down the MRT branch, where a
        missing `mrt_file` is a bare `exit(1)` -- so a target that simply
        omitted `tester_type` passed every up-front check and then killed the
        whole batch part way through.
        """
        assert bgperf2.BATCH_FIELD_DEFAULTS['tester_type'] == 'bird'

    def test_the_default_matches_the_bench_parsers_own(self):
        parser = bgperf2.create_args_parser()
        args = parser.parse_args(['bench'])
        assert args.tester_type == bgperf2.BATCH_FIELD_DEFAULTS['tester_type']

    def test_an_mrt_target_without_a_file_is_refused_up_front(self):
        """`gen_conf()` ends an MRT run with no file at a bare `exit(1)`, and
        that `SystemExit` travels out of `bench()` and out of `batch()`,
        killing the matrix at whichever cell reached it. Defaulting an omitted
        `tester_type` closed one shape of that failure; this is the other.
        """
        test = a_test(targets=[{'name': 'bird', 'tester_type': 'bgpdump2'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'no mrt_file' in str(raised.value)

    def test_an_mrt_target_with_a_file_is_fine(self):
        bgperf2.check_batch_test(a_test(targets=[
            {'name': 'bird', 'tester_type': 'bgpdump2', 'mrt_file': '/x.mrt'}]))

    def test_an_empty_tester_type_reads_as_absent(self):
        """`tester_type:` with nothing after it parses as None -- the very slip
        the default exists to catch -- and a key-presence test skips the
        default for exactly that case, so the cell reached the MRT branch and
        died mid-batch.
        """
        assert bgperf2.batch_target_field({'tester_type': None},
                                          'tester_type') == 'bird'
        bgperf2.check_batch_test(
            a_test(targets=[{'name': 'bird', 'tester_type': None}]))

    def test_reading_the_default_does_not_rewrite_the_target(self):
        """The target dict is part of the cell identity, and the cell id is
        what `--resume` matches on, so filling a default into it renames every
        completed cell of every in-flight batch.
        """
        target = {'name': 'bird'}
        test = a_test(targets=[target])
        bgperf2.check_batch_test(test)
        assert target == {'name': 'bird'}

    def test_an_unrecognised_tester_type_is_refused(self):
        """`gen_conf()` branches on `not in ('exa', 'bird')`, not on the MRT
        list, so an unrecognised value is treated as an MRT injector -- and a
        batch target bypasses argparse's `choices` entirely. A typo therefore
        reached the MRT branch and died at its bare `exit(1)`, taking the rest
        of the matrix with it. Keying the mrt_file guard on the MRT list alone
        left that open.
        """
        test = a_test(targets=[{'name': 'bird', 'tester_type': 'brid'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'brid' in str(raised.value)

    def test_the_cli_and_the_batch_accept_the_same_generators(self):
        parser = bgperf2.create_args_parser()
        for tester in bgperf2.TESTER_TYPES:
            parser.parse_args(['bench', '-g', tester])
        assert set(bgperf2.TESTER_TYPES) == set(
            bgperf2.SYNTHETIC_TESTER_TYPES) | set(bgperf2.MRT_TESTER_TYPES)

    def test_a_target_without_a_name_is_named_rather_than_a_traceback(self):
        """`', '.join()` over targets with neither name nor label raised a bare
        TypeError -- the traceback naming neither the test nor the key that
        this function exists to eliminate, produced by the checks added to
        eliminate it.
        """
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(a_test(targets=[{'tester_type': 'gobgp'}]))
        assert 'needs a `name`' in str(raised.value)

    def test_a_scenario_target_is_not_refused_for_its_generator(self):
        """A `file:` target never reaches `gen_conf()` -- `bench()` loads the
        scenario instead -- so its generator is inert, and refusing it rejects
        a config that would have run.
        """
        bgperf2.check_batch_test(a_test(targets=[
            {'name': 'bird', 'file': 's.yaml', 'tester_type': 'gobgp'}]))

    def test_an_unstated_filter_type_matches_the_cli(self):
        """`batch()` handed `bench()` None, `gen_conf()` writes
        `filter: {args.filter_type: assignment}`, and every target's config
        writer looks for the literal key `'in'` -- so a batch target with
        policy counts and no `filter_type` produced `filter: {null: [p2]}`, ran
        unfiltered, and reported as a filtered run.
        """
        parser = bgperf2.create_args_parser()
        assert bgperf2.BATCH_FIELD_DEFAULTS['filter_type'] == \
            parser.parse_args(['bench']).filter_type

    @pytest.mark.parametrize('key', ['mrt_injector', 'mrt_file'])
    def test_mrt_intent_without_an_mrt_generator_is_refused(self, key):
        """Before `tester_type` had a default this failed loudly: `None` took
        `gen_conf()`'s MRT branch and `bench()` stopped at `invalid
        mrt_injector: None`. The default turned it into a synthetic BIRD run --
        `mrt_file` never read, the monitor check-point `n * p` instead of `p`,
        a converged row and artifacts, and nothing saying the table was never
        played back. A default that makes a wrong workload quiet is worse than
        the crash it replaced.
        """
        test = a_test(targets=[{'name': 'bird', key: 'bgpdump2'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert key in str(raised.value)

    def test_an_explicit_synthetic_generator_is_refused_the_same_way(self):
        """Not only the defaulted case: writing both out is the same mistake
        and produces the same silent run.
        """
        test = a_test(targets=[{'name': 'bird', 'tester_type': 'bird',
                                'mrt_file': '/x.mrt'}])
        with pytest.raises(SystemExit):
            bgperf2.check_batch_test(test)

    def test_an_injector_that_disagrees_with_the_generator_is_refused(self):
        """`gen_conf()` derives the injector from `tester_type` and never reads
        `mrt_injector`, so one that disagrees is not a second opinion -- it is
        a line the run ignores. `tester_type: gobgp` beside `mrt_injector:
        bgpdump2` played back through gobgp, against a 0.93 check-point factor
        instead of 0.99, and wrote a row that reads as a bgpdump2 run.
        """
        test = a_test(targets=[{'name': 'bird', 'tester_type': 'gobgp',
                                'mrt_injector': 'bgpdump2',
                                'mrt_file': '/x.mrt'}])
        with pytest.raises(SystemExit) as raised:
            bgperf2.check_batch_test(test)
        assert 'would never run' in str(raised.value)

    def test_an_injector_that_agrees_is_fine(self):
        bgperf2.check_batch_test(a_test(targets=[
            {'name': 'bird', 'tester_type': 'bgpdump2',
             'mrt_injector': 'bgpdump2', 'mrt_file': '/x.mrt'}]))

    @pytest.mark.parametrize('extra', [
        {'mrt_file': '/x.mrt'},
        {'mrt_injector': 'bgpdump2'},
        {'tester_type': 'gobgp', 'mrt_injector': 'bgpdump2'}])
    def test_a_scenario_target_is_exempt_from_the_generator_checks(self, extra):
        """It never reaches `gen_conf()`, so its generator is inert and the
        advice these checks print would not change what runs. The sibling
        mrt_file rule already exempts them; this one did not, so an `mrt_file`
        left on a scenario target as documentation failed the batch before the
        first container.
        """
        target = {'name': 'bird', 'file': 's.yaml'}
        target.update(extra)
        bgperf2.check_batch_test(a_test(targets=[target]))

    def test_a_scenario_target_takes_no_defaults(self):
        """`tester_type` is not inert on the `-f` path even though the
        generator is: `write_provenance()` records it as `run.tester_type`,
        `collect_provenance()` labels the tester role with it, and
        `bench_output_prefix()` puts it in the stem. Defaulting it wrote
        `"tester_type": "bird"` into the versions manifest of a run that played
        back an MRT file, and named its artifacts `bird_bird_...`. Provenance
        never guesses.
        """
        assert bgperf2.batch_target_field(
            {'name': 'bird', 'file': 's.yaml'}, 'tester_type') is None
        assert bgperf2.batch_target_field(
            {'name': 'bird', 'file': 's.yaml'}, 'filter_type') is None

    def test_a_target_without_a_scenario_still_takes_them(self):
        assert bgperf2.batch_target_field({'name': 'bird'}, 'tester_type') == 'bird'
        assert bgperf2.batch_target_field({'name': 'bird'}, 'filter_type') == 'in'

    def test_a_scenario_target_is_exempt_from_the_generator_validity_check(self):
        """Removing its default makes its tester `None`, which the validity
        check would otherwise refuse -- the exemption has to be uniform across
        all four generator checks or one of them contradicts the rest.
        """
        bgperf2.check_batch_test(a_test(targets=[
            {'name': 'bird', 'file': 's.yaml'}]))


class TestTheGeneratorMatchesTheWorkloadEverywhere:
    """The batch path refused MRT intent with a synthetic generator; `bench`
    and `config` accepted it and ran a synthetic table instead, silently.
    Fourteenth instance in this change set of a rule applied at one entry point
    and not another.
    """

    def cli_args(self, **overrides):
        args = Namespace(dir='/tmp', bench_name='x', docker_network_name=None,
                         file=None, target='bird', version=None, image=None,
                         repeat=True, neighbor_num=10, prefix_num=100,
                         prefix_scope='per-peer', tester_type='bird',
                         mrt_file=None, output='/dev/null')
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def test_bench_refuses_an_mrt_file_with_a_synthetic_generator(self):
        """`-t frr_c -n 10 -p 1050000 --mrt-file rib.mrt` with `-g bgpdump2`
        forgotten offers 10.5M synthetic routes against a check-point of
        `n * p * 0.99`, converges, and publishes a row that reads like the MRT
        run it is not.
        """
        with pytest.raises(SystemExit) as raised:
            bgperf2.bench(self.cli_args(mrt_file='/data/rib.mrt'))
        assert 'never reads it' in str(raised.value)

    def test_config_refuses_it_too(self):
        with pytest.raises(SystemExit):
            bgperf2.config(self.cli_args(mrt_file='/data/rib.mrt'))

    @pytest.mark.parametrize('tester', bgperf2.MRT_TESTER_TYPES)
    def test_an_mrt_generator_is_what_the_file_is_for(self, tester):
        bgperf2.check_generator_matches_workload(
            self.cli_args(tester_type=tester, mrt_file='/data/rib.mrt'))

    @pytest.mark.parametrize('tester', bgperf2.MRT_TESTER_TYPES)
    def test_an_mrt_generator_without_a_file_is_refused_before_teardown(
            self, tester):
        """The other direction, and it fails differently: loud but late.
        `gen_conf()` ends at a bare `exit(1)`, and by then `bench()` has run
        `remove_target_containers()`, `remove_old_containers()` and `rmtree()`
        over the config directory -- the previous run's containers and logs,
        kept deliberately so a failure can be investigated.
        """
        torn = []
        import unittest.mock as mock
        with mock.patch.object(bgperf2, 'remove_target_containers',
                               lambda: torn.append('teardown')):
            with pytest.raises(SystemExit) as raised:
                bgperf2.bench(self.cli_args(tester_type=tester))
        assert 'no --mrt-file' in str(raised.value)
        assert torn == [], 'containers were torn down before the refusal'

    def test_no_mrt_file_is_always_fine(self):
        bgperf2.check_generator_matches_workload(self.cli_args())

    def test_a_scenario_run_is_exempt(self):
        """`bench -f` reads the workload from the file, so nothing here
        applies -- the same exemption the batch guards make.
        """
        args = self.cli_args(file='scenario.yaml', mrt_file='/data/rib.mrt',
                             prefix_scope='per-peer')
        with pytest.raises(Exception) as raised:
            bgperf2.bench(args)
        assert 'never reads it' not in str(raised.value)

    def test_the_rule_is_one_function(self):
        assert bgperf2.mrt_keys_without_an_mrt_generator('bird', '/x.mrt') == \
            ['mrt_file']
        assert bgperf2.mrt_keys_without_an_mrt_generator(
            'bird', '/x.mrt', 'bgpdump2') == ['mrt_injector', 'mrt_file']
        assert bgperf2.mrt_keys_without_an_mrt_generator(
            'bgpdump2', '/x.mrt', 'bgpdump2') == []
