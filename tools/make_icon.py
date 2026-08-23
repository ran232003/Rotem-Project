"""Draw the desktop icon.

A shortcut to a .bat file gets the generic batch-file icon, which on a lawyer's
desktop looks like something that arrived by accident. Drawn here rather than
committed as an opaque binary so the shape can be changed by editing code.

    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "assets" / "agent.ico"

GREEN = (21, 128, 61)
PAPER = (255, 255, 255)

# Windows picks the nearest size, so shipping the small ones drawn at their own
# scale avoids the blur of downsampling a single large bitmap.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int) -> Image.Image:
    """An envelope on a rounded tile, at four times the size then reduced."""
    scale = 4
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    radius = int(edge * 0.22)
    pen.rounded_rectangle([0, 0, edge - 1, edge - 1], radius=radius, fill=GREEN)

    left = int(edge * 0.20)
    right = int(edge * 0.80)
    top = int(edge * 0.30)
    bottom = int(edge * 0.70)
    width = max(1, int(edge * 0.045))

    pen.rectangle([left, top, right, bottom], outline=PAPER, width=width)
    # The flap, as the two diagonals meeting at the centre of the envelope.
    middle = ((left + right) // 2, int(top + (bottom - top) * 0.55))
    pen.line([(left, top), middle, (right, top)], fill=PAPER, width=width, joint="curve")

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [draw(size) for size in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(SIZES)} sizes)")


if __name__ == "__main__":
    main()
