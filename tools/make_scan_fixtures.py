"""Render synthetic certificate images to exercise the OCR path.

Two documents for the same fictional person, with her surname deliberately
transliterated differently on each. That is the discrepancy Rotem's procedure
exists to catch, and a transcription that tidies one spelling into the other
would destroy the evidence, so it is the case worth testing.

Nothing here is real. No client document is ever committed.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "scans"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\davidbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

BIRTH_CERTIFICATE = [
    "REPUBLIC OF MOLDOVA",
    "CERTIFICATE OF BIRTH",
    "",
    "Surname: IVANOVA",
    "Given name: ANNA",
    "Date of birth: 14.03.1986",
    "Place of birth: Chisinau",
    "Father: IVANOV, Petru",
    "Mother: IVANOVA, Maria",
    "",
    "Issued: 20.03.1986   No. AB-114872",
]

PASSPORT_PAGE = [
    "REPUBLICA MOLDOVA / PASSPORT",
    "",
    "Surname: IVANOVva",
    "Given names: ANNA",
    "Date of birth: 14 MAR 1986",
    "Nationality: MDA",
    "Passport No: A5512397",
    "Date of issue: 02.11.2019",
    "Date of expiry: 01.11.2026",
]

MARRIAGE_CERTIFICATE = [
    "REPUBLICA MOLDOVA",
    "CERTIFICATE OF MARRIAGE",
    "",
    "Husband: PETROV, Sergiu",
    "Wife before marriage: IVANOVA, ANNA",
    "Wife after marriage: PETROVA, ANNA",
    "Date of marriage: 11.06.2008",
    "Place: Chisinau",
    "",
    "Registration No: MC-2008-4471",
]

DIVORCE_CERTIFICATE = [
    "REPUBLICA MOLDOVA",
    "CERTIFICATE OF DIVORCE",
    "",
    "Former husband: PETROV, Sergiu",
    "Former wife: PETROVA, ANNA",
    "Marriage dissolved: 03.02.2014",
    "Court: Chisinau District Court",
    "",
    "Registration No: DC-2014-0912",
    "Note: surname after divorce not recorded",
]

ISRAELI_MARRIAGE = [
    "STATE OF ISRAEL",
    "MARRIAGE CERTIFICATE (EXTRACT)",
    "",
    "Spouse A: COHEN, David   ID 034556781",
    "Spouse B: IVANOVA, ANNA  Passport A5512397",
    "Date of marriage: 14.05.2023",
    "Place: Nicosia, Cyprus (registered in Israel)",
    "",
    "Registered: 02.07.2023",
]

HEBREW_LETTER = [
    "מדינת ישראל",
    "רשות האוכלוסין וההגירה",
    "",
    "לכבוד: אנה איבנובה",
    "מספר בקשה: 458822",
    "",
    "בהמשך לבקשתך להסדרת מעמד, עליך להמציא",
    "תעודת מצב אישי מארץ המוצא, מאומתת",
    "באפוסטיל, עד ליום 01.09.2026.",
    "",
    "בכבוד רב,",
    "מדור אשרות",
]


def _visual_rtl(line: str) -> str:
    """Lay a Hebrew line out for a renderer with no bidi engine.

    Reversing the whole string puts the Hebrew in reading order but also flips
    numbers, so 01.09.2026 becomes 6202.90.10 and the fixture silently stops
    testing the date it was written to test. Digit and Latin runs are therefore
    flipped back.
    """
    reversed_line = line[::-1]
    return re.sub(
        r"[0-9A-Za-z][0-9A-Za-z./\-]*",
        lambda match: match.group(0)[::-1],
        reversed_line,
    )


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def render(lines: list[str], path: Path, *, rtl: bool = False) -> Path:
    width, height = 1240, 1754  # A4 at 150 dpi
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font, body_font = _font(46), _font(38)

    y = 140
    for index, line in enumerate(lines):
        font = title_font if index < 2 else body_font
        text = _visual_rtl(line) if rtl and line else line
        span = draw.textlength(text, font=font)
        x = width - 120 - span if rtl else 120
        draw.text((x, y), text, fill="black", font=font)
        y += 70 if index < 2 else 58

    draw.rectangle([90, 90, width - 90, y + 40], outline="black", width=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return path


def main() -> int:
    written = [
        render(BIRTH_CERTIFICATE, OUT_DIR / "birth-certificate.png"),
        render(PASSPORT_PAGE, OUT_DIR / "passport.png"),
        render(MARRIAGE_CERTIFICATE, OUT_DIR / "marriage-2008.png"),
        render(DIVORCE_CERTIFICATE, OUT_DIR / "divorce-2014.png"),
        render(ISRAELI_MARRIAGE, OUT_DIR / "marriage-israel-2023.png"),
        render(HEBREW_LETTER, OUT_DIR / "authority-letter.png", rtl=True),
    ]
    for path in written:
        print(f"{path}  ({path.stat().st_size / 1024:.0f} KB)")
    print(
        "\nWhat this set is built to expose:\n"
        "  - IVANOVA on the birth certificate against IVANOVva on the passport\n"
        "  - PETROVA after 2008, then IVANOVA again in 2023, with no name-change\n"
        "    certificate accounting for the reversion\n"
        "  - nothing evidencing personal status between the 2014 divorce and the\n"
        "    2023 marriage, which is the CENOMAR gap in the firm's procedure"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
