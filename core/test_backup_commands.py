"""All storage is disposable; commands never use the developer database/media."""

from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
from tempfile import TemporaryDirectory
from unittest.mock import patch
import warnings

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class BackupCommandTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.db = self.root / 'source.sqlite3'
        self.media = self.root / 'uploads'
        self.media.mkdir()
        (self.media / 'empty').mkdir()
        (self.media / 'score.pdf').write_bytes(b'score bytes')
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('CREATE TABLE example (value TEXT)')
            connection.execute("INSERT INTO example VALUES ('composition')")
            connection.commit()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            override = override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(self.db)}},
                MEDIA_ROOT=self.media,
            )
            override.enable()
        self.addCleanup(override.disable)
        self.destination = self.root / 'backups'
        self.target_db = self.root / 'restored.sqlite3'
        self.target_media = self.root / 'restored-media'

    def backup(self):
        output = io.StringIO()
        call_command('backup_site', destination=str(self.destination), revision='test-revision',
                     stdout=output, stderr=io.StringIO())
        return Path(output.getvalue().strip())

    def restore(self, archive, **kwargs):
        options = {'archive': str(archive), 'database': str(self.target_db),
                   'media_root': str(self.target_media), 'confirm_offline': True,
                   'stdout': io.StringIO()}
        options.update(kwargs)
        call_command('restore_site', **options)

    def rewrite(self, archive, transform):
        with tarfile.open(archive) as tar:
            entries = [(m, tar.extractfile(m).read()) for m in tar.getmembers()]
        entries = transform(entries)
        with tarfile.open(archive, 'w') as tar:
            for member, data in entries:
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))

    def test_roundtrip_manifest_permissions_and_empty_directories(self):
        archive = self.backup()
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        with tarfile.open(archive) as tar:
            manifest = json.load(tar.extractfile('manifest.json'))
            self.assertEqual(manifest['version'], 1)
            self.assertEqual(manifest['revision'], 'test-revision')
            self.assertEqual(set(tar.getnames()), {'manifest.json', 'database.sqlite3', 'media/score.pdf'})
        self.restore(archive)
        with closing(sqlite3.connect(self.target_db)) as db:
            self.assertEqual(db.execute('SELECT value FROM example').fetchone(), ('composition',))
        self.assertEqual((self.target_media / 'score.pdf').read_bytes(), b'score bytes')
        self.assertTrue((self.target_media / 'empty').is_dir())
        self.assertEqual(self.target_db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.target_media.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.target_media / 'score.pdf').stat().st_mode & 0o777, 0o600)

    def test_online_backup_includes_committed_wal(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("INSERT INTO example VALUES ('WAL entry')")
            db.commit()
            self.restore(self.backup())
        with closing(sqlite3.connect(self.target_db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM example').fetchone(), (2,))

    def test_acknowledgement_required_before_archive_access(self):
        with self.assertRaisesMessage(CommandError, '--confirm-offline'):
            self.restore(self.root / 'missing', confirm_offline=False)
        self.assertFalse(self.target_db.exists())

    def test_existing_targets_and_sidecars_are_never_changed(self):
        archive = self.backup()
        for target in (self.target_db, self.target_media, Path(str(self.target_db) + '-wal')):
            with self.subTest(target=target):
                target.write_bytes(b'keep')
                with self.assertRaises(CommandError):
                    self.restore(archive)
                self.assertEqual(target.read_bytes(), b'keep')
                target.unlink()
        self.target_media.mkdir()
        with self.assertRaises(CommandError):
            self.restore(archive)
        self.assertFalse(self.target_db.exists())

    def test_live_overlapping_and_missing_parent_targets_refused(self):
        archive = self.backup()
        for options in ({'database': str(self.db)}, {'media_root': str(self.media / 'new')},
                        {'database': str(self.target_media / 'db')},
                        {'database': str(self.root / 'missing' / 'db')}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.restore(archive, **options)

    def test_symlink_paths_and_hardlinked_media_refused(self):
        outside = self.root / 'private'
        outside.write_bytes(b'not archived')
        link = self.media / 'link'
        for directory in (False, True):
            link.symlink_to(self.root if directory else outside, target_is_directory=directory)
            with self.assertRaises(CommandError):
                self.backup()
            link.unlink()
        os.link(outside, link)
        with self.assertRaises(CommandError):
            self.backup()
        link.unlink()
        archive = self.backup()
        self.target_media.symlink_to(self.media, target_is_directory=True)
        with self.assertRaises(CommandError):
            self.restore(archive)

    def test_destination_inside_media_or_public_directory_refused(self):
        self.destination = self.media / 'backups'
        with self.assertRaises(CommandError):
            self.backup()
        self.destination = self.root / 'public'
        self.destination.mkdir(mode=0o755)
        with self.assertRaises(CommandError):
            self.backup()

    def test_hidden_media_secrets_refused_and_external_config_not_included(self):
        (self.root / '.env').write_text('fake test secret')
        archive = self.backup()
        with tarfile.open(archive) as tar:
            self.assertNotIn('.env', tar.getnames())
        (self.media / '.env').write_text('fake test secret')
        with self.assertRaises(CommandError):
            self.backup()

    def test_tampered_checksum_refused_before_targets_created(self):
        archive = self.backup()
        self.rewrite(archive, lambda entries: [(m, b'wrong bytes' if m.name == 'media/score.pdf' else data)
                                              for m, data in entries])
        with self.assertRaises(CommandError):
            self.restore(archive)
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_media.exists())

    def test_malicious_member_names_types_and_duplicates(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('media/../escape', tarfile.REGTYPE), ('media\\escape', tarfile.REGTYPE),
                           ('media/link', tarfile.SYMTYPE), ('media/hard', tarfile.LNKTYPE),
                           ('media/fifo', tarfile.FIFOTYPE), ('media/score.pdf', tarfile.REGTYPE)]:
            with self.subTest(name=name, kind=kind):
                archive = self.backup()
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = '/outside'
                self.rewrite(archive, lambda entries: entries + [(member, b'')])
                with self.assertRaises(CommandError):
                    self.restore(archive)
                self.assertFalse(self.target_db.exists())
                self.assertFalse(self.target_media.exists())

    def test_bad_manifest_missing_files_and_invalid_sqlite(self):
        for change in ('version', 'directory', 'missing', 'sqlite', 'json'):
            with self.subTest(change=change):
                archive = self.backup()
                def transform(entries):
                    result = []
                    for member, data in entries:
                        if change == 'missing' and member.name == 'media/score.pdf':
                            continue
                        if member.name == 'database.sqlite3' and change == 'sqlite':
                            data = b'not sqlite'
                        if member.name == 'manifest.json':
                            manifest = json.loads(data)
                            if change == 'version':
                                manifest['version'] = 99
                            if change == 'directory':
                                manifest['directories'].append('../escape')
                            if change == 'sqlite':
                                import hashlib
                                manifest['files']['database.sqlite3'] = {
                                    'size': 10, 'sha256': hashlib.sha256(b'not sqlite').hexdigest()}
                            data = b'{' if change == 'json' else json.dumps(manifest).encode()
                        result.append((member, data))
                    return result
                self.rewrite(archive, transform)
                with self.assertRaises(CommandError):
                    self.restore(archive)
                self.assertFalse(self.target_db.exists())

    def test_missing_sources_not_created_and_failed_backup_cleaned(self):
        self.db.unlink()
        with self.assertRaises(CommandError):
            self.backup()
        self.assertFalse(self.db.exists())
        self.assertFalse(self.destination.exists())

    def test_sidecar_symlinks_including_dangling_targets_refused(self):
        sidecar = Path(str(self.db) + '-wal')
        sidecar.symlink_to(self.root / 'missing')
        with self.assertRaises(CommandError):
            self.backup()
        sidecar.unlink()
        archive = self.backup()
        Path(str(self.target_db) + '-shm').symlink_to(self.root / 'missing')
        with self.assertRaises(CommandError):
            self.restore(archive)
        self.assertFalse(self.target_db.exists())

    def test_unreadable_walk_fails_instead_of_silently_omitting_media(self):
        def failing_walk(*args, **kwargs):
            kwargs['onerror'](PermissionError('test unreadable directory'))
        with patch('core.management.backup_utils.os.walk', side_effect=failing_walk):
            with self.assertRaises(CommandError):
                self.backup()
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_corrupt_source_database_and_missing_media_refused(self):
        self.db.write_bytes(b'not sqlite')
        with self.assertRaises(CommandError):
            self.backup()
        self.assertEqual(list(self.destination.iterdir()), [])
        with override_settings(MEDIA_ROOT=self.root / 'absent-media'):
            with self.assertRaises(CommandError):
                self.backup()
        self.assertFalse((self.root / 'absent-media').exists())

    def test_repeated_backups_are_unique_and_failed_restore_cleans_owned_targets(self):
        first, second = self.backup(), self.backup()
        self.assertNotEqual(first, second)
        with patch('core.management.backup_utils.shutil.copytree', side_effect=OSError('test failure')):
            with self.assertRaises(CommandError):
                self.restore(first)
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_media.exists())
        self.assertFalse(list(self.root.glob('.restore-*')))
