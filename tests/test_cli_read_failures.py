'''What one bad CLI read is allowed to cost.

Three pre-existing defects of one shape, each found by review or by a campaign
block rather than by a test, and each costing more than the read it came from:

* a `docker exec` result that is not UTF-8 raised `UnicodeDecodeError` naming a
  byte offset into a buffer nobody kept, so the campaign's one real occurrence
  (openbgp 9.2, `bgpctl -j show neighbor`, 0x80 at position 13585) is still
  undiagnosed (`bgperf2-qhx`);
* `delivery_metrics()` ran unguarded inside the event artifact, so a raise
  there would have taken the whole document -- the only record a converged run
  happened, and the only account of a failed one (`bgperf2-wq2`);
* a monitor or receiver container that is gone during the establishment wait
  propagated a docker-py `APIError` out of `bench()` as a traceback instead of
  naming the session (`bgperf2-52e`).

None needs Docker to reproduce, which is why they are here now.
'''
import json

import pytest

from conftest import REPO_ROOT  # noqa: F401

import measurements as measurements_module
import monitor as monitor_module
import openbgp as openbgp_module
from base import CliDecodeError, decode_cli_output


BAD = b'{"neighbors": [{"descr": "\x80\xff"}]}'


class TestDecodingACliReadThatIsNotUtf8:

    def test_a_clean_read_is_returned_unchanged(self):
        assert decode_cli_output(b'{"a": 1}', 'c', 'cmd') == '{"a": 1}'

    def test_a_string_passes_through_so_stubs_and_streams_both_work(self):
        assert decode_cli_output('already text', 'c', 'cmd') == 'already text'

    def test_it_raises_rather_than_substituting_a_replacement_character(self):
        '''`errors="replace"` would hand json.loads() corrupted JSON.

        That turns a read that failed into a parse of something that never
        existed, which is the worse of the two failures and the reason the
        bead did not call it an obvious fix.
        '''
        with pytest.raises(CliDecodeError):
            decode_cli_output(BAD, 'c', 'cmd')
        # and the substitution it refuses really would have produced a parse:
        # json.loads() accepts the replaced text, so nothing downstream would
        # have noticed that the read was broken
        assert json.loads(BAD.decode('utf-8', 'replace'))['neighbors']

    def test_the_message_carries_what_the_next_occurrence_needs(self):
        with pytest.raises(CliDecodeError) as caught:
            decode_cli_output(BAD, 'bgperf_openbgp_target', 'bgpctl -j show neighbor')
        message = str(caught.value)
        assert 'bgperf_openbgp_target' in message, 'which container'
        assert 'bgpctl -j show neighbor' in message, 'which command'
        assert str(BAD.index(b'\x80')) in message, 'where in the buffer'
        assert str(len(BAD)) in message, 'how long the buffer was'
        # the offending byte and its neighbours, which is the whole point: the
        # offset alone is what the campaign already had and could not use
        assert '80 ff' in message, f'the bytes themselves: {message}'

    def test_the_original_error_is_chained_not_discarded(self):
        with pytest.raises(CliDecodeError) as caught:
            decode_cli_output(BAD, 'c', 'cmd')
        assert isinstance(caught.value.__cause__, UnicodeDecodeError)

    def test_a_short_buffer_does_not_index_out_of_range(self):
        with pytest.raises(CliDecodeError) as caught:
            decode_cli_output(b'\x80', 'c', 'cmd')
        assert '80' in str(caught.value)


class FakeOpenBGP(openbgp_module.OpenBGPTarget):
    '''Just enough target to drive the read: the payload is the subject.'''

    name = 'bgperf_openbgp_target'

    def __init__(self, payload):
        self._payload = payload

    def local(self, cmd, **kwargs):
        return self._payload


