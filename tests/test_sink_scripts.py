'''The two sink scripts' pure parts: no Docker, as the suite requires.

`scripts/sink_parity_check.py` drives the sink and a GoBGP monitor from one
speaker, and `scripts/sink_go_test.sh` runs the Go tests in the toolchain the
recipe pins. What can be checked without a container is the plan the first
follows and the rule it uses to call a step finished, and that the second
names no toolchain of its own.
'''
import importlib.util
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

PARITY = REPO_ROOT / 'scripts' / 'sink_parity_check.py'
GO_TEST = REPO_ROOT / 'scripts' / 'sink_go_test.sh'


def load_parity():
    spec = importlib.util.spec_from_file_location('sink_parity_check', PARITY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parity = load_parity()


def test_prefixes_are_distinct_and_outside_the_scratch_subnet():
    got = parity.parity_prefixes(600)
    assert len(set(got)) == 600
    assert got[0] == '10.100.0.0/24' and got[256] == '10.101.0.0/24'
    assert not any(p.startswith('10.99.') for p in got)
    with pytest.raises(ValueError):
        parity.parity_prefixes(parity.MAX_PREFIXES + 1)


def test_the_plan_expects_a_replacement_not_an_addition():
    assert parity.plan_steps(3000, 1000, 500) == [
        ('announce', 3000, 3000), ('withdraw', 1000, 2000),
        ('reannounce', 500, 2000)]
    assert parity.plan_steps(10, 0, 0) == [('announce', 10, 10)]
    with pytest.raises(ValueError):
        parity.plan_steps(10, 11, 0)
    with pytest.raises(ValueError):
        parity.plan_steps(10, 5, 6)


@pytest.mark.parametrize('expected,sink,gobgp,verdict', [
    (100, 100, 100, 'agree'),
    (100, 99, 100, 'disagree'),
    (100, 90, 90, 'short'),
])
def test_step_verdict(expected, sink, gobgp, verdict):
    assert parity.step_verdict(expected, sink, gobgp) == verdict


def test_agreement_alone_does_not_finish_a_step():
    '''A re-announcement leaves the count where it was, so both monitors
    agree before one replacement has arrived.'''
    assert not parity.settled('agree', 10, 10, quiet_s=5, settle_s=2)
    assert not parity.settled('agree', 10, 12, quiet_s=1, settle_s=2)
    assert parity.settled('agree', 10, 12, quiet_s=2, settle_s=2)
    assert not parity.settled('disagree', 10, 12, quiet_s=5, settle_s=2)


def test_help_needs_no_docker():
    out = subprocess.run([sys.executable, str(PARITY), '--help'],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and '--prefixes' in out.stdout


def test_the_go_test_script_names_no_toolchain_of_its_own():
    '''It reads the digest the recipe pins. A tag typed here would float, and
    the race run and the image build could use two compilers.'''
    code = '\n'.join(line for line in GO_TEST.read_text().splitlines()
                     if not line.lstrip().startswith('#'))
    assert 'BUILD_VARS["go_image"]' in code
    assert not re.search(r'golang:\d', code)
