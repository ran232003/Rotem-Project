"""Ad hoc: what a candidate reference document would add to every prompt.

Kept because the answer changes whenever the skill or the glossary grows, and
the decision to load a reference always or conditionally rests on this number.
"""

from __future__ import annotations

import sys
from pathlib import Path

from google import genai

from rotem_agent.config import load_firm, load_glossary, load_settings
from rotem_agent.docs.extract import extract_file
from rotem_agent.drafting.prompt import build_system_prompt
from rotem_agent.skill import load_skill

INPUT_USD_PER_MILLION = 0.75


def main(candidate: Path | None) -> int:
    skill = load_skill()
    system = build_system_prompt(load_firm(), load_glossary(), skill, "advisory")
    client = genai.Client(api_key=load_settings().gemini_api_key)
    model = "gemini-3.6-flash"

    def count(text: str) -> int:
        return client.models.count_tokens(model=model, contents=text).total_tokens

    print(f"references loaded on every draft: {', '.join(sorted(skill.references))}")
    system_tokens = count(system)
    print(f"\nsystem prompt now : {len(system):>6} chars -> {system_tokens:>5} tokens")

    if candidate is None:
        return 0

    text = extract_file(candidate).text
    tokens = count(text)
    print(f"candidate document: {len(text):>6} chars -> {tokens:>5} tokens")
    print(f"\nAs an always-on reference: +{tokens / system_tokens:.0%} on every system prompt")
    per_draft = tokens * INPUT_USD_PER_MILLION / 1_000_000
    print(f"  +${per_draft:.5f} per draft, ${per_draft * 300:.2f} per 300 drafts")
    print("  ...on every email, including the ones this procedure has nothing to say about.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
