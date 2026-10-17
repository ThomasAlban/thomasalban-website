from io import BytesIO

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.forms.models import inlineformset_factory
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from .admin_forms import ListeningLinkInlineForm, ListeningLinkInlineFormSet
from .listening import MAX_AUDIO_FILE_SIZE, listening_embed_url
from .models import Composition, ListeningLink


class AudioTests(TestCase):
    def test_optional_audio_and_supported_extensions(self):
        Composition(title='Work', slug='work').full_clean()
        for extension in ['mp3', 'wav', 'ogg', 'm4a', 'MP3']:
            with self.subTest(extension=extension):
                work = Composition(title='Work', slug='work', audio_file=SimpleUploadedFile(f'a.{extension}', b'not real audio'))
                work.full_clean()
        field = Composition._meta.get_field('audio_file')
        self.assertEqual(field.upload_to, 'audio/%Y/%m/')
        self.assertIn('audio_file', admin.site._registry[Composition].get_form(None).base_fields)

    def test_invalid_extension_and_size(self):
        for filename, size in [('a.exe', 1), ('a.mp3', MAX_AUDIO_FILE_SIZE + 1)]:
            with self.subTest(filename=filename, size=size):
                audio = UploadedFile(BytesIO(b'a'), name=filename, size=size)
                work = Composition(title='Work', slug='work', audio_file=audio)
                with self.assertRaises(ValidationError) as error:
                    work.full_clean()
                self.assertIn('audio_file', error.exception.message_dict)
        work = Composition(title='Work', slug='work', audio_file=UploadedFile(BytesIO(b'a'), name='a.mp3', size=MAX_AUDIO_FILE_SIZE))
        work.full_clean()


