# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Crop a vhs capture to the iirc card in it.

The card's frame is violet, and nothing else on the screen above the prompt is:
the box around the violet pixels is the card. Usage: crop-card.py RAW OUT
"""
import sys

from PIL import Image

BOTTOM = 260   # rows at the bottom that hold the prompt and Claude Code's status lines
PAD = 16

raw, out = sys.argv[1], sys.argv[2]
img = Image.open(raw).convert("RGB")
w, h = img.size
px = img.load()
bg = px[5, 5]
xs, ys = [], []
for y in range(h - BOTTOM):
    for x in range(w):
        r, g, b = px[x, y]
        # violet: blue well above red and green, and not the dark background
        if b > 60 and b > r + 15 and b > g + 10:
            xs.append(x)
            ys.append(y)
if not xs:
    sys.exit(f"crop-card: no card frame in {raw}")
# crop to the frame itself, then add an empty margin: padding the crop would take in the command line above
card = img.crop((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
framed = Image.new("RGB", (card.size[0] + 2 * PAD, card.size[1] + 2 * PAD), bg)
framed.paste(card, (PAD, PAD))
framed.save(out)
print(f"{out} {card.size[0]}x{card.size[1]}")
