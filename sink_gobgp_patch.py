# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Source-bound private dependency copy; never edit the module cache."""
import json
from pathlib import PurePosixPath
import shlex

PROFILE = 'unknown-ec-v1'
SOURCE = '/go/pkg/mod/github.com/osrg/gobgp/v4@v4.9.0/pkg/packet/bgp/bgp.go'
SOURCE_SHA256 = '69789fbd3defea643e3c9012f428584a1b1cb049abc794ad1556a97fcdab2a63'
DESTINATION = '/tmp/bgperf-gobgp-unknown-ec-v1'
MODFILE = DESTINATION + '/go.mod'
OLD = '\treturn nil, NewMessageError(BGP_ERROR_UPDATE_MESSAGE_ERROR, BGP_ERROR_SUB_MALFORMED_ATTRIBUTE_LIST, nil, fmt.Sprintf("unknown evpn subtype: %d", subType))'
NEW = '\treturn NewUnknownExtended(EC_TYPE_EVPN, data[1:8]), nil'


def build_dependency_command(*, source=SOURCE, destination=DESTINATION, project='/src'):
    """Copy a verified pinned module, patch one statement, use a private modfile.

    Production runs go mod verify first. Paths can be overridden by modeled
    tests; all production paths are fixed inside the pinned toolchain image.
    """
    for path in (source, destination, project):
        if (not PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
                or any(c in path for c in ('\n','\r','\0'))):
            raise ValueError('Absolute normalized dependency paths required')
    if PurePosixPath(source).parts[-4:] != ('pkg','packet','bgp','bgp.go'):
        raise ValueError('Pinned GoBGP packet source path required')
    module = str(PurePosixPath(source).parents[3])
    copied_module = destination + '/gobgp'
    target = copied_module + '/pkg/packet/bgp/bgp.go'
    pattern = '^' + ''.join('\\'+c if c in r'\.^$[]*' else c for c in OLD) + '$'
    replacement = NEW.replace('\\', '\\\\').replace('&', r'\&').replace('|', r'\|')
    def checksum(path):
        return 'test "$(sha256sum '+shlex.quote(path)+' | cut -d " " -f 1)" = '+SOURCE_SHA256
    commands = [
        'test "$(grep -Fxc '+shlex.quote('\tgithub.com/osrg/gobgp/v4 v4.9.0')+' '+shlex.quote(project+'/go.mod')+')" = 1',
        '! grep -Eq '+shlex.quote(r'^[[:space:]]*replace[[:space:](]')+' '+shlex.quote(project+'/go.mod'),
        checksum(source),
        'test "$(grep -Fxc '+shlex.quote(OLD)+' '+shlex.quote(source)+')" = 1',
        'mkdir -m 700 '+shlex.quote(destination),
        'cp -a -- '+shlex.quote(module)+' '+shlex.quote(copied_module),
        'chmod -R u+w '+shlex.quote(copied_module),
        checksum(target),
        'sed -i '+shlex.quote('s|'+pattern+'|'+replacement+'|')+' '+shlex.quote(target),
        'test "$(grep -Fxc '+shlex.quote(NEW)+' '+shlex.quote(target)+')" = 1',
        'test "$(grep -Fxc '+shlex.quote(OLD)+' '+shlex.quote(target)+')" = 0',
        'cp -- '+shlex.quote(project+'/go.mod')+' '+shlex.quote(destination+'/go.mod'),
        'cp -- '+shlex.quote(project+'/go.sum')+' '+shlex.quote(destination+'/go.sum'),
        "printf '\\n%s\\n' "+shlex.quote('replace github.com/osrg/gobgp/v4 => '+json.dumps(copied_module))+' >> '+shlex.quote(destination+'/go.mod'),
    ]
    return ' && '.join(commands)
