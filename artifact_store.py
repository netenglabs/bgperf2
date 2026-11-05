"""Local immutable evidence objects and reference packages. No runtime imports.

Catalogs map logical names to objects; original result checksums remain
authoritative. Registrations are permanent roots until an explicit future
retention policy releases them. GC never expires retained evidence.
"""
import argparse
from compression import zstd
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import sys

CATALOG = '.artifact-store.json'
SCHEMA = 'bgperf2/artifact-store/v1'
MINIMUM = 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')


class StorageError(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def safe_absolute(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise StorageError('Use an absolute path without symlink components: ' + str(path))
    return path


def relative_name(name):
    if not isinstance(name, str) or not name or '\x00' in name:
        raise StorageError('Invalid artifact name')
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != name or name == '.':
        raise StorageError('Unsafe artifact name: ' + name)
    return name


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def make_directory(path):
    path = safe_absolute(path)
    if not path.exists():
        make_directory(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            if not path.is_dir() or path.is_symlink():
                raise StorageError('Unsafe directory publication')
        fsync_dir(path.parent)


def sync_tree(root):
    root = safe_absolute(root)
    directories = [root]
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = safe_absolute(directory)
        directories.extend(safe_absolute(base / name) for name in dirs)
        for name in files:
            path = safe_absolute(base / name)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise StorageError('Nonregular result metadata')
                os.fsync(fd)
            finally:
                os.close(fd)
    for path in reversed(directories):
        fsync_dir(path)
    fsync_dir(root.parent)


def publish(path, data):
    """Create a durable immutable file; an interrupted publication is unrooted."""
    make_directory(path.parent)
    fd, pending = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path)  # no overwrite, including concurrent publication
        fsync_dir(path.parent)
    finally:
        os.unlink(pending)


def load_catalog(root):
    root = Path(root)
    path = root / CATALOG
    if not os.path.lexists(path):
        return None
    root = safe_absolute(root)
    if not path.is_file() or path.is_symlink():
        raise StorageError('Unsafe artifact catalog')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise StorageError('Duplicate catalog key')
            value[key] = item
        return value
    try:
        data = json.loads(path.read_text(), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as exc:
        raise StorageError('Malformed artifact catalog') from exc
    if (not isinstance(data, dict) or set(data) != {'schema', 'store', 'files'}
            or data['schema'] != SCHEMA or not isinstance(data['files'], dict)):
        raise StorageError('Unsupported artifact catalog')
    if not isinstance(data['store'], str) or not Path(data['store']).is_absolute() or '..' in Path(data['store']).parts:
        raise StorageError('Invalid store binding')
    for name, ref in data['files'].items():
        relative_name(name)
        if name == CATALOG:
            raise StorageError('Recursive artifact catalog')
        validate_ref(ref)
    return data


def validate_ref(ref):
    if (not isinstance(ref, dict) or set(ref) != {'sha256', 'size', 'codec'}
            or not isinstance(ref['sha256'], str) or not HEX.fullmatch(ref['sha256'])
            or type(ref['size']) is not int or ref['size'] < 0 or ref['codec'] != 'zstd'):
        raise StorageError('Invalid object reference')


def configured_store():
    value = os.environ.get('BGPERF_ARTIFACT_STORE')
    if not value:
        return None
    store = Store(value)
    engine = Path(__file__).resolve().parent
    if store.root == engine or engine in store.root.parents:
        raise StorageError('Store must be outside the engine checkout')
    return store


def validate_destinations(*destinations):
    store = configured_store()
    if store:
        for destination in destinations:
            path = safe_absolute(Path(destination).absolute())
            if path == store.root or path in store.root.parents or store.root in path.parents:
                raise StorageError('Artifact store and attempt roots must be nonnested')
    return store


def check_location(root):
    from contention import filesystem_type, is_memory_backed
    root = safe_absolute(root)
    ancestor = root
    while not os.path.lexists(ancestor):
        ancestor = ancestor.parent
    if not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
        raise StorageError('Store ancestor must be writable and searchable')
    mounts = Path('/proc/mounts').read_text()
    fs_type = filesystem_type(str(ancestor), mounts)
    if fs_type is None or is_memory_backed(str(ancestor), mounts):
        raise StorageError('Store requires identified disk-backed storage')
    stats = os.statvfs(ancestor)
    return {'schema': SCHEMA, 'path': str(root), 'filesystem_type': fs_type,
            'available_bytes': stats.f_bavail * stats.f_frsize, 'directories_created': False}


class _Reader(io.RawIOBase):
    def __init__(self, source, ref):
        self.source, self.ref = source, ref
        self.digest, self.count, self.verified = hashlib.sha256(), 0, False

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.source.read(len(buffer))
        if data:
            self.digest.update(data)
            self.count += len(data)
            if self.count > self.ref['size']:
                raise StorageError('Object exceeds declared size')
            buffer[:len(data)] = data
        elif not self.verified:
            if self.count != self.ref['size'] or self.digest.hexdigest() != self.ref['sha256']:
                raise StorageError('Object checksum or size mismatch')
            self.verified = True
        return len(data)


class Store:
    def __init__(self, root):
        self.root = safe_absolute(root)

    @contextmanager
    def locked(self):
        make_directory(self.root)
        safe_absolute(self.root)
        fd = os.open(self.root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            for name in ('objects', 'roots', 'staging'):
                make_directory(self.root / name)
            yield fd
        finally:
            os.close(fd)

    def object_path(self, ref):
        validate_ref(ref)
        sha = ref['sha256']
        return safe_absolute(self.root / 'objects' / sha[:2] / (sha + '.zst'))

    @contextmanager
    def open(self, ref):
        path = self.object_path(ref)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise StorageError('Object must be a regular file')
            try:
                with zstd.ZstdFile(source, 'rb') as expanded:
                    reader = io.BufferedReader(_Reader(expanded, ref))
                    try:
                        yield reader
                        while reader.read(1024 * 1024):
                            pass  # verify even when a caller reads just a prefix
                    finally:
                        reader.close()
            except (EOFError, zstd.ZstdError) as exc:
                raise StorageError('Unreadable compressed object: ' + str(path)) from exc

    def _put(self, source):
        try:
            before = os.fstat(source.fileno())
        except (AttributeError, io.UnsupportedOperation):
            before = None
        fd, pending = tempfile.mkstemp(dir=self.root / 'staging', prefix='.pending-')
        sha, size = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, 'wb') as target:
                with zstd.ZstdFile(target, 'wb', level=3) as compressed:
                    while block := source.read(1024 * 1024):
                        sha.update(block)
                        size += len(block)
                        compressed.write(block)
                target.flush()
                os.fsync(target.fileno())
            if before is not None:
                after = os.fstat(source.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise StorageError('Source changed while storing evidence')
            ref = {'sha256': sha.hexdigest(), 'size': size, 'codec': 'zstd'}
            path = self.object_path(ref)
            path.parent.mkdir(exist_ok=True, mode=0o700)
            if path.exists():
                with self.open(ref):
                    pass
            else:
                os.link(pending, path)
                fsync_dir(path.parent)
                fsync_dir(self.root / 'objects')
            return ref
        finally:
            os.unlink(pending)

    def put(self, source):
        with self.locked():
            return self._put(source)

    def _catalog(self, package, files):
        data = {'schema': SCHEMA, 'store': str(self.root), 'files': files}
        record = {'schema': SCHEMA, 'package': str(safe_absolute(package)), 'catalog': data}
        raw = canonical(record)
        root = self.root / 'roots' / (hashlib.sha256(raw).hexdigest() + '.json')
        if not root.exists():
            publish(root, raw)
        # Register before exposing the package. A crash can retain extra evidence,
        # but cannot expose a reference whose object is collectible.
        publish(package / CATALOG, canonical(data))
        return data

    def maintain(self, *, apply=False, grace_seconds=86400):
        if grace_seconds < 3600:
            raise StorageError('GC grace must be at least one hour')
        with self.locked():
            roots, reachable, references = [], set(), {}
            for path in sorted((self.root / 'roots').glob('*.json')):
                if path.is_symlink() or not path.is_file():
                    raise StorageError('Symlink root record')
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != path.stem:
                    raise StorageError('Corrupt root record')
                record = json.loads(raw)
                if (not isinstance(record, dict) or set(record) != {'schema', 'package', 'catalog'}
                        or record['schema'] != SCHEMA or not isinstance(record['package'], str)
                        or not Path(record['package']).is_absolute() or '..' in Path(record['package']).parts
                        or not isinstance(record['catalog'], dict)
                        or set(record['catalog']) != {'schema', 'store', 'files'}
                        or record['catalog']['schema'] != SCHEMA or record['catalog']['store'] != str(self.root)
                        or not isinstance(record['catalog']['files'], dict)):
                    raise StorageError('Invalid root record')
                for name, ref in record['catalog']['files'].items():
                    relative_name(name)
                    validate_ref(ref)
                    reachable.add(ref['sha256'])
                    if ref['sha256'] in references and references[ref['sha256']] != ref:
                        raise StorageError('Conflicting object declarations')
                    references[ref['sha256']] = ref
                roots.append(record)
            objects, garbage = [], []
            for path in sorted((self.root / 'objects').glob('*/*.zst')):
                safe_absolute(path)
                sha = path.name.removesuffix('.zst')
                if not HEX.fullmatch(sha) or path.parent.name != sha[:2] or not path.is_file():
                    raise StorageError('Invalid object path')
                objects.append((sha, path.stat().st_size))
                if sha not in reachable and time.time() - path.stat().st_mtime >= grace_seconds:
                    garbage.append(path)
            if reachable - {sha for sha, size in objects}:
                raise StorageError('Referenced objects missing; GC refused')
            for ref in references.values():
                with self.open(ref):
                    pass
            report = {'schema': SCHEMA, 'apply': apply, 'roots': len(roots), 'objects': len(objects),
                      'orphan_objects': [str(p) for p in garbage],
                      'reclaimable_bytes': sum(p.stat().st_size for p in garbage),
                      'objects_verified': len(references), 'evidence_expired': 0}
            staging = []
            for pattern in ('.pending-*', '.index-*'):
                for path in self.root.rglob(pattern):
                    safe_absolute(path)
                    if not path.is_file():
                        raise StorageError('Unsafe abandoned staging entry')
                    if time.time() - path.stat().st_mtime >= grace_seconds:
                        staging.append(path)
            for path in (self.root / 'staging').glob('.parquet-export-*'):
                safe_absolute(path)
                if not path.is_dir():
                    raise StorageError('Unsafe converter staging entry')
                for child in path.rglob('*'):
                    safe_absolute(child)
                    if not child.is_dir() and not child.is_file():
                        raise StorageError('Nonregular converter staging entry')
                if time.time() - path.stat().st_mtime >= grace_seconds:
                    staging.append(path)
            report['abandoned_staging'] = [str(p) for p in staging]
            if apply:
                journal = self.root / ('gc-' + str(time.time_ns()) + '.json')
                publish(journal, canonical(report))
                for path in [*garbage, *staging]:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    fsync_dir(path.parent)
                # Rebuildable search cache; manifests/objects remain authoritative.
                fd, pending = tempfile.mkstemp(dir=self.root, prefix='.index-')
                os.close(fd)
                try:
                    with sqlite3.connect(pending) as db:
                        db.execute('create table objects (sha256 text primary key, compressed_bytes integer)')
                        removed = {p.stem for p in garbage}
                        db.executemany('insert into objects values (?,?)', [(s, n) for s, n in objects if s not in removed])
                        db.execute('create table packages (path text, manifest text)')
                        db.executemany('insert into packages values (?,?)', [(r['package'], canonical(r['catalog']).decode()) for r in roots])
                    with open(pending, 'rb') as stream:
                        os.fsync(stream.fileno())
                    os.replace(pending, self.root / 'index.sqlite')
                    fsync_dir(self.root)
                finally:
                    if os.path.exists(pending):
                        os.unlink(pending)
            return report


def reference(root, relative):
    """Resolve a missing logical file through the nearest catalog inside root."""
    root = safe_absolute(root)
    relative_name(relative)
    parts = Path(relative).parts
    for depth in range(len(parts) - 1, -1, -1):
        base = root.joinpath(*parts[:depth])
        data = load_catalog(base)
        name = Path(*parts[depth:]).as_posix()
        if data and name in data['files']:
            return Store(data['store']), data['files'][name]
    return None


def large_artifact(relative, size):
    return size >= MINIMUM and Path(relative).suffix in ('.log', '.conf', '.parquet')


def capture_tree(source, output, store):
    """Capture stopped work directly, keeping small files and references expanded."""
    from recipe_results import _regular_file, _RuntimeSocket
    source, output = safe_absolute(source), safe_absolute(output)
    if not source.is_dir():
        raise StorageError('Capture source must be an existing directory')
    if any(path.parent != source for path in source.rglob(CATALOG)):
        raise StorageError('Capture individual stored packages; use export for aggregate report trees')
    if source == output or source in output.parents or output in source.parents:
        raise StorageError('Capture roots must be nonnested')
    if store.root == source or store.root in source.parents or source in store.root.parents or store.root == output or output in store.root.parents or store.root in output.parents:
        raise StorageError('Store must be outside captured trees')
    if os.path.lexists(output):
        raise StorageError('Capture output already exists')
    output.mkdir(parents=True, mode=0o700)
    files, omitted = {}, []
    source_catalog = load_catalog(source)
    with store.locked():
        if source_catalog:
            for name, ref in source_catalog['files'].items():
                if os.path.lexists(source / name):
                    with _regular_file(source, name) as content:
                        actual = store._put(content)
                    if actual != ref:
                        raise StorageError('Materialized source differs from its catalog')
                    files[name] = actual
                else:
                    with Store(source_catalog['store']).open(ref) as content:
                        files[name] = ref if source_catalog['store'] == str(store.root) else store._put(content)
        for directory, dirs, names in os.walk(source, followlinks=False, onerror=lambda exc: (_ for _ in ()).throw(exc)):
            base = Path(directory)
            if any((base / name).is_symlink() for name in dirs):
                raise StorageError('Symlink directory in capture source')
            for name in sorted(names):
                relative = (base / name).relative_to(source).as_posix()
                if relative == CATALOG or relative in files:
                    continue
                try:
                    with _regular_file(source, relative) as content:
                        size = os.fstat(content.fileno()).st_size
                        if large_artifact(relative, size):
                            files[relative] = store._put(content)
                        else:
                            target = output / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with target.open('xb') as target_stream:
                                shutil.copyfileobj(content, target_stream)
                                target_stream.flush()
                                os.fsync(target_stream.fileno())
                except _RuntimeSocket:
                    omitted.append(relative)
        sync_tree(output)
        store._catalog(output, files)
    if omitted:
        publish(output / 'runtime-socket-omissions.json', canonical({'paths': omitted}))
    return {'stored_files': len(files), 'runtime_sockets_omitted': omitted}


def verify_tree(package):
    package = safe_absolute(package)
    count = 0
    for path in [package, *sorted(p for p in package.rglob('*') if p.is_dir())]:
        data = load_catalog(path)
        if data:
            for ref in data['files'].values():
                with Store(data['store']).open(ref):
                    pass
                count += 1
    return {'valid': True, 'stored_files_verified': count}


def reclaim(source, package, *, prefix=''):
    """Reclaim only identical stored bulk files, after a caller stops its writers."""
    source, package = safe_absolute(source), safe_absolute(package)
    if source == package or source in package.parents or package in source.parents:
        raise StorageError('Reclamation source and package must be nonnested')
    sync_tree(package)
    verify_tree(package)
    data = load_catalog(package)
    if not data:
        return {'removed': []}
    removed = []
    store = Store(data['store'])
    journal = store.root / ('reclamation-' + str(time.time_ns()) + '.jsonl')
    with journal.open('x') as records:
        for name, ref in data['files'].items():
            if prefix and not name.startswith(prefix):
                continue
            logical = name[len(prefix):] if prefix else name
            relative_name(logical)
            target = source / logical
            safe_absolute(target)
            if not target.exists():
                continue
            if not target.is_file() or target.is_symlink():
                raise StorageError('Unsafe reclaim source')
            before = target.stat()
            with target.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = target.stat()
            if (before.st_ino, before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size) or actual != ref['sha256']:
                raise StorageError('Reclaim source changed; retained: ' + str(target))
            records.write(canonical({'path': str(target), 'object': ref}).decode())
            records.flush()
            os.fsync(records.fileno())
            fsync_dir(store.root)
            target.unlink()
            fsync_dir(target.parent)
            removed.append(name)
    return {'removed': removed}


def export_tree(source, output):
    """Materialize an independent package, preserving its original result hashes."""
    from recipe_results import _regular_file
    source, output = safe_absolute(source), safe_absolute(output)
    if source == output or source in output.parents or output in source.parents:
        raise StorageError('Export roots must be nonnested')
    if os.path.lexists(output):
        raise StorageError('Export destination already exists')
    names = set()
    for directory, dirs, files in os.walk(source, followlinks=False):
        base = safe_absolute(directory)
        names.update((base / name).relative_to(source).as_posix() for name in files)
        catalog = load_catalog(base)
        if catalog:
            names.update((base / name).relative_to(source).as_posix() for name in catalog['files'])
    output.mkdir(parents=True, mode=0o700)
    for name in sorted(names):
        if Path(name).name == CATALOG:
            continue  # A portable export has no external storage binding.
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with _regular_file(source, name) as content, target.open('xb') as stream:
            shutil.copyfileobj(content, stream)
    for checksums in sorted(output.rglob('checksums.json'), key=lambda p: -len(p.parts)):
        base = checksums.parent
        ancestors = [base, *[p for p in base.parents if p == output or output in p.parents]]
        if any((p / 'result.json').is_file() for p in ancestors):
            continue  # opaque scientific artifacts retain their original bytes
        if not any((base / name).is_file() for name in ('comparison.json', 'investigation.json', 'bisection.json')):
            continue
        data = json.loads(checksums.read_text())
        if (data.get('schema') in ('bgperf2/comparison/v1alpha1', 'bgperf2/investigation/v1alpha1')
                or (set(data) == {'files'} and (base / 'bisection.json').is_file())):
            files = []
            for path in sorted(base.rglob('*')):
                if path.is_file() and path != checksums:
                    with path.open('rb') as stream:
                        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                    files.append({'path': path.relative_to(base).as_posix(), 'sha256': sha})
            checksums.write_bytes(canonical({**data, 'files': files}))
    sync_tree(output)
    return {'exported_files': len(names)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    capture = commands.add_parser('capture')
    capture.add_argument('--source', required=True)
    capture.add_argument('--output', required=True)
    capture.add_argument('--store', required=True)
    for command in ('verify', 'export', 'reclaim'):
        sub = commands.add_parser(command)
        sub.add_argument('--package', required=True)
        if command == 'export':
            sub.add_argument('--output', required=True)
        if command == 'reclaim':
            sub.add_argument('--source', required=True)
            sub.add_argument('--writers-stopped', action='store_true', required=True)
            sub.add_argument('--prefix', default='')
    maintain = commands.add_parser('maintain')
    maintain.add_argument('--store', required=True)
    maintain.add_argument('--apply', action='store_true')
    maintain.add_argument('--grace-seconds', type=int, default=86400)
    check = commands.add_parser('check')
    check.add_argument('--store', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'capture':
            check_location(args.store)
            result = capture_tree(args.source, args.output, Store(args.store))
        elif args.command == 'check':
            result = check_location(args.store)
        elif args.command == 'verify':
            result = verify_tree(args.package)
        elif args.command == 'export':
            result = export_tree(args.package, args.output)
        elif args.command == 'reclaim':
            result = reclaim(args.source, args.package, prefix=args.prefix)
        else:
            result = Store(args.store).maintain(apply=args.apply, grace_seconds=args.grace_seconds)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
