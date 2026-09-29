#!/usr/bin/env python3
"""Check that a plan document and its beads epic say the same thing.

The plan document is the source of intent and evidence; each bead is a title,
a status and a pointer to a section of the plan (see `CLAUDE.md`, "Beads is
task tracking, and nothing else"). With the reasoning kept in one place, the
only thing left to drift is status, and that is what this checks:

    scripts/check_plan_beads.py docs/2026-daemon-comparison-plan.md

The plan declares its epic once and each tracked section declares its bead and
status on lines of their own:

    **Epic:** `bgperf2-0y5`

    ## 2. Phase 0 -- ...
    **Tracked by:** `bgperf2-0y5.1` · **Status:** done

A status is one of PLAN_STATUSES. Findings:

- a section's status disagrees with its bead's (the plan wins; fix the bead,
  or fix the plan if the plan is the one that is stale);
- a bead named by the plan that does not exist;
- a child of the epic that no section names -- work the plan does not know
  about, which is how the tracker starts to outrun the document;
- a bead whose description does not name the plan, or that is long enough to
  be carrying reasoning the plan should hold.

Exit 0 when aligned, 1 on any finding, 2 when `bd` could not be asked.
The comparison is pure (`check()`); only `main()` runs `bd`, so the test suite
covers it without a Dolt database.
"""

import json
import os
import re
import subprocess
import sys

# plan status -> the bead statuses that agree with it
PLAN_STATUSES = {
    'not started': {'open', 'blocked', 'deferred'},
    'in progress': {'in_progress'},
    'done': {'closed'},
    'not needed': {'closed'},
}

# A pointer and a sentence is ~100 characters; several paragraphs is prose
# that belongs in the plan.
MAX_DESCRIPTION = 400

EPIC_RE = re.compile(r'^\*\*Epic:\*\*\s*`([^`]+)`', re.M)
HEADING_RE = re.compile(r'^(#{2,3})\s+(.*)$', re.M)
TRACKED_RE = re.compile(
    r'^\*\*Tracked by:\*\*\s*`([^`]+)`\s*·\s*\*\*Status:\*\*\s*(.+?)\s*$', re.M)


def parse_plan(text):
    """(epic id, [(section heading, bead id, status)]) from a plan's text."""
    epic = EPIC_RE.search(text)
    headings = [(m.start(), m.group(2).strip()) for m in HEADING_RE.finditer(text)]
    sections = []
    for m in TRACKED_RE.finditer(text):
        heading = next((h for pos, h in reversed(headings) if pos < m.start()),
                       '(before any heading)')
        sections.append((heading, m.group(1), m.group(2).strip().lower()))
    return (epic.group(1) if epic else None), sections


def check(plan_path, epic, sections, beads):
    """Findings, as strings. `beads` is `bd list --json` output for the epic's
    children plus anything the plan names, keyed by id."""
    findings = []
    if not epic:
        findings.append('the plan declares no **Epic:** line')
    elif epic not in beads:
        # Its children list comes back empty rather than failing, so without
        # this a typo'd or deleted epic would check nothing and pass.
        findings.append('the epic {0} does not exist'.format(epic))
    if not sections:
        findings.append('the plan has no **Tracked by:** lines')
    named = set()
    for heading, bead_id, status in sections:
        named.add(bead_id)
        if status not in PLAN_STATUSES:
            findings.append('{0}: status {1!r} is not one of {2}'.format(
                heading, status, ', '.join(PLAN_STATUSES)))
            continue
        bead = beads.get(bead_id)
        if bead is None:
            findings.append('{0}: names {1}, which does not exist'.format(
                heading, bead_id))
            continue
        if bead['status'] not in PLAN_STATUSES[status]:
            findings.append('{0}: the plan says {1!r}, {2} is {3!r}'.format(
                heading, status, bead_id, bead['status']))
    for bead_id, bead in sorted(beads.items()):
        if bead.get('parent') == epic and bead_id not in named:
            findings.append('{0} ({1!r}) is a child of {2} that no section of the '
                            'plan names'.format(bead_id, bead.get('title'), epic))
    for bead_id in sorted(named | {epic} - {None}):
        bead = beads.get(bead_id)
        if bead is None:
            continue
        description = bead.get('description') or ''
        if plan_path not in description:
            findings.append('{0}: its description does not name {1}'.format(
                bead_id, plan_path))
        if len(description) > MAX_DESCRIPTION:
            findings.append('{0}: its description is {1} characters; reasoning '
                            'belongs in the plan'.format(bead_id, len(description)))
    return findings


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bd_json(*args):
    # bd finds its database from the cwd, so it runs in the repo whatever
    # directory this script was started from.
    out = subprocess.run(['bd', *args, '--json'], capture_output=True,
                         text=True, check=True, cwd=REPO_ROOT).stdout
    return json.loads(out or '[]')


def main(argv):
    if len(argv) != 2:
        sys.exit('usage: check_plan_beads.py docs/<plan>.md')
    plan_path = argv[1]
    with open(plan_path) as f:
        text = f.read()
    # Beads name the plan repo-relative, whatever cwd this is run from.
    absolute = os.path.abspath(plan_path)
    if absolute.startswith(REPO_ROOT + os.sep):
        plan_path = os.path.relpath(absolute, REPO_ROOT)
    epic, sections = parse_plan(text)
    try:
        beads = {}
        if epic:
            # --limit 0: bd's default of 50 would silently drop children.
            for b in bd_json('list', '--parent', epic, '--all', '--limit', '0'):
                beads[b['id']] = dict(b, parent=epic)
        for bead_id in {epic, *(s[1] for s in sections)} - {None} - set(beads):
            try:
                shown = bd_json('show', bead_id)
            except subprocess.CalledProcessError as e:
                # Only bd's own "not found" means the bead is missing, which
                # check() then names. Anything else -- a held Dolt lock, a
                # stopped server -- is bd failing, and must not send someone to
                # "fix" a bead that is fine.
                if 'no issue' in (e.stdout or '') + (e.stderr or ''):
                    continue
                raise
            if shown:
                beads[bead_id] = shown[0]
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        print('could not ask bd: {0}'.format(e), file=sys.stderr)
        return 2
    findings = check(plan_path, epic, sections, beads)
    for line in findings:
        print(line)
    if findings:
        print('\n{0} finding(s). The plan is the source; fix whichever side is '
              'stale.'.format(len(findings)))
        return 1
    print('{0}: {1} section(s) and epic {2} agree'.format(
        plan_path, len(sections), epic))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
