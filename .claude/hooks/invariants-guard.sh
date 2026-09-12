#!/bin/sh
# PreToolUse guard: when a file governed by docs/invariants/*.md is about to be
# edited, name the document that governs it.
#
# CLAUDE.md's preamble is a story about a second copy of a mapping drifting from
# the thing it described while looking right from the inside, so this script
# holds no mapping of its own. Each document states what it governs on its
# `**Read this before editing:**` paragraph, and that paragraph is the mapping --
# a document that starts governing another module says so in one place, and the
# guard follows without being edited. A hardcoded table here was the first
# version and review found it had already drifted from three documents.
#
# Two rules the next three rounds of review settled, both of the same shape --
# a rule written against the case in front of it rather than against the claim:
#
#   * A document path in the command is *stripped*, never treated as an
#     exemption. Exempting a command that mentioned one meant "edit the module,
#     record the reason in its invariant document" -- the most natural thing an
#     agent following this guard's advice does -- returned nothing. Three
#     separate compound commands slipped that exemption before it was replaced;
#     a per-segment version would have been a fourth list to get wrong.
#   * The command is scanned whether or not it looks like a write. Deciding that
#     in shell means a list of verbs (`sed -i`, `>`, `tee`, `patch`, `cp`...),
#     and the list missed `perl -i`, `awk -i inplace`, `truncate` and `dd of=`.
#     The guard is advisory: a false positive costs one paragraph, a miss costs
#     the pointer entirely and costs it silently. So it over-fires on purpose,
#     including on a shell command that only reads one of these files.

json=$(cat)
f=$(printf '%s' "$json" | jq -r '.tool_input.file_path // ""')
c=$(printf '%s' "$json" | jq -r '.tool_input.command // ""')

# Editing a document *is* writing the document, not what it governs. This is the
# one unambiguous target there is, which is why it is the only exemption.
case "$f" in *docs/invariants/*) exit 0 ;; esac

# The command word of each segment is what is being *run*, not edited, so it is
# dropped: `./bgperf2.py bench -t bird` is the most common command in this repo
# and would otherwise carry the whole advisory every time. Segments are split on
# `;&|` the way .claude/settings.json's own git guard splits them. A script named
# as an interpreter's argument (`venv/bin/python bgperf2.py bench`, the form the
# Setup section recommends) is being run too, so it goes with the command word --
# but only directly after something named `python*`, since the token after `cat`
# is an argument and dropping it would be a miss.
# Newlines are hidden first, so that a `;&|` split yields segments and a heredoc
# body is not mistaken for one. Stripping the leading token of every *line* was
# the first version, and it erased a governed filename that began a continuation
# or a heredoc line -- `python3 - <<EOF` writing a file is the likeliest shell
# write there is, and it went silent. The token class has to exclude the hidden
# newline too: it is not `[[:space:]]`, so the strip ran straight through it and
# ate the start of the body whenever the first line held no space at all
# (`python3<<EOF`), which is the same miss one character further along.
NL=$(printf '\001')
SEG=$(printf '\002')
cmd=$(printf '%s' "$c" \
  | tr '\n' '\001' \
  | sed -E "s/(\|\||&&|[;&|])/$SEG/g" \
  | tr '\002' '\n' \
  | sed -E "s|^([[:space:]]*[^[:space:]$NL]*python[0-9.]*)[[:space:]]+[^[:space:]$NL-][^[:space:]$NL]*\.py|\1|" \
  | sed -E "s/^[[:space:]]*[^[:space:]$NL]+//" \
  | tr '\001' '\n')
blob=$(printf '%s\n%s' "$f" "$cmd" | sed 's|docs/invariants/[A-Za-z0-9_.-]*||g')
[ -n "$(printf '%s' "$blob" | tr -d '[:space:]')" ] || exit 0

root=${CLAUDE_PROJECT_DIR:-}
[ -n "$root" ] || root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
[ -d "$root/docs/invariants" ] || exit 0

names=$(printf '%s' "$blob" | grep -oE '[A-Za-z0-9_]+\.py([^A-Za-z0-9_]|$)' | sed 's/[^A-Za-z0-9_.].*$//' | sort -u)

# `sed -i ... *.py` is the natural way to edit the repo at once and names no
# module at all, so requiring a name meant the broadest edit there is got the
# quietest answer. A glob stands for every governed module.
if printf '%s' "$blob" | grep -qE '(^|[^A-Za-z0-9_/])[*?][A-Za-z0-9_*?]*\.py([^A-Za-z0-9_]|$)'; then
  glob=1
else
  glob=0
fi
[ -n "$names" ] || [ "$glob" -eq 1 ] || exit 0

docs=""
ndocs=0
matched_names=""
for doc in "$root"/docs/invariants/*.md; do
  [ -f "$doc" ] || continue
  # The whole paragraph, not its first line: one governs line is long enough to
  # be rewrapped, and a per-line read would then silently govern only the
  # modules before the break.
  governs=$(awk '/^\*\*Read this before editing:\*\* /{f=1} f{if ($0 == "" || ++n > 6) exit; print}' "$doc")
  [ -n "$governs" ] || continue
  hit=0
  if [ "$glob" -eq 1 ]; then
    hit=1
  fi
  for name in $names; do
    # A trailing backtick after either a backtick or a directory: the governs
    # paragraphs name `scripts/check_timing_evidence.py`, and requiring a leading
    # backtick left the file encoding the campaign's Acceptance Rules governed by
    # nothing -- the same blind spot as the first version's hardcoded table, and
    # the test shared it because it extracted names with the same pattern.
    case "$governs" in
      *"\`$name\`"*|*"/$name\`"*)
        hit=1
        # Every matching name, not just the first: breaking here let one broad
        # module absorb a document and collapse the count below to 1.
        case " $matched_names " in *" $name "*) ;; *) matched_names="$matched_names $name" ;; esac
        ;;
    esac
  done
  if [ "$hit" -eq 1 ]; then
    docs="$docs docs/invariants/$(basename "$doc")"
    ndocs=$((ndocs + 1))
  fi
done
[ -n "$docs" ] || exit 0
docs=$(printf '%s' "$docs" | sed 's/^ //')

# bgperf2.py is the controller and is genuinely governed by nearly all of them,
# so a long list is the honest answer rather than a mapping that quietly picks.
# The wording is about one file, so it is used only when one file matched.
# "Most of them" must mean most of them: `bird.py` matches 4 of 9, and telling
# its editor to pick one of the four invites skipping three that apply.
# Only documents with a governs paragraph: one without can never contribute to
# ndocs, so counting it would make the comparison permanently false.
ntotal=$(grep -l "^\*\*Read this before editing:\*\* " "$root"/docs/invariants/*.md 2>/dev/null | wc -l)
nmatched=$(printf '%s' "$matched_names" | wc -w)
if [ "$ndocs" -eq "$ntotal" ] && [ "$ntotal" -gt 3 ] && [ "$nmatched" -eq 1 ]; then
  tail=" This file is governed by most of them, so read the one covering the area you are changing."
else
  tail=""
fi

jq -nc --arg p "$docs" --arg t "$tail" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:("The invariants governing this file are in: " + $p + "." + $t + " They were moved out of CLAUDE.md to keep it loadable, and every rule in them exists because the obvious alternative was tried and published a wrong number quietly. Read the relevant one before changing behaviour here; a comment, rename or test-only edit needs nothing.")}}'
