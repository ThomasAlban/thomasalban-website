"""Keep decorative heading masks small, transparent and sharp on Retina displays."""

from base64 import b64decode
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase
from PIL import Image

from core.templatetags.headings import heading_mask


class HeadingAssetTests(SimpleTestCase):
    def test_masks_keep_the_canvas_ratio_and_a_small_download_budget(self):
        for filename, size, budget in [
            ('thomas-alban.png', (1275, 699), 28000),
            ('compositions.png', (1275, 699), 25000),
            ('about.png', (850, 466), 15000),
            ('contact.png', (850, 466), 14000),
        ]:
            with self.subTest(filename=filename):
                asset = Path(finders.find(f'images/headings/{filename}'))
                self.assertLess(asset.stat().st_size, budget)
                with Image.open(asset) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, size)
                    # Preserve the original uncropped canvas and antialiased alpha.
                    self.assertEqual(image.width * 1398, image.height * 2550)
                    alpha = image.convert('RGBA').getchannel('A')
                    self.assertEqual(alpha.getextrema(), (0, 255))
                    self.assertGreater(len(alpha.getcolors()), 2)
                uri = heading_mask(asset.stem)
                self.assertTrue(uri.startswith('data:image/png;base64,'))
                data = b64decode(uri.split(',', 1)[1], validate=True)
                self.assertEqual(data, asset.read_bytes())
                with Image.open(BytesIO(data)) as embedded:
                    self.assertEqual(embedded.size, size)
        css = (settings.BASE_DIR / 'static/css/site.css').read_text()
        self.assertNotIn('../images/headings/', css)

    def test_heading_mask_rejects_unknown_names_and_paths(self):
        for name in ('missing', '../about', '/tmp/about', 'about.png'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                heading_mask(name)

    def test_heading_mask_reads_each_asset_only_once_per_process(self):
        heading_mask.cache_clear()
        self.addCleanup(heading_mask.cache_clear)
        expected = heading_mask('about')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('Uncached read')):
            self.assertEqual(heading_mask('about'), expected)
