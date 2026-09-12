'''The index in CLAUDE.md, the invariant documents, and the hook that points at them.

CLAUDE.md's preamble is a story about a second copy of a document drifting from
the thing it described while looking right from the inside. Splitting the
invariants out of it reintroduces exactly that risk, so the parts are pinned
against each other here: a document nobody indexes is a rule nobody reads, an
index line naming a document that is gone is the AGENTS.md failure again, and a
guard that names a source file which no longer exists points an editor at
nothing.
'''
import json
import os
import re
import subprocess

import pytest

from conftest import REPO_ROOT

CLAUDE_MD = REPO_ROOT / 'CLAUDE.md'
INVARIANTS = REPO_ROOT / 'docs' / 'invariants'
SKILLS = REPO_ROOT / '.claude' / 'skills'
HOOK = REPO_ROOT / '.claude' / 'hooks' / 'invariants-guard.sh'
SETTINGS = REPO_ROOT / '.claude' / 'settings.json'

DOCS = sorted(p.name for p in INVARIANTS.glob('*.md'))


def claude_md():
    return CLAUDE_MD.read_text()


def test_there_are_invariant_documents():
    '''A green result over zero checks is the one outcome a caller must not trust.'''
    assert DOCS, 'docs/invariants/ is empty; the index below would pass vacuously'


@pytest.mark.parametrize('name', DOCS)
def test_every_invariant_document_is_indexed(name):
    assert f'docs/invariants/{name}' in claude_md(), (
        f'{name} is not named in CLAUDE.md, so nothing tells a reader it exists'
    )


@pytest.mark.parametrize('name', DOCS)
def test_every_invariant_document_says_what_it_governs(name):
    text = (INVARIANTS / name).read_text()
    assert text.startswith('# '), f'{name} has no title'
    assert '**Read this before editing:**' in text, (
        f'{name} does not name the sources it governs, so the hook has nothing to agree with'
    )


@pytest.mark.parametrize('name', DOCS)
def test_a_document_pointing_at_a_sibling_points_at_one_that_exists(name):
    """The split turned four "see the section below" into pointers to nothing.

    These documents were one file, so they referred to each other by position.
    A pointer that resolved before the move and silently resolves to nothing
    after it is the split's own version of a rule going missing.
    """
    text = (INVARIANTS / name).read_text()
    for ref in set(re.findall(r'docs/invariants/([A-Za-z0-9_-]+\.md)', text)):
        assert (INVARIANTS / ref).is_file(), f'{name} points at {ref}, which is not there'
    for dangling in ('section below', 'section above'):
        assert dangling not in text, (
            f'{name} says "{dangling}", which named a section of the file it was split out of'
        )


def test_every_indexed_document_exists():
    for ref in set(re.findall(r'docs/invariants/([A-Za-z0-9_-]+\.md)', claude_md())):
        assert (INVARIANTS / ref).is_file(), f'CLAUDE.md indexes {ref}, which is not there'


GOVERNS = '**Read this before editing:** '


def governed_modules(name):
    """Every `x.py` the document claims to govern.

    The whole paragraph, not its first line, and a name may carry a directory:
    `target-state.md` governs `scripts/check_timing_evidence.py`, and a pattern
    anchored on a leading backtick left that file -- the one encoding the timing
    campaign's Acceptance Rules -- governed by nothing, in the hook and in this
    function alike, so the test compared the blind spot against itself.

    Reading one line here while the
    hook also read one line meant the test compared a truncation against the
    same truncation and stayed green: wrapping the 365-character line in
    `provenance-and-verify.md` silently dropped 15 of the 17 modules it
    governs, and nothing said so.
    """
    paragraph, started = [], False
    for line in (INVARIANTS / name).read_text().splitlines():
        if line.startswith(GOVERNS):
            started = True
        if started:
            if not line.strip():
                break
            paragraph.append(line)
    return sorted(set(re.findall(r'`(?:[A-Za-z0-9_]+/)*([A-Za-z0-9_]+\.py)`', ' '.join(paragraph))))


