"""Draw the desktop icons.

A shortcut to a .bat file gets the generic batch-file icon, which on a lawyer's
desktop looks like something that arrived by accident. Drawn here rather than
committed as an opaque binary so the shape can be changed by editing code.

Two of them: a green envelope to open the dashboard, and a red power symbol to
stop the agent. They have to be unmistakable from each other at 32 pixels,
because one of them is the one she reaches for when something looks wrong, so
they differ in both colour and shape rather than only in colour.

    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"

GREEN = (21, 128, 61)
RED = (185, 28, 28)
PAPER = (255, 255, 255)

# Windows picks the nearest size, so shipping the small ones drawn at their own
# scale avoids the blur of downsampling a single large bitmap.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _tile(size: int, colour: tuple[int, int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    """A rounded tile at four times the size, to be reduced once drawn on."""
    scale = 4
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle(
        [0, 0, edge - 1, edge - 1], radius=int(edge * 0.22), fill=colour
    )
    return image, pen, edge


def envelope(size: int) -> Image.Image:
    image, pen, edge = _tile(size, GREEN)

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


def power(size: int) -> Image.Image:
    """The standard power symbol: a ring broken at the top, with a stem in the gap."""
    image, pen, edge = _tile(size, RED)

    width = max(1, int(edge * 0.075))
    inset = int(edge * 0.28)
    # PIL measures from three o'clock, clockwise. Starting past the top and
    # running the long way round leaves a gap of 60 degrees centred at twelve.
    pen.arc(
        [inset, inset, edge - inset, edge - inset],
        start=300,
        end=600,
        fill=PAPER,
        width=width,
    )
    middle = edge // 2
    pen.line(
        [(middle, int(edge * 0.17)), (middle, int(edge * 0.44))],
        fill=PAPER,
        width=width,
    )

    return image.resize((size, size), Image.LANCZOS)


def write(name: str, shape) -> None:
    out = ASSETS / name
    frames = [shape(size) for size in SIZES]
    frames[-1].save(
        out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1]
    )
    print(f"Wrote {out} ({out.stat().st_size:,} bytes, {len(SIZES)} sizes)")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    write("agent.ico", envelope)
    write("stop.ico", power)


if __name__ == "__main__":
    main()
