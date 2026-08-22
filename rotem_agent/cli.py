from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from rotem_agent.analysis.questions import extract_asks
from rotem_agent.config import OUT_DIR, ConfigError, load_settings
from rotem_agent.drafting.composer import compose, render_draft_html, render_internal_note
from rotem_agent.llm.gemini import GeminiClient
from rotem_agent.mailparse.parser import ParsedEmail, parse_eml
from rotem_agent.outlook import OutlookError, OutlookMailbox, load_mailbox_config
from rotem_agent.skill import load_skill
from rotem_agent.state import DraftLedger
from rotem_agent.watch import WatchOptions, run_cycle, watch


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

    scan_cmd = sub.add_parser(
        "outlook-scan", help="List messages from an allowed sender in the local Outlook"
    )
    scan_cmd.add_argument("--sender", required=True)
    scan_cmd.add_argument("--limit", type=int, default=20)

    oldraft_cmd = sub.add_parser(
        "outlook-draft", help="Draft a reply to the newest message from an allowed sender"
    )
    oldraft_cmd.add_argument("--sender", required=True)
    oldraft_cmd.add_argument(
        "--index", type=int, default=0, help="0 is the newest matching message"
    )
    oldraft_cmd.add_argument(
        "--save",
        action="store_true",
        help="Write the reply into the Outlook Drafts folder (never sends)",
    )
    oldraft_cmd.add_argument("--model", default=None)
    oldraft_cmd.add_argument("--out", type=Path, default=OUT_DIR)
    oldraft_cmd.add_argument(
        "--source-policy", choices=("strict", "advisory"), default="advisory"
    )

    watch_cmd = sub.add_parser(
        "outlook-watch",
        help="Poll Outlook and draft a reply to each new message, once per message",
    )
    watch_cmd.add_argument(
        "--sender",
        action="append",
        default=None,
        help="Repeatable. Defaults to every address in allowed_senders.",
    )
    watch_cmd.add_argument("--interval", type=int, default=60, help="Seconds between polls")
    watch_cmd.add_argument(
        "--backlog-days",
        type=int,
        default=7,
        help="Ignore mail older than this on first run. -1 means no limit.",
    )
    watch_cmd.add_argument("--max-per-cycle", type=int, default=5)
    watch_cmd.add_argument("--once", action="store_true", help="Run a single pass and exit")
    watch_cmd.add_argument(
        "--force",
        action="store_true",
        help="Re-draft messages already in the ledger",
    )
    watch_cmd.add_argument("--save", action="store_true")
    watch_cmd.add_argument("--model", default=None)
    watch_cmd.add_argument(
        "--source-policy", choices=("strict", "advisory"), default="advisory"
    )

    ledger_cmd = sub.add_parser("ledger", help="Inspect what the agent has already drafted")
    ledger_cmd.add_argument("--forget", metavar="KEY", default=None)

    demo_cmd = sub.add_parser(
        "outlook-demo",
        help="Draft from a local .eml and place it in Outlook as a new mail to --to",
    )
    demo_cmd.add_argument("eml", type=Path)
    demo_cmd.add_argument("--to", required=True)
    demo_cmd.add_argument("--save", action="store_true")
    demo_cmd.add_argument("--model", default=None)
    demo_cmd.add_argument("--out", type=Path, default=OUT_DIR)
    demo_cmd.add_argument(
        "--source-policy", choices=("strict", "advisory"), default="advisory"
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "parse":
            return _run_parse(args.eml)
        if args.command == "outlook-scan":
            return _run_outlook_scan(args.sender, args.limit)
        if args.command == "outlook-draft":
            return _run_outlook_draft(args)
        if args.command == "outlook-watch":
            return _run_outlook_watch(args)
        if args.command == "ledger":
            return _run_ledger(args)
        if args.command == "outlook-demo":
            return _run_outlook_demo(args)
        return _run_draft(args.eml, args.model, args.out, args.source_policy)
    except (ConfigError, OutlookError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 2


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
    email = parse_eml(path)
    _print_summary(email)
    report = _compose(email, model, source_policy)
    _emit(report, out_dir)
    return 0 if report.ok else 1


def _make_drafter(model: str | None, source_policy: str):
    """Build the drafting callable once; the watch loop reuses it every cycle."""
    settings = load_settings()
    client = GeminiClient(api_key=settings.gemini_api_key, model=model or settings.model)
    skill = load_skill()
    print(f"\nDrafting with {client.model}, source policy '{source_policy}' ...")
    return lambda email: compose(email, client, skill=skill, source_policy=source_policy)


def _compose(email: ParsedEmail, model: str | None, source_policy: str):
    return _make_drafter(model, source_policy)(email)


def _emit(report, out_dir: Path) -> None:
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


def _mailbox() -> "OutlookMailbox":
    config = load_mailbox_config()
    box = OutlookMailbox(config)
    box.connect()
    accounts = box.account_addresses()
    print(f"Outlook account(s): {', '.join(accounts)}")
    if config.mailbox and not any(config.mailbox.lower() == a.lower() for a in accounts):
        print(
            f"  warning: configured mailbox {config.mailbox} is not signed in to this Outlook"
        )
    return box


def _run_outlook_scan(sender: str, limit: int) -> int:
    box = _mailbox()
    print(f"\nSearching for mail from {sender} ...")
    matches = box.messages_from(sender, limit=limit)
    if not matches:
        print("  no messages found")
        return 1
    for index, found in enumerate(matches):
        print(f"  [{index}] {found.received} | {found.folder_path}")
        print(f"      {found.subject}")
    return 0


def _run_outlook_draft(args) -> int:
    box = _mailbox()
    matches = box.messages_from(args.sender, limit=max(args.index + 1, 10))
    if not matches:
        print(f"No mail from {args.sender} in this mailbox. Nothing to reply to.")
        return 1
    if args.index >= len(matches):
        print(f"Only {len(matches)} message(s) found; --index {args.index} is out of range.")
        return 1

    found = matches[args.index]
    print(f"\nReplying to: {found.subject}  [{found.received}]  in {found.folder_path}")
    email = box.to_parsed_email(found.item)
    _print_summary(email)

    report = _compose(email, args.model, args.source_policy)
    _emit(report, args.out)

    if args.save:
        box.create_reply_draft(found.item, report.draft_text, save=True)
        print("\nSaved a threaded reply in your Outlook Drafts folder, tagged 'AI draft'.")
    else:
        print("\nDry run. Pass --save to place this reply in your Outlook Drafts folder.")
    return 0 if report.ok else 1


def _run_outlook_watch(args) -> int:
    config = load_mailbox_config()
    senders = args.sender or config.allowed_senders
    unknown = [s for s in senders if not config.allows(s)]
    if unknown:
        print(f"Not in allowed_senders: {', '.join(unknown)}", file=sys.stderr)
        return 2

    box = _mailbox()
    ledger = DraftLedger()
    drafter = _make_drafter(args.model, args.source_policy)
    options = WatchOptions(
        save=args.save,
        interval_seconds=args.interval,
        backlog_days=args.backlog_days,
        max_per_cycle=args.max_per_cycle,
        source_policy=args.source_policy,
        force=args.force,
    )

    print(f"Watching {', '.join(senders)}")
    print(f"Ledger holds {len(ledger)} answered message(s) at {ledger.path}")
    if not args.save:
        print("Dry run: no drafts will be written. Pass --save to create them.")
    if args.once:
        created = len(run_cycle(box, ledger, senders, drafter, options))
    else:
        print(f"Polling every {args.interval}s. Press Ctrl+C to stop.")
        try:
            created = watch(box, ledger, senders, drafter, options)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
    print(f"\nDrafted {created} repl{'y' if created == 1 else 'ies'}.")
    return 0


def _run_ledger(args) -> int:
    ledger = DraftLedger()
    if args.forget:
        if ledger.forget(args.forget):
            print(f"Forgot {args.forget}. It will be drafted again on the next pass.")
            return 0
        print(f"No ledger entry with key {args.forget}", file=sys.stderr)
        return 1

    entries = ledger.entries()
    if not entries:
        print(f"Ledger is empty ({ledger.path})")
        return 0
    print(f"{len(entries)} answered message(s) in {ledger.path}\n")
    for entry in entries:
        flag = "ok" if entry.get("ok") else "PROBLEMS"
        print(f"  {entry.get('drafted_at')}  [{flag}]  {entry.get('sender')}")
        print(f"    {entry.get('subject')}")
        print(f"    key: {entry.get('key')}")
    return 0


def _run_outlook_demo(args) -> int:
    email = parse_eml(args.eml)
    _print_summary(email)
    report = _compose(email, args.model, args.source_policy)
    _emit(report, args.out)

    box = _mailbox()
    subject = f"[AI draft] {email.subject}"
    if args.save:
        box.create_new_draft(args.to, subject, report.draft_text, save=True)
        print(f"\nSaved a draft to {args.to} in your Outlook Drafts folder.")
    else:
        print("\nDry run. Pass --save to place this draft in your Outlook Drafts folder.")
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
