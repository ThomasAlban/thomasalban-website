"""Keep decorative heading masks small, transparent and sharp on Retina displays."""

from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase
from PIL import Image


class HeadingAssetTests(SimpleTestCase):
    def test_masks_keep_the_canvas_ratio_and_a_small_download_budget(self):
        for filename, size, budget in [
            ('thomas-alban.png', (1275, 699), 75000),
            ('compositions.png', (1275, 699), 70000),
            ('about.png', (850, 466), 40000),
            ('contact.png', (850, 466), 40000),
        ]:
            with self.subTest(filename=filename):
                relative_path = f'images/headings/{filename}'
                asset = Path(finders.find(relative_path))
                self.assertLess(asset.stat().st_size, budget)
                with Image.open(asset) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, size)
                    # Preserve the original uncropped canvas and antialiased alpha.
                    self.assertEqual(image.width * 1398, image.height * 2550)
                    alpha = image.getchannel('A')
                    self.assertEqual(alpha.getextrema(), (0, 255))
                    self.assertGreater(len(alpha.getcolors()), 2)
                css = (settings.BASE_DIR / 'static/css/site.css').read_text()
                self.assertIn(f'url("../{relative_path}")', css)
