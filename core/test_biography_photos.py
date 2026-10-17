from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import modelform_factory
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import BiographyPhoto


@override_settings(ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class BiographyPhotoTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name, MEDIA_URL='/media/')
        settings.enable()
        self.addCleanup(settings.disable)

    def image_upload(self):
        image = BytesIO()
        Image.new('RGB', (20, 30), 'white').save(image, format='PNG')
        return SimpleUploadedFile('portrait.png', image.getvalue(), content_type='image/png')

    def make_photo(self, alt_text='Thomas Alban portrait', **kwargs):
        return BiographyPhoto.objects.create(
            image=self.image_upload(), alt_text=alt_text, **kwargs,
        )

    def test_image_upload_path_and_default_values(self):
        photo = self.make_photo()
        self.assertRegex(photo.image.name, r'^biography_photos/\d{4}/\d{2}/portrait.*\.png$')
        self.assertTrue(photo.image.storage.exists(photo.image.name))
        self.assertEqual(photo.caption, '')
        self.assertEqual(photo.position, 0)
        self.assertEqual(str(photo), photo.alt_text)

    def test_required_image_and_descriptive_alt_text(self):
        form_class = modelform_factory(BiographyPhoto, fields='__all__')
        form = form_class(data={'alt_text': '', 'position': 0})
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)
        self.assertIn('alt_text', form.errors)
        form = form_class(
            data={'alt_text': '   ', 'position': 0},
            files={'image': self.image_upload()},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('alt_text', form.errors)
        form = form_class(
            data={'alt_text': 'Thomas Alban at a piano', 'position': 0},
            files={'image': self.image_upload()},
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_registration_and_editable_position(self):
        model_admin = admin.site._registry[BiographyPhoto]
        self.assertIn('position', model_admin.list_editable)
        self.assertEqual(model_admin.fields, ['image', 'alt_text', 'caption', 'position'])

    def test_empty_about_keeps_biography_without_gallery(self):
        response = self.client.get(reverse('core:about'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['photos']), [])
        self.assertContains(response, 'Biography placeholder')
        self.assertNotContains(response, 'photo-gallery')

    def test_about_gallery_orders_by_position_then_pk_and_escapes_text(self):
        last = self.make_photo('Last portrait', position=5)
        first = self.make_photo('Portrait "at piano"', position=1, caption='Credit <script>unsafe</script>')
        second = self.make_photo('Second portrait', position=1)
        self.assertEqual(list(BiographyPhoto.objects.all()), [first, second, last])
        response = self.client.get(reverse('core:about'))
        self.assertEqual(list(response.context['photos']), [first, second, last])
        self.assertContains(response, 'Biography placeholder')
        self.assertContains(response, 'class="photo-gallery"')
        self.assertContains(response, 'class="gallery-photo"', count=3)
        self.assertContains(response, 'loading="lazy" decoding="async"', count=3)
        self.assertContains(response, 'alt="Portrait &quot;at piano&quot;"')
        self.assertContains(response, '<figcaption>Credit &lt;script&gt;unsafe&lt;/script&gt;</figcaption>', html=True)
        self.assertContains(response, '<figcaption>', count=1)
        content = response.content.decode()
        locations = [content.index(photo.image.url) for photo in [first, second, last]]
        self.assertEqual(locations, sorted(locations))

    def test_single_photo_renders_without_caption(self):
        photo = self.make_photo()
        response = self.client.get(reverse('core:about'))
        self.assertContains(response, photo.image.url)
        self.assertContains(response, f'alt="{photo.alt_text}"')
        self.assertContains(response, 'class="gallery-photo"', count=1)
        self.assertNotContains(response, '<figcaption>')