class EmbedTests(SimpleTestCase):
    def test_recognized_youtube_urls(self):
        for url in [
            'https://youtube.com/watch?v=dQw4w9WgXcQ',
            'http://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10',
            'https://m.youtube.com/shorts/dQw4w9WgXcQ',
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ?si=test',
        ]:
            with self.subTest(url=url):
                self.assertEqual(listening_embed_url(url), 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')

    def test_recognized_spotify_urls(self):
        for kind in ['track', 'album', 'playlist', 'episode', 'show']:
            url = f'http://open.spotify.com/{kind}/AbC123?si=test'
            self.assertEqual(ListeningLink(url=url).embed_url, f'https://open.spotify.com/embed/{kind}/AbC123')

    def test_unsafe_or_unrecognized_urls_are_not_embedded(self):
        urls = [
            'https://example.com/audio', 'javascript:alert(1)',
            'ftp://youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ',
            'https://evilyoutube.com/watch?v=dQw4w9WgXcQ',
            'https://youtube.com@evil.test/watch?v=dQw4w9WgXcQ',
            'https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ',
            'https://@youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtube.com:443/watch?v=dQw4w9WgXcQ',
            'https://youtube.com:/watch?v=dQw4w9WgXcQ',
            'https://youtube.com:bad/watch?v=dQw4w9WgXcQ',
            'https://youtube.com./watch?v=dQw4w9WgXcQ',
            'https://youtube.com/watch?v=short',
            'https://youtube.com/watch?v=dQw4w9WgXcQ&v=dQw4w9WgXcQ',
            'https://youtube.com/watch?v=dQw4w9WgX%21',
            'https://youtube.com/watch/extra?v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ/extra',
            'https://youtube.com/shorts/dQw4w9WgXcQ/',
            'https://open.spotify.com/artist/AbC123',
            'https://open.spotify.com/track/a-b',
            'https://open.spotify.com/track/abc/extra',
            'https://open.spotify.com/embed/track/abc',
            'https://open.spotify.com.evil.test/track/abc',
            'https://open.spotify.com:443/track/abc',
            'https://open.spotify.com/track/',
            'https://you\ntube.com/watch?v=dQw4w9WgXcQ',
            ' https://youtube.com/watch?v=dQw4w9WgXcQ',
            '', 'https://[invalid',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(listening_embed_url(url), '')


class ListeningLinkTests(TestCase):
    def setUp(self):
        self.work = Composition.objects.create(title='Work', slug='work')

    def make_link(self, **kwargs):
        return ListeningLink.objects.create(composition=self.work, label='Listen', url='https://example.com/listen', **kwargs)

    def test_ordering_and_cascade(self):
        later = self.make_link(position=2)
        first = self.make_link()
        second = self.make_link()
        self.assertEqual(list(self.work.listening_links.all()), [first, second, later])
        self.assertEqual(str(first), 'Listen')
        self.work.delete()
        self.assertFalse(ListeningLink.objects.exists())

    def test_required_fields_and_url_validation(self):
        for kwargs in [{'label': '', 'url': ''}, {'label': 'Listen', 'url': 'not-a-url'}, {'label': 'Listen', 'url': 'https://example.com', 'position': -1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                ListeningLink(composition=self.work, **kwargs).full_clean()

    def test_url_policy_in_model_admin_and_display(self):
        for url in [
            'javascript:alert(1)', 'ftp://example.com/audio',
            'https://user:pass@example.com/audio', 'https://@example.com',
            '//example.com/audio', 'https://example.com:99999/audio',
            'https://example.com:/audio', 'https://[invalid',
        ]:
            with self.subTest(url=url):
                link = ListeningLink(composition=self.work, label='Listen', url=url)
                with self.assertRaises(ValidationError):
                    link.full_clean()
                self.assertEqual(link.safe_url, '')
                form = ListeningLinkInlineForm(data={
                    'label': 'Listen', 'url': url, 'position': 0,
                })
                self.assertFalse(form.is_valid())
                self.assertIn('url', form.errors)
        for url in ['http://example.com/audio', 'https://example.com:8443/audio?x=1&y=2']:
            link = ListeningLink(composition=self.work, label='Listen', url=url)
            link.full_clean()
            self.assertEqual(link.safe_url, url)

    def test_credits_are_optional_and_admin_editable(self):
        link = self.make_link()
        link.full_clean()
        self.assertEqual(link.credit, '')
        self.assertEqual(self.work.audio_credit, '')
        self.assertIn('audio_credit', admin.site._registry[Composition].get_form(None).base_fields)
        inline = next(inline for inline in admin.site._registry[Composition].inlines
                      if inline.model == ListeningLink)
        self.assertIn('credit', inline.fields)
        form = ListeningLinkInlineForm(data={
            'label': link.label, 'url': link.url, 'position': 0,
            'credit': 'Verified test recording credit <text>',
        }, instance=link)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        link.refresh_from_db()
        self.assertEqual(link.credit, 'Verified test recording credit <text>')

    def test_primary_constraint_and_validation(self):
        self.make_link(is_primary=True)
        duplicate = ListeningLink(composition=self.work, label='Other', url='https://example.com', is_primary=True)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate.save()
        self.make_link()
        other = Composition.objects.create(title='Other', slug='other')
        ListeningLink.objects.create(composition=other, label='Listen', url='https://example.com', is_primary=True)

    def formset(self, links, extra=None):
        factory = inlineformset_factory(
            Composition, ListeningLink, form=ListeningLinkInlineForm,
            formset=ListeningLinkInlineFormSet,
            fields=['label', 'url', 'position', 'is_primary'], extra=0,
        )
        rows = [(link.pk, primary, delete) for link, primary, delete in links]
        if extra:
            rows.append(('', True, False))
        data = {
            'listening_links-TOTAL_FORMS': str(len(rows)),
            'listening_links-INITIAL_FORMS': str(len(links)),
        }
        for index, (pk, primary, delete) in enumerate(rows):
            prefix = f'listening_links-{index}-'
            data.update({prefix + 'id': str(pk), prefix + 'label': 'Listen', prefix + 'url': 'https://example.com', prefix + 'position': str(index)})
            if primary:
                data[prefix + 'is_primary'] = 'on'
            if delete:
                data[prefix + 'DELETE'] = 'on'
        return factory(data, instance=self.work)

    def test_inline_rejects_multiple_primaries(self):
        first, second = self.make_link(), self.make_link()
        formset = self.formset([(first, True, False), (second, True, False)])
        self.assertFalse(formset.is_valid())
        self.assertIn('Choose at most one primary', str(formset.non_form_errors()))

    def test_switch_primary_in_either_order(self):
        first, second = self.make_link(is_primary=True), self.make_link()
        for selected in [second, first]:
            formset = self.formset([(first, selected == first, False), (second, selected == second, False)])
            self.assertTrue(formset.is_valid(), formset.errors)
            formset.save()
            self.assertEqual(self.work.listening_links.get(is_primary=True).pk, selected.pk)

    def test_deleted_primary_can_be_replaced_by_new_primary(self):
        first = self.make_link(is_primary=True)
        formset = self.formset([(first, True, True)], extra=True)
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertEqual(self.work.listening_links.count(), 1)
        self.assertTrue(self.work.listening_links.get().is_primary)

    def test_unchanged_primary_and_commit_false(self):
        first = self.make_link(is_primary=True)
        formset = self.formset([(first, True, False)])
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        first.refresh_from_db()
        self.assertTrue(first.is_primary)
        formset = self.formset([(first, False, False)])
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save(commit=False)
        first.refresh_from_db()
        self.assertTrue(first.is_primary)

    def test_admin_uses_inline_formset(self):
        inline = next(inline for inline in admin.site._registry[Composition].inlines if inline.model == ListeningLink)
        self.assertIs(inline.formset, ListeningLinkInlineFormSet)


class ListeningMigrationTests(TransactionTestCase):
    migrate_from = [('compositions', '0001_initial')]
    migrate_to = [('compositions', '0002_remove_composition_recording_url_and_more')]

    def test_recording_urls_are_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        try:
            old_apps = executor.loader.project_state(self.migrate_from).apps
            Work = old_apps.get_model('compositions', 'Composition')
            recorded = Work.objects.create(title='Recorded', slug='recorded', recording_url='https://example.com/recording')
            Work.objects.create(title='Silent', slug='silent')
            executor = MigrationExecutor(connection)
            executor.migrate(self.migrate_to)
            new_apps = executor.loader.project_state(self.migrate_to).apps
            Link = new_apps.get_model('compositions', 'ListeningLink')
            link = Link.objects.get()
            self.assertEqual(link.composition_id, recorded.pk)
            self.assertEqual(link.label, 'Recording')
            self.assertEqual(link.url, 'https://example.com/recording')
            self.assertTrue(link.is_primary)
            self.assertEqual(link.position, 0)
            executor = MigrationExecutor(connection)
            executor.migrate(self.migrate_from)
            restored_apps = executor.loader.project_state(self.migrate_from).apps
            Work = restored_apps.get_model('compositions', 'Composition')
            self.assertEqual(Work.objects.get(pk=recorded.pk).recording_url, link.url)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
