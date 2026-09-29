"""`scripts/check_plan_beads.py`: the plan and its beads agree on status.

Only the pure half is tested -- `main()` runs `bd`, which needs a Dolt
database this suite deliberately does without.
"""
import importlib.util

import pytest

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    'check_plan_beads', REPO_ROOT / 'scripts' / 'check_plan_beads.py')
cpb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpb)

PLAN = 'docs/x-plan.md'
TEXT = """# X plan

**Epic:** `e-1`

## 1. Phase 0 -- land it

**Tracked by:** `e-1.1` · **Status:** done

## 2. Phase 1 -- next

**Tracked by:** `e-1.2` · **Status:** not started
"""


def bead(status, parent='e-1', description='See ' + PLAN + ' §1.'):
    return {'status': status, 'parent': parent, 'title': 't',
            'description': description}


def beads(**over):
    b = {'e-1': bead('open', parent=None), 'e-1.1': bead('closed'),
         'e-1.2': bead('open')}
    b.update(over)
    return b


def run(b, text=TEXT):
    epic, sections = cpb.parse_plan(text)
    return cpb.check(PLAN, epic, sections, b)


def test_the_plan_is_parsed_with_its_headings():
    epic, sections = cpb.parse_plan(TEXT)
    assert epic == 'e-1'
    assert sections == [('1. Phase 0 -- land it', 'e-1.1', 'done'),
                        ('2. Phase 1 -- next', 'e-1.2', 'not started')]


def test_agreement_is_silent():
    assert run(beads()) == []


@pytest.mark.parametrize('status', ['open', 'in_progress'])
def test_a_done_phase_with_an_open_bead_is_named(status):
    [finding] = run(beads(**{'e-1.1': bead(status)}))
    assert 'Phase 0' in finding and 'e-1.1' in finding and status in finding


def test_a_closed_bead_under_a_phase_not_started_is_named():
    [finding] = run(beads(**{'e-1.2': bead('closed')}))
    assert 'not started' in finding


def test_a_child_no_section_names_is_named():
    [finding] = run(beads(**{'e-1.3': bead('open')}))
    assert 'e-1.3' in finding and 'no section' in finding


def test_a_missing_bead_is_named():
    b = beads()
    del b['e-1.2']
    [finding] = run(b)
    assert 'does not exist' in finding


def test_an_unknown_status_word_is_named():
    [finding] = run(beads(), TEXT.replace('not started', 'nearly'))
    assert 'nearly' in finding


def test_a_bead_that_does_not_point_at_the_plan_is_named():
    [finding] = run(beads(**{'e-1.2': bead('open', description='do the thing')}))
    assert PLAN in finding


def test_a_bead_carrying_reasoning_is_named():
    long = 'See ' + PLAN + '. ' + 'because ' * 60
    [finding] = run(beads(**{'e-1.2': bead('open', description=long)}))
    assert 'reasoning' in finding


def test_the_real_plan_parses():
    """The one plan that uses the format must keep parsing."""
    text = (REPO_ROOT / 'docs' / '2026-daemon-comparison-plan.md').read_text()
    epic, sections = cpb.parse_plan(text)
    assert epic and len(sections) >= 5
    assert all(s in cpb.PLAN_STATUSES for _, _, s in sections)


def test_an_epic_that_does_not_exist_is_named():
    """bd lists no children for a missing epic and exits 0, so this is the
    only thing that stops a typo'd Epic line from passing."""
    b = beads()
    del b['e-1']
    assert any('epic e-1 does not exist' in f for f in run(b))
