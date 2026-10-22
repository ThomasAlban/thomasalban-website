# Website icons

The icons in `static/images/icons/` use the owner's replacement green-and-cream TA monogram, including the complete border and musical notes. The source attachment is a 2048 x 2048 RGBA PNG (289,144 bytes):

`.juggler/Google Search Website Title Branding--conv_ajfs5vk2l/assets/24033265126a23ecf1557f056646c5110f79a7e50845d09a3c6956559cb5318f.png`

Generated using installed Pillow, resizing the full original directly with `Image.Resampling.LANCZOS`. No crop, redraw, palette reduction or color changes were applied. PNGs use `optimize=True` and retain RGBA transparency; the source has no embedded ICC profile, and none is added. The ICO contains 32-bit RGBA BMP frames, each resized directly from the original, for browser compatibility. Decoded pixels of both PNGs and every ICO frame were verified against direct full-canvas LANCZOS resizes of the source.

| Asset | Dimensions | Bytes |
| --- | --- | ---: |
| `favicon-96.png` | 96 x 96 | 13,946 |
| `favicon.ico` | 16 x 16, 32 x 32, 48 x 48 | 14,510 |
| `apple-touch-icon.png` | 180 x 180 | 30,378 |

The shared `templates/base.html` head declares all three outside the metadata block, including on error pages. The 96 px PNG is square and a multiple of 48 for Google favicon compatibility. No manifest, PWA behavior or root favicon route is required.

Deploy through the existing Docker build: `collectstatic` copies these assets and nginx serves them under `/static/images/icons/`. No settings or migrations are required. Keep the icon URLs stable and publicly crawlable. Browser caches and Google's recrawl schedule can delay the visible update; inclusion in search results is not guaranteed. The original attachment is not required at runtime or by tests.

Regression coverage is in `core/test_icons.py`, including rendered declarations, image dimensions, all ICO frames, download budgets, static discovery and collection into a temporary production static root.
