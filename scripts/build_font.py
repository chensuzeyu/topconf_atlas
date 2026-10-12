"""Optional build tool: create a local Chinese font subset; runtime needs no external font CDN."""
import json
from pathlib import Path
from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / '.runtime/font-build/NotoSansCJKsc-Regular.otf'
chars = set(chr(i) for i in range(32, 127))
for first in range(0xA1, 0xF8):
    for second in range(0xA1, 0xFF):
        try:
            chars.update(bytes([first, second]).decode('gb2312'))
        except UnicodeDecodeError:
            pass
for path in [*ROOT.glob('frontend/*.js'), *ROOT.glob('frontend/*.html'), *ROOT.glob('config/*.json'), ROOT / 'data/catalog.json']:
    if path.exists():
        chars.update(path.read_text(encoding='utf-8'))
options = subset.Options()
options.flavor = 'woff2'
font = subset.load_font(str(source), options)
worker = subset.Subsetter(options=options)
worker.populate(text=''.join(chars))
worker.subset(font)
subset.save_font(font, str(ROOT / 'frontend/fonts/NotoSansSC.woff2'), options)
print('Local font bytes:', (ROOT / 'frontend/fonts/NotoSansSC.woff2').stat().st_size)
