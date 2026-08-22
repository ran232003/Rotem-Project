from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from rotem_agent.analysis.questions import extract_asks
from rotem_agent.config import OUT_DIR, load_settings
from rotem_agent.drafting.composer import compose, render_draft_html, render_internal_note
from rotem_agent.llm.gemini import GeminiClient
from rotem_agent.mailparse.parser import ParsedEmail, parse_eml
from rotem_agent.skill import load_skill


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()

    parser = argparse.ArgumentParser(prog="rotem_agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="Inspect an .eml without calling the model")
    parse_cmd.add_argument("eml", type=Path)

    draft_cmd = sub.add_parser("draft", help="Generate a Hebrew reply draft")
    draft_cmd.add_argument("eml", type=Path)
    draft_cmd.add_argument("--model", default=None, help="Override the configured Gemini model")
    draft_cmd.add_argument("--out", type=Path, default=OUT_DIR)
    draft_cmd.add_argument(
        "--source-policy",
        choices=("strict", "advisory"),
        default="advisory",
        help="strict forces a holding reply when a legal proposition cannot be verified",
    )

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _run_parse(args.eml)
    return _run_draft(args.eml, args.model, args.out, args.source_policy)


def _run_parse(path: Path) -> int:
    email = parse_eml(path)
    _print_summary(email)

    asks = extract_asks(email.latest_body)
    print(f"\nAsks found by regex only ({len(asks.asks)}):")
    for index, ask in enumerate(asks.asks, start=1):
        print(f"  {index}. [{ask.kind}] {ask.text}")
    print(f"Expected count stated by sender: {asks.expected_count}")

    print("\n--- latest body ---")
    print(email.latest_body)
    return 0


def _run_draft(path: Path, model: str | None, out_dir: Path, source_policy: str) -> int:
    settings = load_settings()
    email = parse_eml(path)
    _print_summary(email)

    client = GeminiClient(api_key=settings.gemini_api_key, model=model or settings.model)
    print(f"\nDrafting with {client.model}, source policy '{source_policy}' ...")
    report = compose(email, client, skill=load_skill(), source_policy=source_policy)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "draft.txt").write_text(report.draft_text, encoding="utf-8")
    (out_dir / "draft.html").write_text(render_draft_html(report), encoding="utf-8")
    (out_dir / "internal_note.md").write_text(render_internal_note(report), encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(dataclasses.asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    note = report.internal
    print(
        f"\n{note.matter_category} | {note.client_type} | urgency {note.urgency} | "
        f"confidence {note.confidence} | {note.approval}"
        + (" | HOLDING REPLY" if note.is_holding_reply else "")
    )
    print(f"Coverage: {sum(a.answered for a in report.answers)}/{len(report.asks.asks)} asks answered")
    for label, items in (("PROBLEM", report.problems), ("warning", report.warnings)):
        for item in items:
            print(f"  {label}: {item}")
    # Under the advisory policy these are the claims the draft states without an
    # official source. They are the first thing to check before sending.
    if note.unverified_propositions:
        print("\nClaims in this draft that need an official source:")
        for item in note.unverified_propositions:
            print(f"  ? {item}")
        if note.likely_sources:
            print("  Check against:")
            for item in note.likely_sources:
                print(f"    - {item}")

    if note.missing_facts:
        print("\nFacts the draft asks the client for:")
        for item in note.missing_facts:
            print(f"  - {item}")
    if report.placeholders:
        print("\nPlaceholders left for the lawyer:")
        for item in report.placeholders:
            print(f"  - {item}")
    if report.usage:
        print(f"\nTokens: in={report.usage.input_tokens} out={report.usage.output_tokens}")

    print(f"\nWrote {out_dir / 'draft.html'} and {out_dir / 'internal_note.md'}")
    return 0 if report.ok else 1


def _print_summary(email: ParsedEmail) -> None:
    print(f"Subject : {email.subject}")
    print(f"From    : {email.from_}")
    print(f"To      : {', '.join(str(p) for p in email.to)}")
    print(f"Cc      : {', '.join(str(p) for p in email.cc) or '-'}")
    print(f"Date    : {email.date}")
    print(
        f"Attach  : {len(email.real_attachments)} real, "
        f"{len(email.signature_assets)} signature asset(s) ignored"
    )
    print(f"Quoted  : {len(email.quoted_chain)} message(s) in trail")
    print(f"Body    : {len(email.latest_body)} chars after boilerplate stripping")


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