class TestTheReadThatActuallyFailedOnTheCampaignHost:

    def test_it_fails_as_a_diagnosable_error_not_a_bare_decode_error(self):
        with pytest.raises(CliDecodeError) as caught:
            FakeOpenBGP(BAD).get_neighbors_state()
        assert 'bgpctl' in str(caught.value)

    def test_a_good_read_still_parses(self):
        payload = json.dumps({'neighbors': [{
            'remote_addr': '10.10.0.2',
            'stats': {'prefixes': {'received': 7},
                      'update': {'received': {'eor': 1}}}}]}).encode()
        full, accepted = FakeOpenBGP(payload).get_neighbors_state()
        assert accepted == {'10.10.0.2': 7}
        assert full == {'10.10.0.2': True}


class TestTheArtifactOutlivesItsOwnDerivation:

    def samples(self):
        return [{'monotonic_s': 0.0, 'exported_to_monitor': 0,
                 'monitor_accepted': 0, 'witness_age_s': 0.0},
                {'monotonic_s': 1.0, 'exported_to_monitor': 10,
                 'monitor_accepted': 10, 'witness_age_s': 0.0}]

    def test_a_raising_delivery_costs_its_own_figure_and_nothing_else(self,
                                                                     monkeypatch):
        def explode(samples):
            raise TypeError("unsupported operand type(s) for +: 'int' and 'str'")

        monkeypatch.setattr(measurements_module, 'delivery_metrics', explode)
        section = measurements_module.target_table_section(self.samples())
        # the evidence survives: it is what the document is for
        assert section['samples'] == self.samples()
        assert section['series'], 'the per-series summary was lost with it'

    def test_the_reason_stays_a_token_and_the_detail_sits_beside_it(self,
                                                                    monkeypatch):
        '''`unresolved_reason` is a closed vocabulary, not a place for prose.

        `check_timing_evidence.py` reads any non-null reason as "the series
        cannot support an answer". A derivation that raised is a bug, not such
        a case, so putting an exception message in that field would make the
        two indistinguishable downstream.
        '''
        def explode(samples):
            raise TypeError('int and str')

        monkeypatch.setattr(measurements_module, 'delivery_metrics', explode)
        delivery = measurements_module.target_table_section(
            self.samples())['delivery']
        assert delivery['unresolved_reason'] == 'derivation_raised'
        assert delivery['unresolved_detail'] == 'TypeError: int and str'

    def test_the_detail_field_is_present_and_null_on_an_ordinary_path(self):
        delivery = measurements_module.target_table_section(
            self.samples())['delivery']
        assert 'unresolved_detail' in delivery
        assert delivery['unresolved_detail'] is None

    def test_the_new_reason_is_documented_where_a_reader_looks_it_up(self):
        '''The vocabulary test in test_delivery_metrics.py scans only
        `delivery_metrics()`'s own body, and this reason is raised from
        `target_table_section()`, so it would not be covered there.'''
        from conftest import REPO_ROOT
        dictionary = (REPO_ROOT / 'docs' / 'measurement-dictionary.md').read_text()
        assert '`derivation_raised`' in dictionary
        assert '`unresolved_detail`' in dictionary

    def test_every_delivery_field_is_still_present_and_null(self, monkeypatch):
        def explode(samples):
            raise ValueError('nope')

        monkeypatch.setattr(measurements_module, 'delivery_metrics', explode)
        good = measurements_module.target_table_section(self.samples())['delivery']
        monkeypatch.undo()
        shape = measurements_module.target_table_section(self.samples())['delivery']
        assert set(good) == set(shape), (
            'a section whose keys come and go cannot be read without knowing '
            'which branch produced it'
        )
        for field in measurements_module._DELIVERY_FIELDS:
            assert good[field] is None


class BrokenExec(monitor_module.Monitor):
    '''A container that is gone: `docker exec` answers with an APIError.'''

    def __init__(self, name):
        self.name = name

    def local(self, cmd, **kwargs):
        from docker.errors import APIError
        raise APIError(
            '409 Client Error: Conflict ("Container %s is not running")' % self.name)


