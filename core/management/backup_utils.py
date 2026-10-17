"""Private, versioned SQLite/media archives. No Django database connections."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tarfile
import tempfile

from django.conf import settings
from django.core.management.base import CommandError


def safe_path(value):
    path = Path(os.path.abspath(value))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise CommandError('Symlink paths are not permitted.')
    return path


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def regular(path):
    mode = path.lstat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1:
        raise CommandError('Only regular, non-hardlinked files are permitted.')


def configured_paths():
    config = settings.DATABASES['default']
    if config['ENGINE'] != 'django.db.backends.sqlite3' or str(config['NAME']) == ':memory:':
        raise CommandError('A file-backed SQLite default database is required.')
    db, media = safe_path(config['NAME']), safe_path(settings.MEDIA_ROOT)
    if overlaps(db, media):
        raise CommandError('Database and media paths must be separate.')
    return db, media


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def integrity(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise CommandError('SQLite integrity check failed.')


def media_name(name):
    parts = PurePosixPath(name).parts
    return (name == str(PurePosixPath(name)) and len(parts) >= 2
            and parts[0] == 'media' and '\\' not in name
            and all(not p.startswith('.') and ':' not in p for p in parts))


def private_file(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')


def walk_error(error):
    raise error


def backup(destination, revision):
    db, media = configured_paths()
    regular(db)
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = safe_path(str(db) + suffix)
        if sidecar.exists():
            regular(sidecar)
    if not media.is_dir():
        raise CommandError('Media root must be an existing directory (even if empty).')
    destination = safe_path(destination)
    if overlaps(destination, media) or overlaps(destination, db):
        raise CommandError('Backup destination must be separate from database and media.')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_mode & 0o077:
        raise CommandError('Backup destination must have private permissions (0700).')
    with tempfile.TemporaryDirectory(prefix='.backup-', dir=destination) as temporary:
        stage = Path(temporary)
        snapshot = stage / 'database.sqlite3'
        # Precreate with private permissions, including during SQLite backup.
        snapshot.touch(mode=0o600)
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
        integrity(snapshot)
        entries = {'database.sqlite3': snapshot}
        directories = ['media']
        for root, dirs, files in os.walk(media, followlinks=False, onerror=walk_error):
            for name in dirs + files:
                item = safe_path(Path(root) / name)
                relative = 'media/' + item.relative_to(media).as_posix()
                if not media_name(relative):
                    raise CommandError('Hidden or unsafe media names are not archived.')
                if item.is_dir():
                    directories.append(relative)
                else:
                    regular(item)
                    entries[relative] = item
        archive = stage / 'backup.tar'
        manifest = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'revision': revision, 'directories': sorted(directories), 'files': {}}
        with archive.open('xb') as output:
            os.chmod(archive, 0o600)
            with tarfile.open(fileobj=output, mode='w') as tar:
                for name, source in sorted(entries.items()):
                    # Copy media first so hashes describe exactly the bytes archived.
                    if source != snapshot:
                        copied = stage / 'payload'
                        shutil.copyfile(source, copied)
                        os.chmod(copied, 0o600)
                        source = copied
                    manifest['files'][name] = {'sha256': digest(source), 'size': source.stat().st_size}
                    info = tarfile.TarInfo(name)
                    info.size = source.stat().st_size
                    info.mode = 0o600
                    with source.open('rb') as data:
                        tar.addfile(info, data)
                metadata = json.dumps(manifest, sort_keys=True).encode('utf-8')
                if len(metadata) > 1024 * 1024:
                    raise CommandError('Manifest exceeds the supported 1 MiB limit.')
                info = tarfile.TarInfo('manifest.json')
                info.size = len(metadata)
                info.mode = 0o600
                tar.addfile(info, io.BytesIO(metadata))
            output.flush()
            os.fsync(output.fileno())
        # Unique name, never replace an earlier backup.
        final = destination / (stage.name.removeprefix('.') + '.tar')
        os.link(archive, final)
        return final


def unpack(archive, stage):
    regular(archive)
    with tarfile.open(archive, mode='r:') as tar:
        members = tar.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or 'manifest.json' not in names:
            raise CommandError('Missing manifest or duplicate archive members.')
        for member in members:
            if (not member.isfile() or member.issparse()
                    or member.name not in {'manifest.json', 'database.sqlite3'} and not media_name(member.name)):
                raise CommandError('Unsafe archive member.')
        metadata = tar.getmember('manifest.json')
        if metadata.size > 1024 * 1024:
            raise CommandError('Manifest is too large.')
        manifest = json.load(tar.extractfile(metadata))
        if not isinstance(manifest, dict) or manifest.get('version') != 1:
            raise CommandError('Unsupported manifest version.')
        files, directories = manifest['files'], manifest['directories']
        if (not isinstance(files, dict) or not isinstance(directories, list)
                or 'database.sqlite3' not in files or 'media' not in directories
                or set(names) != set(files) | {'manifest.json'}):
            raise CommandError('Manifest does not match archive contents.')
        for name in directories:
            if not isinstance(name, str) or (name != 'media' and not media_name(name)):
                raise CommandError('Unsafe manifest directory.')
            (stage / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        for member in members:
            if member.name == 'manifest.json':
                continue
            expected = files[member.name]
            if expected['size'] != member.size:
                raise CommandError('Archive size mismatch.')
            target = stage / member.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open('xb') as output, tar.extractfile(member) as source:
                os.chmod(target, 0o600)
                shutil.copyfileobj(source, output)
            if digest(target) != expected['sha256']:
                raise CommandError('Archive checksum mismatch.')
    for directory in stage.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o700)
    integrity(stage / 'database.sqlite3')


def restore(archive, database, media):
    live_db, live_media = configured_paths()
    archive, database, media = map(safe_path, (archive, database, media))
    for target in (database, media):
        if any(overlaps(target, other) for other in (live_db, live_media, archive)):
            raise CommandError('Restore targets must be separate from configured storage and archive.')
        if target.exists() or any(os.path.lexists(str(target) + suffix) for suffix in ('-wal', '-shm', '-journal')):
            raise CommandError('Restore targets and SQLite sidecars must not exist.')
        if not target.parent.is_dir():
            raise CommandError('Restore target parents must already exist.')
    if overlaps(database, media):
        raise CommandError('Restore targets must be separate.')
    # Validate everything before publishing either target. Parents must be trusted,
    # offline, and not concurrently modified; this is not a hostile OS sandbox.
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=media.parent) as temporary:
        stage = Path(temporary)
        unpack(archive, stage)
        created_db = created_media = False
        try:
            with private_file(database) as output:
                created_db = True
                os.chmod(database, 0o600)
                with (stage / 'database.sqlite3').open('rb') as source:
                    shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            media.mkdir(mode=0o700)
            created_media = True
            shutil.copytree(stage / 'media', media, dirs_exist_ok=True)
        except BaseException:
            if created_media:
                shutil.rmtree(media)
            if created_db:
                database.unlink()
            raise


ERRORS = (OSError, sqlite3.Error, tarfile.TarError, ValueError, KeyError, TypeError)
