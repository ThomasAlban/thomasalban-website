from io import BytesIO
from pathlib import Path
import re

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import modelform_factory
from django.test import SimpleTestCase
from PIL import Image

from compositions.models import CompositionImage, ScorePreview
from .models import BiographyPhoto
from .validators import IMAGE_EXTENSIONS, IMAGE_HELP_TEXT


class ImageValidationTests(SimpleTestCase):
    models = (CompositionImage, ScorePreview, BiographyPhoto)

    def upload(self, extension, image_format):
        data = BytesIO()
        Image.new('RGB', (8, 6), 'white').save(data, format=image_format)
        return SimpleUploadedFile(f'image.{extension}', data.getvalue())

    def test_valid_bmp_is_rejected_by_every_model_and_form(self):
        for model in self.models:
            with self.subTest(model=model.__name__):
                instance = model(image=self.upload('bmp', 'BMP'))
                with self.assertRaises(ValidationError) as error:
                    model._meta.get_field('image').clean(instance.image, instance)
                self.assertEqual(error.exception.error_list[0].code, 'invalid_extension')
                form_class = modelform_factory(model, fields=['image'])
                form = form_class(files={'image': self.upload('bmp', 'BMP')})
                self.assertFalse(form.is_valid())
                self.assertIn('Unsupported image extension', str(form.errors['image']))

    def test_supported_images_are_accepted_including_uppercase_extensions(self):
        formats = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'gif': 'GIF',
                   'webp': 'WEBP', 'avif': 'AVIF'}
        for model in self.models:
            form_class = modelform_factory(model, fields=['image'])
            for extension, image_format in formats.items():
                for name in (extension, extension.upper()):
                    with self.subTest(model=model.__name__, extension=name):
                        form = form_class(files={'image': self.upload(name, image_format)})
                        self.assertTrue(form.is_valid(), form.errors)
                        self.assertEqual(form.fields['image'].help_text, IMAGE_HELP_TEXT)

    def test_corrupt_image_still_rejected(self):
        for model in self.models:
            with self.subTest(model=model.__name__):
                form = modelform_factory(model, fields=['image'])(
                    files={'image': SimpleUploadedFile('image.png', b'not an image')},
                )
                self.assertFalse(form.is_valid())
                self.assertEqual(form.errors.as_data()['image'][0].code, 'invalid_image')

    def test_image_allowlist_matches_nginx_serving_and_mime_types(self):
        config = (Path(__file__).resolve().parent.parent / 'deploy/nginx.conf').read_text()
        location = next(line for line in config.splitlines() if 'location ~* ^/media/' in line)
        extensions = set(re.search(r'\(\?:([a-z0-9|]+)\)', location).group(1).split('|'))
        image_extensions = set()
        audio_extensions = set()
        for kind, suffixes in re.findall(r'(image|audio)/\S+\s+([^;]+);', config):
            (image_extensions if kind == 'image' else audio_extensions).update(suffixes.split())
        self.assertEqual(set(IMAGE_EXTENSIONS), image_extensions)
        self.assertEqual(extensions - audio_extensions, set(IMAGE_EXTENSIONS))
