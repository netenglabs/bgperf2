# Copyright (C) 2026 bgperf2 contributors. Apache-2.0.
"""Explicit MRT workload binding; no acquisition, Docker or export-policy inference."""
import copy
import hashlib
import ipaddress
import os
from pathlib import Path
import stat
import struct
import time

import recipes

SCHEMA = 'bgperf2/mrt-recipe/v1alpha1'
SPEC_SCHEMA = 'bgperf2/mrt-workload/v1alpha1'
MAX_PREFIXES = 5_000_000


def selected(document):
    return isinstance(document, dict) and document.get('schema') == SCHEMA


def validate_spec(spec, resolved):
    recipes._keys(spec, ('schema', 'input', 'peers', 'target_asn', 'observer_asn',
                         'expected_prefixes', 'expectation_description'), where='mrt')
    recipes._same(spec['schema'], SPEC_SCHEMA, 'mrt.schema')
    source = spec['input']
    recipes._keys(source, ('path', 'bytes', 'sha256'), where='mrt.input')
    path = Path(recipes._text(source['path'], 'mrt.input.path'))
    if (not path.is_absolute() or str(path) != source['path'] or '..' in path.parts
            or '\x00' in str(path) or ':' in str(path)):
        raise recipes.ContractError('mrt.input.path: absolute normalized path required')
    recipes._integer(source['bytes'], 'mrt.input.bytes', 1)
    if source['bytes'] > 16 * 1024**3:
        raise recipes.ContractError('mrt.input.bytes: at most 16 GiB supported')
    recipes._match(source['sha256'], recipes._HEX64, 'mrt.input.sha256', 'SHA-256')
    for role in ('target_asn', 'observer_asn'):
        recipes._integer(spec[role], 'mrt.' + role, 1)
        if spec[role] >= 2**32:
            raise recipes.ContractError('mrt role ASN must fit four bytes')
    if spec['target_asn'] == spec['observer_asn']:
        raise recipes.ContractError('mrt role ASNs must differ')
    peers = spec['peers']
    if not isinstance(peers, list) or not 1 <= len(peers) <= 128:
        raise recipes.ContractError('mrt.peers: 1–128 ordered peers required')
    indexes = set()
    for peer in peers:
        recipes._keys(peer, ('index', 'asn', 'prefixes'), where='mrt.peer')
        for name in ('index', 'asn', 'prefixes'):
            recipes._integer(peer[name], 'mrt.peer.' + name, 0 if name == 'index' else 1)
        if peer['index'] >= 4096 or peer['index'] in indexes:
            raise recipes.ContractError('mrt peer indexes must be unique and below 4096')
        indexes.add(peer['index'])
        if peer['asn'] >= 2**32 or peer['asn'] in (spec['target_asn'], spec['observer_asn']):
            raise recipes.ContractError('mrt source ASN must fit four bytes and differ from role ASNs')
        if peer['prefixes'] > MAX_PREFIXES:
            raise recipes.ContractError('mrt peer prefix capacity exceeded')
    recipes._same(len(peers), resolved['neighbors'], 'mrt peer count')
    recipes._same(max(p['prefixes'] for p in peers), resolved['prefixes_per_peer'],
                  'mrt source topology prefix count')
    values = spec['expected_prefixes']
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_PREFIXES:
        raise recipes.ContractError('mrt expected set must contain 1–5000000 IPv4 prefixes')
    previous = None
    for value in values:
        if not isinstance(value, str) or len(value) > 18:
            raise recipes.ContractError('mrt expected prefix must be canonical IPv4 text')
        try:
            prefix = ipaddress.IPv4Network(value, strict=True)
        except ValueError as exc:
            raise recipes.ContractError('mrt expected prefix: ' + str(exc)) from exc
        if str(prefix) != value or (previous is not None and value <= previous):
            raise recipes.ContractError('mrt expected prefixes must be canonical, unique and lexically sorted')
        previous = value
    if len(values) > sum(p['prefixes'] for p in peers):
        raise recipes.ContractError('mrt expected set exceeds the declared offered entries')
    recipes._text(spec['expectation_description'], 'mrt.expectation_description')
    return spec


def bind(base, spec):
    """Bind an MRT workload to a validated synthetic *topology* source cell."""
    recipes.validate_recipe(base)
    if base['schema'] != recipes.RECIPE_SCHEMA:
        raise recipes.ContractError('MRT binding requires an unmodified synthetic topology recipe')
    if base['reproduction']['expected_outcome'] != 'experiment_completed':
        raise recipes.ContractError('MRT crash reproduction is unsupported')
    validate_spec(spec, base['resolved'])
    value = copy.deepcopy(base)
    value['schema'] = SCHEMA
    value['resolved']['target']['tester_type'] = 'bgpdump2'
    value['roles']['generator']['adapter'] = 'bgpdump2'
    value['inputs'] = [copy.deepcopy(spec['input'])]
    value['mrt'] = copy.deepcopy(spec)
    return value