def run_hook(payload):
    result = subprocess.run(
        ['sh', str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
        env={**os.environ, 'CLAUDE_PROJECT_DIR': str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return []
    ctx = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
    return re.findall(r'docs/invariants/[A-Za-z0-9_-]+\.md', ctx)



def run_hook_context(payload):
    result = subprocess.run(
        ['sh', str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
        env={**os.environ, 'CLAUDE_PROJECT_DIR': str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return ''
    return json.loads(result.stdout)['hookSpecificOutput']['additionalContext']

@pytest.mark.parametrize('name', DOCS)
def test_every_invariant_document_governs_modules_that_exist(name):
    """A guard pointing at a renamed module sends an editor to nothing."""
    modules = governed_modules(name)
    assert modules, f'{name} names no source file, so no edit can ever trigger it'
    for module in modules:
        hits = list(REPO_ROOT.glob(module)) + list(REPO_ROOT.glob(f'scripts/{module}'))
        assert hits, f'{name} claims to govern {module}, which does not exist'


@pytest.mark.parametrize('name', DOCS)
def test_the_hook_returns_every_document_that_claims_a_module(name):
    """The documents are the mapping; the hook must not hold a second opinion.

    The first version of the guard carried its own hardcoded table and had
    already drifted from three documents by the time it was reviewed: editing
    the export poll or `verify` was answered with three documents, none of them
    the one governing the edit, and `graphs.py`, `tester.py`, `openbgp.py` and
    `rustybgp.py` matched nothing at all. The suite was green, because it only
    checked that the names the hook already held pointed at files that exist.
    """
    for module in governed_modules(name):
        path = REPO_ROOT / module
        if not path.exists():
            path = REPO_ROOT / 'scripts' / module
        docs = run_hook({'tool_input': {'file_path': str(path)}})
        assert f'docs/invariants/{name}' in docs, (
            f'{name} says it governs {module}, but editing it points at {docs or "nothing"}'
        )


def test_the_hook_says_nothing_about_an_ungoverned_file():
    assert run_hook({'tool_input': {'file_path': str(REPO_ROOT / 'README.md')}}) == []


def test_the_hook_scans_a_shell_command_whether_or_not_it_looks_like_a_write():
    """An agent told to edit through the shell must not slip past the guard.

    Deciding "is this a write" in shell is a list of verbs, and the list missed
    `perl -i`, `awk -i inplace`, `truncate` and `dd of=`. The guard is advisory:
    a false positive costs one paragraph and a miss costs the pointer silently,
    so it over-fires on a read rather than keeping a list that will drift.
    """
    for command in (
        "sed -i 's/a/b/' convergence.py",
        'perl -i -pe s/a/b/ convergence.py',
        'truncate -s 0 convergence.py',
        'cat convergence.py',
        # A heredoc-fed script is the likeliest shell write there is -- it is what
        # this harness tells agents to use -- and stripping the leading token of
        # every *line* rather than of every `;&|` segment erased the filename off
        # the body's first line and went silent.
        'python3 - <<EOF\nopen("convergence.py", "w").write(x)\nEOF',
        'grep -n foo \\\n convergence.py',
        # The hidden newline is not `[[:space:]]`, so a first line holding no
        # space at all let the strip run through it and eat the body's start.
        'python3<<EOF\nopen("convergence.py", "w").write(x)\nEOF',
        'true\nconvergence.py --x',
    ):
        assert run_hook({'tool_input': {'command': command}}) == [
            'docs/invariants/convergence.md'
        ], command


def test_a_document_named_beside_an_edit_never_suppresses_the_guard():
    """Recording the reason in the document is the natural thing to do.

    Three separate compound commands slipped an exemption tested over the whole
    command string, each found by a later round of review than the last. The
    document path is stripped instead, so there is no exemption left to slip.
    """
    for command in (
        'sed -i s/a/b/ convergence.py && cat docs/invariants/convergence.md',
        'sed -i s/a/b/ convergence.py && cat >> docs/invariants/convergence.md <<EOF',
        'sed -i s/a/b/ convergence.py; echo hi > docs/invariants/convergence.md',
        'sed -i s/a/b/ convergence.py docs/invariants/convergence.md',
    ):
        assert run_hook({'tool_input': {'command': command}}) == [
            'docs/invariants/convergence.md'
        ], command


def test_editing_a_document_is_not_editing_what_it_governs():
    """The one unambiguous target there is, which is why it is the one exemption."""
    doc = REPO_ROOT / 'docs' / 'invariants' / 'convergence.md'
    assert run_hook({'tool_input': {'file_path': str(doc)}}) == []


def test_the_hook_is_registered_and_executable():
    assert os.access(HOOK, os.X_OK), 'the guard is not executable, so it silently never runs'
    settings = json.loads(SETTINGS.read_text())
    commands = [
        h['command']
        for entry in settings['hooks']['PreToolUse']
        for h in entry['hooks']
    ]
    assert any('invariants-guard.sh' in c for c in commands), (
        'the guard is not registered in .claude/settings.json. Note bd rewrites that file '
        'whole on drift and bd setup appends rather than reverts -- re-read it after either.'
    )


SKILL_DIRS = sorted(p.name for p in SKILLS.iterdir() if p.is_dir()) if SKILLS.is_dir() else []


@pytest.mark.parametrize('name', SKILL_DIRS)
def test_every_skill_declares_itself_and_is_indexed(name):
    text = (SKILLS / name / 'SKILL.md').read_text()
    assert re.search(rf'^name: {re.escape(name)}$', text, re.M), (
        f'{name}/SKILL.md declares a different name than its directory'
    )
    assert re.search(r'^description: \S', text, re.M), f'{name} has no description to trigger on'
    assert name in claude_md(), f'{name} is not named in CLAUDE.md, so nothing says it exists'


@pytest.mark.parametrize('name', SKILL_DIRS)
def test_every_operator_contract_keeps_its_trigger_phrase(name):
    '''The phrase is the whole interface: a contract nobody can say is unreachable.'''
    text = (SKILLS / name / 'SKILL.md').read_text()
    phrases = re.findall(r'When the user says `([^`]+)`', text)
    assert phrases, f'{name} states no trigger phrase'
    for phrase in phrases:
        assert phrase in text.split('---', 2)[1], (
            f'{name} triggers on "{phrase}" but its description does not mention it'
        )
        assert phrase in claude_md(), f'CLAUDE.md does not list the phrase "{phrase}"'


def test_a_governs_paragraph_may_be_rewrapped():
    """The line is prose and will be wrapped; wrapping must not narrow the guard.

    `provenance-and-verify.md` names 17 modules and is the document most likely
    to be reflowed. A per-line read left `rustybgp.py` -- the bug that document
    leads with -- governed by nothing at all.
    """
    widest = max(DOCS, key=lambda n: len(governed_modules(n)))
    assert len(governed_modules(widest)) > 3, 'no document names enough modules to test this'
    for module in governed_modules(widest):
        path = REPO_ROOT / module
        docs = run_hook({'tool_input': {'file_path': str(path)}})
        assert f'docs/invariants/{widest}' in docs, (
            f'{widest} governs {module} only on a line the guard did not read'
        )



def test_the_single_file_note_is_withheld_when_several_files_are_named():
    """The note says "this file", so it may not appear over a four-module edit."""
    one = run_hook_context({'tool_input': {'file_path': str(REPO_ROOT / 'bgperf2.py')}})
    assert 'This file is governed by most of them' in one
    for command in (
        'sed -i s/a/b/ convergence.py findings.py contention.py summary.py',
        # bgperf2.py absorbs every document on its own, so a version that counted
        # only the first name matching each one collapsed this back to a single
        # file and printed the note anyway.
        'sed -i s/a/b/ bgperf2.py frr.py',
    ):
        many = run_hook_context({'tool_input': {'command': command}})
        assert 'This file is governed by most of them' not in many, command


@pytest.mark.parametrize('name', SKILL_DIRS)
def test_every_document_a_skill_names_exists_at_the_path_it_names(name):
    """The plan documents are the entire payload of these contracts.

    They were repo-root-relative when this text lived in CLAUDE.md and came
    across verbatim, so as markdown links they pointed at
    `.claude/skills/<name>/docs/...`. Rewriting the hrefs to `../../../docs/...`
    fixed the reading from the skill directory and broke the one from the repo
    root, which is the cwd an agent runs `cat` in -- so the link syntax is gone
    and a backticked repo path is what is left, correct in both readings.
    """
    text = (SKILLS / name / 'SKILL.md').read_text()
    assert '](../' not in text, f'{name} carries a relative link that escapes the repo'
    # Not every contract drives a plan document -- `2026-benchmark-campaign`
    # drives a script -- so this checks the ones that do name one.
    referenced = set(re.findall(r'`(docs/[A-Za-z0-9_./-]+\.md)`', text))
    for ref in referenced:
        assert (REPO_ROOT / ref).is_file(), f'{name} names {ref}, which is not there'


def test_the_skills_between_them_drive_the_plan_documents():
    """Keeps the two checks above from passing over an empty set."""
    named = set()
    for name in SKILL_DIRS:
        named |= set(re.findall(r'`(docs/[A-Za-z0-9_./-]+\.md)`', (SKILLS / name / 'SKILL.md').read_text()))
    assert len(named) >= 3, f'only {named} named across every skill'


@pytest.mark.parametrize('name', SKILL_DIRS)
def test_the_plan_a_skill_drives_points_back_at_the_skill(name):
    """A pointer that resolved before the move and not after is a rule lost.

    `docs/unattended-execution-plan.md` said its continuation prompt "is now an
    operator contract in `CLAUDE.md` ... see the contract", and after the move a
    worker following that found only the index table. The plan documents are
    older than the skills, so nothing else pins the direction.
    """
    text = (SKILLS / name / 'SKILL.md').read_text()
    plans = [
        REPO_ROOT / ref for ref in re.findall(r'`(docs/[A-Za-z0-9_./-]+plan\.md)`', text)
    ]
    for plan in plans:
        body = plan.read_text()
        # Only a plan that says its contract *lives* in CLAUDE.md: an incidental
        # mention of the file is not a pointer at anything that moved.
        if not re.search(r'(contract|prompt)[^.]{0,80}in `CLAUDE\.md`', body):
            continue
        assert name in body, (
            f'{plan.name} refers to CLAUDE.md but never names the {name} skill that now '
            f'carries its contract'
        )


@pytest.mark.parametrize('name', SKILL_DIRS)
def test_every_skill_is_reachable_through_the_agents_directory(name):
    """Codex reads this repo through `AGENTS.md` and loads no `.claude/skills/`.

    The symlinks under `.agents/skills/` are the only thing that puts these
    contracts in front of it, and a fifth skill added without one would be lost
    for that reader in silence.
    """
    link = REPO_ROOT / '.agents' / 'skills' / name
    assert link.is_symlink(), f'{name} has no .agents/skills entry, so Codex cannot see it'
    assert link.resolve() == (SKILLS / name).resolve()


def test_a_module_named_with_a_directory_is_still_governed():
    """`target-state.md` governs `scripts/check_timing_evidence.py`."""
    path = REPO_ROOT / 'scripts' / 'check_timing_evidence.py'
    assert run_hook({'tool_input': {'file_path': str(path)}}) == ['docs/invariants/target-state.md']


def test_running_the_cli_is_not_editing_it():
    """`./bgperf2.py bench` is the most common command in this repo.

    It names the module governed by every document, so without dropping each
    segment's command word it carried the full advisory every time -- including
    once per cell of a multi-hour campaign.
    """
    for command in (
        './bgperf2.py bench -t bird -n 10 -p 1000',
        # the form the Setup section recommends: the script is the interpreter's
        # argument, so it is still being run rather than edited
        'venv/bin/python bgperf2.py bench -t bird -n 10 -p 1000',
        'venv/bin/python -m pytest tests/ -q',
    ):
        assert run_hook({'tool_input': {'command': command}}) == [], command
    # but the token after a non-interpreter is an argument, and dropping it
    # would be a miss
    assert run_hook({'tool_input': {'command': 'sed -i s/a/b/ bgperf2.py'}}) != []
    assert run_hook({'tool_input': {'command': 'cat bgperf2.py'}}) != []


def test_the_note_appears_only_when_every_document_applies():
    """"Most of them" must mean most of them.

    The note tells the reader to pick one document and skip the rest, so firing
    it at `bird.py`'s 4 of 9 invites skipping three that genuinely apply.
    """
    NOTE = 'This file is governed by most of them'
    assert NOTE in run_hook_context({'tool_input': {'file_path': str(REPO_ROOT / 'bgperf2.py')}})
    four = run_hook({'tool_input': {'file_path': str(REPO_ROOT / 'bird.py')}})
    assert 1 < len(four) < len(DOCS)
    assert NOTE not in run_hook_context({'tool_input': {'file_path': str(REPO_ROOT / 'bird.py')}})


RELOCATED = sorted(
    [INVARIANTS / n for n in DOCS] + [SKILLS / n / 'SKILL.md' for n in SKILL_DIRS]
)


@pytest.mark.parametrize('path', RELOCATED, ids=lambda p: p.parent.name + '/' + p.name)
def test_nothing_relocated_is_still_duplicated_in_claude_md(path):
    """The split moved text; it may never have copied it.

    CLAUDE.md's preamble is a story about a second copy drifting in silence, and
    the first cut of this very change set reintroduced one: the unattended
    contract's extraction over-ran its section boundary and carried the whole
    `### Code conventions` list -- seven rules CLAUDE.md still holds verbatim --
    into the skill, along with an unmatched `BEGIN BEADS INTEGRATION` marker.
    Nothing noticed, because a losslessness check only looks for text that went
    missing.

    The rule is every substantial line rather than a run of them: a first cut
    compared four-line windows, which a duplicate of three scattered bullets
    walks straight through. There is no overlap at all today, so the strict rule
    costs nothing and the loose one only looked safe.
    """
    def substantial(text):
        return {l.strip() for l in text.splitlines() if len(l.strip()) > 30}

    shared = sorted(substantial(path.read_text()) & substantial(claude_md()))
    assert not shared, (
        f'{path.name} repeats {len(shared)} line(s) CLAUDE.md still carries, '
        f'starting: {shared[0][:70]}'
    )


@pytest.mark.parametrize('name', DOCS)
def test_a_governs_paragraph_ends_at_a_blank_line(name):
    """The guard reads the paragraph, so the paragraph has to be one.

    Its scan stops at a blank line; a document without one would absorb the
    prose that follows and govern every module named in it. Bounding the scan
    alone would have reproduced the same blind spot in this test, so the
    structure is what is asserted.
    """
    lines = (INVARIANTS / name).read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(GOVERNS))
    tail = lines[start:start + 7]
    assert '' in tail, f'{name} governs paragraph runs past 6 lines with no blank line after it'


def test_a_glob_stands_for_every_governed_module():
    """`sed -i ... *.py` is the broadest shell edit there is and names nothing.

    Requiring a filename gave the widest edit the quietest answer, which is the
    direction this guard is not allowed to fail in.
    """
    assert run_hook({'tool_input': {'command': "sed -i 's/a/b/' *.py"}}) == [
        f'docs/invariants/{n}' for n in DOCS
    ]
    for quiet in ('ls *.pyc', 'rm convergence.pyc'):
        assert run_hook({'tool_input': {'command': quiet}}) == [], quiet


def test_the_monitors_own_poll_rules_govern_the_monitor():
    """`tester-offering.md` holds "both poll loops stamp the sample before the read".

    It named every generator and not `monitor.py`, so moving the timestamp in
    `Monitor.stats()` past its `docker exec` -- which biases
    `post_injection_tail_s`, the one interval whose sign is the finding -- was
    answered with two documents, neither holding the rule against it.
    """
    docs = run_hook({'tool_input': {'file_path': str(REPO_ROOT / 'monitor.py')}})
    assert 'docs/invariants/tester-offering.md' in docs


def test_no_module_a_document_discusses_is_governed_by_nobody():
    """Every check above runs document -> module; this is the other direction.

    It does not catch a rule filed in a document that governs the module only
    through a different one -- that is what the monitor case was, and it is not
    mechanisable -- but it does catch a module discussed by a document and
    governed by none.
    """
    governed, mentioned = set(), set()
    for name in DOCS:
        text = (INVARIANTS / name).read_text()
        governed |= set(governed_modules(name))
        mentioned |= set(re.findall(r'`(?:[A-Za-z0-9_]+/)*([A-Za-z0-9_]+\.py)`', text))
    real = {
        m for m in mentioned
        if (REPO_ROOT / m).is_file() or (REPO_ROOT / 'scripts' / m).is_file()
    }
    assert not (real - governed), f'discussed but governed by no document: {sorted(real - governed)}'
