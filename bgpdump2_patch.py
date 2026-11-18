# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Opt-in, source-bound fix for bgpdump2 attribute-block prefix aliasing."""
import re
import shlex

PATCH = 'pa-exact-v1'
SUFFIX = '-' + PATCH
MARKER = '/root/bgperf-bgpdump2-patch'
OLD = '  bgp_path_node = ptree_search((char *)filtered_path, filtered_path_length * 8, peer_table[index].path_root);'
NEW = OLD.replace('ptree_search(', 'ptree_search_exact(')


def patched_ref(version):
    value = str(version or '')
    if not value.endswith(SUFFIX):
        return None
    revision = value[:-len(SUFFIX)]
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('bgpdump2 pa-exact-v1 requires a full lowercase 40-hex upstream commit')
    return revision


def patch_command():
    """Run from the upstream root; no inferred context or silent best effort."""
    path = 'src/bgpdump_data.c'
    # Escape GNU/POSIX basic-regexp metacharacters, leaving ordinary parentheses
    # literal. Python's re.escape would turn them into BRE capture groups.
    pattern = '^' + ''.join('\\'+c if c in r'\.^$[]*' else c for c in OLD) + '$'
    replacement = NEW.replace('\\', '\\\\').replace('&', r'\&').replace('|', r'\|')
    edit = 's|' + pattern + '|' + replacement + '|'
    return ('test "$(grep -Fxc ' + shlex.quote(OLD) + ' ' + path + ')" = 1'
            + ' && sed -i ' + shlex.quote(edit) + ' ' + path
            + ' && test "$(grep -Fxc ' + shlex.quote(NEW) + ' ' + path + ')" = 1'
            + ' && test "$(grep -Fxc ' + shlex.quote(OLD) + ' ' + path + ')" = 0')
