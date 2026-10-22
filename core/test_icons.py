"""Shared website icons remain discoverable and usable by browsers and crawlers."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.test import SimpleTestCase, override_settings
from PIL import Image


class WebsiteIconTests(SimpleTestCase):
    icons = (
        ('favicon.ico', 'icon', '16x16 32x32 48x48', 'image/x-icon'),
        ('favicon-96.png', 'icon', '96x96', 'image/png'),
        ('apple-touch-icon.png', 'apple-touch-icon', '180x180', None),
    )

    def test_shared_head_includes_icons_even_when_metadata_is_overridden(self):
        for template in ('base.html', '400.html', '403.html', '404.html', '500.html'):
            with self.subTest(template=template):
                content = render_to_string(template)
                head = content.split('</head>', 1)[0]
                for filename, rel, sizes, mime_type in self.icons:
                    declaration = f'<link rel="{rel}" href="{static(f"images/icons/{filename}")}"'
                    if mime_type:
                        declaration += f' type="{mime_type}"'
                    declaration += f' sizes="{sizes}">'
                    self.assertInHTML(declaration, head, count=1)

    def test_icon_formats_dimensions_and_download_budgets(self):
        for filename, size, budget in (
            ('favicon-96.png', (96, 96), 15000),
            ('apple-touch-icon.png', (180, 180), 34000),
            ('favicon.ico', (48, 48), 16000),
        ):
            with self.subTest(filename=filename):
                found = finders.find(f'images/icons/{filename}')
                self.assertIsNotNone(found)
                asset = Path(found)
                self.assertLess(asset.stat().st_size, budget)
                with Image.open(asset) as icon:
                    self.assertEqual(icon.size, size)
                    if filename.endswith('.ico'):
                        self.assertEqual(icon.format, 'ICO')
                        self.assertEqual(icon.ico.sizes(), {(16, 16), (32, 32), (48, 48)})
                        for frame_size in icon.ico.sizes():
                            frame = icon.ico.getimage(frame_size)
                            frame.load()
                            self.assertEqual(frame.size, frame_size)
                    else:
                        self.assertEqual(icon.format, 'PNG')
                        self.assertEqual(icon.mode, 'RGBA')
                        icon.load()
                        # The replacement artwork includes alpha but no ICC profile.
                        self.assertNotIn('icc_profile', icon.info)
                        alpha_min, alpha_max = icon.getchannel('A').getextrema()
                        self.assertLess(alpha_min, 255)
                        self.assertEqual(alpha_max, 255)
                if filename == 'favicon-96.png':
                    self.assertEqual(size[0] % 48, 0)

    def test_collectstatic_copies_icons_to_production_static_root(self):
        with TemporaryDirectory() as directory, override_settings(STATIC_ROOT=directory):
            call_command('collectstatic', interactive=False, verbosity=0)
            for filename, *_ in self.icons:
                relative_path = f'images/icons/{filename}'
                with self.subTest(filename=filename):
                    self.assertEqual(
                        (Path(directory) / relative_path).read_bytes(),
                        Path(finders.find(relative_path)).read_bytes(),
                    )