class TestAnEstablishmentWaitOnAContainerThatIsGone:

    def test_it_names_the_session_instead_of_raising_a_docker_error(self):
        with pytest.raises(monitor_module.SessionUnavailable) as caught:
            BrokenExec('bgperf_receiver2').wait_established('10.10.0.2',
                                                            role='receiver2')
        message = str(caught.value)
        assert 'bgperf_receiver2' in message, 'which container'
        assert 'receiver2' in message, 'which role'
        assert 'not running' in message, "docker's own reason is kept"
        # and it claims nothing it did not measure: APIError covers every
        # non-2xx the daemon can answer with, including a 500 from a host out
        # of pids for a container that is running perfectly well
        assert 'is gone' not in message
        assert 'cannot be shown to be established' in message

    def test_it_does_not_wait_for_a_container_that_cannot_establish(self):
        '''Retrying is right for a bad answer and wrong for a failed exec.

        The JSONDecodeError arm treats an unparseable payload as "not
        established yet" and sleeps; a container that is gone will not
        establish a session however long the loop waits.
        '''
        import time
        started = time.monotonic()
        with pytest.raises(monitor_module.SessionUnavailable):
            BrokenExec('bgperf_monitor').wait_established('10.10.0.2')
        assert time.monotonic() - started < 0.5, 'it slept instead of dying'


class GarbledThenGood(monitor_module.Monitor):
    """gobgpd answers with binary before its RPC endpoint is up, then works."""

    name = 'bgperf_monitor'

    def __init__(self):
        self.reads = 0

    def local(self, cmd, **kwargs):
        self.reads += 1
        if self.reads < 3:
            return b'\x80\xff not json'
        return b'{"state": {"session_state": "established"}}'


class TestAGarbledAnswerIsNotYetEstablished:
    """The read runs about a second after the container starts, which is when
    the RPC endpoint is least likely to be up.  Decoding it ahead of the
    JSONDecodeError arm made an undecodable payload fatal, so the loop died on
    exactly the answer it exists to wait out."""

    def test_it_waits_the_payload_out_instead_of_ending_the_run(self):
        import contextlib
        import io
        mon = GarbledThenGood()
        with contextlib.redirect_stdout(io.StringIO()):
            waited = monitor_module.Monitor.wait_established(mon, '10.0.0.1')
        assert mon.reads == 3, 'it did not retry the undecodable answer'
        assert waited == 2


class TestTheInstrumentsOwnReadsAreCoveredToo:
    """The campaign's decode failure happened in a target sampler, but every
    published timing comes from the monitor's own per-second read, and that one
    was left bare -- recording `UnicodeDecodeError: ... position 13585`, an
    offset into a buffer that is gone, which is the defect being fixed."""

    def test_the_monitors_read_reports_the_bytes(self):
        import inspect
        source = inspect.getsource(monitor_module)
        assert ".decode('utf-8')" not in source, (
            'a bare decode is back in monitor.py; route it through '
            'decode_cli_output so the failure names the bytes'
        )

    def test_the_gobgp_targets_read_reports_the_bytes(self):
        import inspect
        import gobgp
        source = inspect.getsource(gobgp)
        assert "output.decode('utf-8')" not in source


class FakeOpenBGPEmpty(FakeOpenBGP):
    pass


class TestAnEmptyOpenbgpReadIsNotAnEmptyFleet:
    """`gobgp.py` names this failure already; polling can start before bgpd
    answers, and `json.loads('')` says "Expecting value: line 1 column 1",
    which names no container."""

    def test_it_is_named_rather_than_left_to_json(self):
        with pytest.raises(openbgp_module.OpenBGPNeighborReadError) as caught:
            FakeOpenBGPEmpty(b'').get_neighbors_state()
        message = str(caught.value)
        assert 'bgperf_openbgp_target' in message
        assert 'bgpctl' in message