def validate(document):
    recipes._keys(document, ('schema', 'engine', 'source', 'selection', 'legacy', 'resolved',
                            'roles', 'inputs', 'seeds', 'resources', 'completion',
                            'reproduction', 'mrt'))
    base = copy.deepcopy(document)
    spec = base.pop('mrt')
    base['schema'] = recipes.RECIPE_SCHEMA
    recipes._keys(base['roles'], ('target', 'generator', 'observer'), where='roles')
    recipes._keys(base['roles']['generator'], ('adapter', 'image'), where='roles.generator')
    recipes._same(base['roles']['generator']['adapter'], 'bgpdump2', 'MRT generator adapter')
    if (not isinstance(base['resolved'], dict)
            or not isinstance(base['resolved'].get('target'), dict)):
        raise recipes.ContractError('MRT resolved target must be an object')
    recipes._same(base['resolved']['target'].get('tester_type'), 'bgpdump2', 'MRT resolved tester type')
    base['resolved']['target']['tester_type'] = 'bird'
    base['roles']['generator']['adapter'] = 'bird'
    base['inputs'] = []
    recipes.validate_recipe(base)
    recipes._same(document, bind(base, spec), 'MRT recipe')
    return document


def verify_input(document, *, timeout_seconds=120, clock=time.monotonic):
    """Whole-file read outside measurement; size/hash and path/fd identity checked."""
    source = document['mrt']['input']
    path = Path(source['path'])
    if path.resolve(strict=True) != path:
        raise recipes.ContractError('Canonical MRT input without symlinks required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    started = clock()
    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != source['bytes']:
            raise recipes.ContractError('Regular MRT file with expected size required')
        from mrt_inventory import MAX_RECORD_BYTES, peer_table
        header = stream.read(12)
        if len(header) != 12:
            raise recipes.ContractError('Truncated MRT peer-table header')
        _, kind, subtype, length = struct.unpack('!IHHI', header)
        if kind != 13 or subtype != 1 or not 0 < length <= MAX_RECORD_BYTES:
            raise recipes.ContractError('MRT input must begin with a bounded peer table')
        body = stream.read(length)
        if len(body) != length:
            raise recipes.ContractError('Truncated MRT peer table')
        _, _, peers = peer_table(body)
        for peer in document['mrt']['peers']:
            if peer['index'] >= len(peers) or peers[peer['index']]['asn'] != peer['asn']:
                raise recipes.ContractError('MRT selected peer index/ASN does not match the consumed input')
        digest = hashlib.sha256(header + body)
        consumed = len(header) + len(body)
        while True:
            if clock()-started >= timeout_seconds:
                raise recipes.ContractError('MRT identity verification deadline expired')
            block = stream.read(1024 * 1024)
            if not block:
                break
            consumed += len(block)
            if consumed > source['bytes']:
                raise recipes.ContractError('MRT input grew during verification')
            digest.update(block)
        if (consumed != source['bytes'] or digest.hexdigest() != source['sha256']
                or identity(before) != identity(os.fstat(stream.fileno()))
                or identity(before) != identity(path.stat(follow_symlinks=False))):
            raise recipes.ContractError('MRT input identity mismatch or mutation')
    return {'input': copy.deepcopy(source), 'status': 'verified',
            'elapsed_seconds': clock()-started, 'method': 'complete buffered SHA-256 read'}


def scenario(text, document, render):
    """Modify only the scoped generated topology; no dynamic source-peer choice."""
    import yaml
    value = render(text)
    spec = document['mrt']
    value['target']['as'] = spec['target_asn']
    value['monitor']['as'] = spec['observer_asn']
    value['monitor']['check-points'] = [max(1, int(len(spec['expected_prefixes']) * .99))]
    for ordinal, (tester, peer) in enumerate(zip(value['testers'], spec['peers'], strict=True)):
        tester['bgpdump-index'] = peer['index']
        tester['mrt-index'] = ordinal
        neighbor = next(iter(tester['neighbors'].values()))
        neighbor['as'] = peer['asn']
        neighbor['mrt-file'] = spec['input']['path']
        neighbor['count'] = peer['prefixes']
        neighbor['check-points'] = peer['prefixes']
    return yaml.safe_dump(value, sort_keys=False)


def generated_scenario(engine, args, document):
    # Legacy gen_conf returns Mako+YAML. Never pass the untrusted input path
    # through that renderer. Insert it only after rendering an inert placeholder;
    # the scoped lifecycle must then parse the result as plain safe YAML.
    safe_args = copy.copy(args)
    safe_args.mrt_file = '/root/recipe-mrt-input'
    return scenario(engine.gen_conf(safe_args), document, engine.render_scenario)


def adapter(base, document):
    """Retain bgpdump2 polling/version behavior; fix mapping and full IPv4 command."""
    import shlex
    spec = document['mrt']
    mapping = {peer['index']: peer['asn'] for peer in spec['peers']}
    class FixedMRT(base):
        def get_index_valid(self, prefix_count):
            return [peer['index'] for peer in spec['peers']]

        def get_index_asns(self):
            return mapping.copy()

        def get_host_config(self):
            config = super().get_host_config()
            expected = spec['input']['path'] + ':/root/mrt_file'
            if config.get('Binds', []).count(expected) != 1:
                raise recipes.ContractError('Unexpected MRT bind; refusing writable or alternate input')
            config['Binds'] = [bind + ':ro' if bind == expected else bind for bind in config['Binds']]
            return config

        def get_startup_cmd(self):
            index = self.conf['bgpdump-index']
            neighbor = next(iter(self.conf['neighbors'].values()))
            command = ['stdbuf', '-oL', '-eL', '/usr/local/sbin/bgpdump2', '-4',
                       '--blaster', self.target_ip, '-p', str(index), '-a', str(mapping[index]),
                       '/root/mrt_file', '-T', '0', '-S', neighbor['local-address']]
            return ('#!/bin/bash\nulimit -n 65536\n' + shlex.join(command) + ' > '
                    + shlex.quote(self.guest_dir + '/' + self.LOG_NAME) + ' 2>&1 &\n')
    return FixedMRT
