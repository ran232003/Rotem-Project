from __future__ import annotations

import re

from rotem_agent.config import BoilerplateRules

_BLANK_RUN = re.compile(r"\n{3,}")


def strip_boilerplate(text: str, rules: BoilerplateRules) -> str:
    """Drop confidentiality notices, phone blocks and inline-image placeholders.

    These repeat in every message, so they inflate token counts and match every
    retrieval query while carrying no information.
    """
    if not text:
        return ""

    cuts = [m.start() for pattern in rules.truncate_from if (m := pattern.search(text))]
    if cuts:
        text = text[: min(cuts)]

    kept = [
        line
        for line in text.split("\n")
        if not any(pattern.search(line) for pattern in rules.remove_lines)
    ]
    return _BLANK_RUN.sub("\n\n", "\n".join(kept)).strip()
