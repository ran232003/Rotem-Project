from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from rotem_agent import logs, usage
from rotem_agent.analysis.questions import extract_asks
from rotem_agent.attachments import excerpts_from_files, safe_filename, save_eml_attachments
from rotem_agent.config import OUT_DIR, ConfigError, load_settings
from rotem_agent.control import clear_stop
from rotem_agent.dashboard import serve
from rotem_agent.doctor import FAIL, format_report, run_all
from rotem_agent.drafting.composer import compose, render_draft_html, render_internal_note
from rotem_agent.llm.gemini import GeminiClient
from rotem_agent.lock import AlreadyRunning, SingleInstance
from rotem_agent.mailparse.parser import ParsedEmail, parse_eml
from rotem_agent.matters import MatterRegistry, load_matters_root
from rotem_agent.outcomes import DEFAULT_DAYS as OUTCOME_DAYS
from rotem_agent.outcomes import refresh as refresh_outcomes
from rotem_agent.outcomes import save as save_outcomes
from rotem_agent.outlook import OutlookError, OutlookMailbox, load_mailbox_config
from rotem_agent.pricing import format_money, format_usd, load_prices
from rotem_agent.retrieval import ChunkStore, GeminiEmbedder, ingest_matter, search
from rotem_agent.skill import load_skill
from rotem_agent.templates import load_templates
from rotem_agent.state import ConversationMatters, DraftLedger
from rotem_agent.watch import WatchOptions, backlog_cutoff, run_cycle, watch


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
    draft_cmd.add_argument("--matter", default=None, help="Override matter resolution")
    draft_cmd.add_argument(
        "--no-files", action="store_true", help="Ignore client documents entirely"
    )
    draft_cmd.add_argument("--no-embed", action="store_true", help="Lexical retrieval only")

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
    oldraft_cmd.add_argument("--matter", default=None)
    oldraft_cmd.add_argument("--no-files", action="store_true")
    oldraft_cmd.add_argument("--no-embed", action="store_true")

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
    watch_cmd.add_argument("--no-files", action="store_true")
    watch_cmd.add_argument("--no-embed", action="store_true")

    ledger_cmd = sub.add_parser("ledger", help="Inspect what the agent has already drafted")
    ledger_cmd.add_argument("--forget", metavar="KEY", default=None)

    usage_cmd = sub.add_parser("usage", help="Tokens spent and what they cost")
    usage_cmd.add_argument(
        "--days", type=int, default=30, help="How far back to look. -1 for everything."
    )
    usage_cmd.add_argument(
        "--by",
        choices=("day", "model", "matter", "sender"),
        default=None,
        help="Group the totals instead of listing every draft",
    )
    usage_cmd.add_argument("--limit", type=int, default=20, help="Drafts to list")

    sub.add_parser("matters", help="List client matters and their indexed documents")

    new_cmd = sub.add_parser("matter-new", help="Scaffold a folder for a new matter")
    new_cmd.add_argument("slug")
    new_cmd.add_argument("--client", default="", help="Client name")
    new_cmd.add_argument("--category", default="admin")
    new_cmd.add_argument("--address", action="append", default=None, help="Repeatable")

    ingest_cmd = sub.add_parser("ingest", help="Index the documents in a matter folder")
    ingest_cmd.add_argument("--matter", default=None, help="Defaults to every matter")
    ingest_cmd.add_argument("--force", action="store_true", help="Re-index unchanged files")
    ingest_cmd.add_argument(
        "--no-embed",
        action="store_true",
        help="Lexical index only; skips the embedding API entirely",
    )
    ingest_cmd.add_argument(
        "--ocr",
        action="store_true",
        help="Transcribe scans and photographs. Costs tokens per page, so a whole "
        "folder of certificates is opt-in; email attachments are always read.",
    )

    audit_cmd = sub.add_parser(
        "audit",
        help="Audit a matter's public certificates and produce the document table",
    )
    audit_cmd.add_argument("--matter", required=True)
    audit_cmd.add_argument("--model", default=None)
    audit_cmd.add_argument("--out", type=Path, default=OUT_DIR / "audits")

    search_cmd = sub.add_parser("search", help="Query a matter's documents")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--matter", required=True)
    search_cmd.add_argument("--top", type=int, default=6)
    search_cmd.add_argument("--no-embed", action="store_true")

    board_cmd = sub.add_parser(
        "dashboard", help="Open the local page showing what the agent has done"
    )
    board_cmd.add_argument("--port", type=int, default=8765)
    board_cmd.add_argument(
        "--interval", type=int, default=60, help="Poll interval for a watcher started here"
    )
    board_cmd.add_argument("--no-browser", action="store_true")

    outcomes_cmd = sub.add_parser(
        "outcomes", help="Check Sent Items to see which drafts were actually sent"
    )
    outcomes_cmd.add_argument("--days", type=int, default=OUTCOME_DAYS)

    sub.add_parser(
        "accounts",
        help="List the mailboxes this Outlook is signed in to, one per line",
    )

    stop_cmd = sub.add_parser("stop", help="Stop the agent without the dashboard")
    stop_cmd.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="How long to wait for it to finish the message it is on",
    )
    stop_cmd.add_argument(
        "--force", action="store_true", help="Terminate it instead of asking"
    )
    stop_cmd.add_argument(
        "--dialog",
        action="store_true",
        help="Report through a message box rather than the console, for the desktop icon",
    )

    doctor_cmd = sub.add_parser(
        "doctor", help="Check this machine is set up correctly and say what is missing"
    )
    doctor_cmd.add_argument(
        "--online", action="store_true", help="Also confirm the Gemini key is accepted"
    )
    doctor_cmd.add_argument(
        "--no-outlook", action="store_true", help="Skip the Outlook checks"
    )

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
    log_path = logs.setup(" ".join(argv if argv is not None else sys.argv[1:]))
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
        if args.command == "usage":
            return _run_usage(args)
        if args.command == "matters":
            return _run_matters()
        if args.command == "matter-new":
            return _run_matter_new(args)
        if args.command == "ingest":
            return _run_ingest(args)
        if args.command == "search":
            return _run_search(args)
        if args.command == "audit":
            return _run_audit(args)
        if args.command == "outlook-demo":
            return _run_outlook_demo(args)
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "dashboard":
            return _run_dashboard(args)
        if args.command == "outcomes":
            return _run_outcomes(args)
        if args.command == "accounts":
            return _run_accounts()
        if args.command == "stop":
            return _run_stop(args)
        return _run_draft(args)
    except (ConfigError, OutlookError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        print(f"Details in {log_path}", file=sys.stderr)
        return 2
    except Exception:
        # The traceback belongs in the log, not only on a console that may have
        # been closed hours ago.
        logs.logger().exception("unhandled error running %s", args.command)
        raise


def _run_stop(args: argparse.Namespace) -> int:
    """Turn the agent off from outside the dashboard.

    The dashboard was the only way to stop it, and the fallback when that page
    will not open — a port taken by something else, a browser that will not
    launch — was a PowerShell command to hunt the process, which is no use to
    the one person who would need it. This is what the second desktop icon runs.

    Returns 4 when the agent is still running, so a caller can tell "asked and
    it stopped" from "asked and nothing happened".
    """
    from rotem_agent import control, dialog

    def say(hebrew: str, english: str, *, error: bool = False) -> None:
        # Hebrew only through a message box. A console runs under the OEM
        # codepage, where it would arrive as rubbish.
        if args.dialog:
            dialog.tell(hebrew, error=error)
        else:
            print(english, file=sys.stderr if error else sys.stdout)

    if not control.watcher_status().running:
        # A request left behind by a watcher that was killed rather than asked
        # would stop the next one on its first cycle.
        control.clear_stop()
        say("הסוכן אינו פועל.", "The agent is not running.")
        return 0

    if args.force:
        forced = control.force_stop()
        if forced.running:
            say("לא ניתן לכבות את הסוכן.", "Could not stop the agent.", error=True)
            return 4
        say("הסוכן כובה בכוח.", "The agent was terminated.")
        return 0

    if not control.stop_watcher(timeout=args.timeout).running:
        say(
            "הסוכן כובה.\n\nלהפעלה מחדש: הסמל 'סוכן הטיוטות' על שולחן העבודה.",
            "The agent has stopped.",
        )
        return 0

    # It never answered: running code from before the request existed, or wedged
    # in a COM call. Killing it can lose a draft, so it is offered rather than done.
    agreed = args.dialog and dialog.ask(
        "הסוכן אינו מגיב לבקשת הכיבוי.\n\n"
        "לכבות אותו בכוח? טיוטה שנמצאת באמצע כתיבה עלולה ללכת לאיבוד."
    )
    if not agreed:
        say(
            "הסוכן אינו מגיב לבקשת הכיבוי. הבקשה נשארה בתוקף והוא ייעצר כשיסיים.",
            "The agent did not answer. Re-run with --force to terminate it.",
            error=True,
        )
        return 4

    if control.force_stop().running:
        say("לא ניתן לכבות את הסוכן.", "Could not stop the agent.", error=True)
        return 4
    say("הסוכן כובה בכוח.", "The agent was terminated.")
    return 0


def _run_accounts() -> int:
    """Nothing but the addresses, so another process can read them.

    The dashboard needs this to check a mailbox against reality, and cannot ask
    Outlook itself: COM belongs to the thread that initialised it, and a request
    handler is the wrong thread.
    """
    box = OutlookMailbox(load_mailbox_config())
    box.connect()
    for address in box.account_addresses():
        print(address)
    return 0


def _run_dashboard(args: argparse.Namespace) -> int:
    serve(
        port=args.port,
        interval_seconds=args.interval,
        open_browser=not args.no_browser,
    )
    return 0


def _run_outcomes(args: argparse.Namespace) -> int:
    """Refresh the record of which drafts were followed by a sent reply."""
    box = _mailbox()
    result = refresh_outcomes(box, days=args.days)
    save_outcomes(result)

    ledger = DraftLedger()
    entries = ledger.entries()
    sent = sum(
        1
        for e in entries
        if result.was_sent(e.get("conversation_id"), str(e.get("drafted_at", "")))
    )
    unknown = sum(
        1
        for e in entries
        if result.was_sent(e.get("conversation_id"), str(e.get("drafted_at", ""))) is None
    )

    print(f"Sent Items scanned back {args.days} day(s): {len(result.conversations)} conversation(s)")
    print(f"Drafts: {len(entries)} written, {sent} followed by a sent reply", end="")
    print(f", {unknown} unknown" if unknown else "")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    checks = run_all(online=args.online, skip_outlook=args.no_outlook)
    print(format_report(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


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


def _run_draft(args) -> int:
    email = parse_eml(args.eml)
    _print_summary(email)

    excerpts: list = []
    attachments: list = []
    matter = ""
    category: str | None = None
    if not args.no_files:
        excerpts, matter, category = _retrieve(email, args.matter, no_embed=args.no_embed)
        saved = save_eml_attachments(args.eml, args.out / "attachments")
        attachments = _read_attachments(saved, email, matter=matter)

    report = _compose(
        email, args.model, args.source_policy, excerpts, attachments, category, matter
    )
    _emit(report, args.out, command="draft", sender=email.from_, matter=matter)
    return 0 if report.ok else 1


def _make_drafter(model: str | None, source_policy: str):
    """Build the drafting callable once; the watch loop reuses it every cycle."""
    settings = load_settings()
    client = GeminiClient(api_key=settings.gemini_api_key, model=model or settings.model)
    skill = load_skill()
    templates = load_templates()
    print(f"\nDrafting with {client.model}, source policy '{source_policy}' ...")
    if templates:
        print(f"{len(templates)} firm template(s) available.")
    return lambda email, excerpts=None, attachments=None, category=None, matter="": compose(
        email,
        client,
        skill=skill,
        source_policy=source_policy,
        excerpts=excerpts,
        attachment_excerpts=attachments,
        matter_category=category,
        client_type=_client_type(matter),
        templates=templates,
    )


def _client_type(matter: str | None) -> str:
    """A first guess, needed because the template is chosen before the model runs.

    A sender who resolves to an open matter is a client of the firm. A sender who
    does not may still be one, writing from a new address or through an agency, so
    drafting corrects this from the thread when the firm has already replied in it.
    The model classifies the sender properly in the internal note either way.
    """
    return "existing_client" if matter else "potential_client"


def _compose(
    email: ParsedEmail,
    model: str | None,
    source_policy: str,
    excerpts=None,
    attachments=None,
    category: str | None = None,
    matter: str = "",
):
    return _make_drafter(model, source_policy)(email, excerpts, attachments, category, matter)


def _read_attachments(paths: list[Path], email: ParsedEmail, *, matter: str = "") -> list:
    if not paths:
        return []
    query = f"{email.subject}\n{email.latest_body}"
    # Unlike a bulk ingest, this is not opt-in: an email carries a page or two,
    # and a client who photographs a certificate expects the reply to address it.
    ocr = _ocr_or_none()
    ocr_usage: list = []
    excerpts, notes = excerpts_from_files(paths, query, ocr=ocr, usage=ocr_usage)
    for note in notes:
        print(f"  attachment: {note}")
    for excerpt in excerpts:
        print(f"  attachment excerpt: {excerpt.citation}")
    _record_ocr_usage(ocr, ocr_usage, command="attachment", matter=matter)
    return excerpts


def _ocr_or_none():
    """A missing key must degrade to 'cannot read the scan', never crash a draft."""
    try:
        return _ocr()
    except Exception as exc:
        print(f"  OCR unavailable ({exc}); scans will be reported unread")
        return None


def _emit(
    report,
    out_dir: Path,
    *,
    command: str = "draft",
    sender: str = "",
    matter: str = "",
    key: str = "",
) -> None:
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
    if report.template:
        print(f"Template: {report.template} ({report.template_reason})")
    elif report.template_reason:
        print(f"Template: none ({report.template_reason})")
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
    record = usage.from_report(
        report,
        command=command,
        sender=sender,
        subject=report.subject,
        matter=matter,
        key=key,
    )
    usage.UsageLog().record(record)
    _print_cost(record)

    print(f"\nWrote {out_dir / 'draft.html'} and {out_dir / 'internal_note.md'}")


def _print_cost(record: usage.UsageRecord) -> None:
    if not record.input_tokens and not record.output_tokens:
        return
    prices = load_prices()
    thinking = f" +{record.thinking_tokens} thinking" if record.thinking_tokens else ""
    cached = f" ({record.cached_tokens} cached)" if record.cached_tokens else ""
    cost = record.cost_usd(prices)
    print(
        f"\nTokens: in={record.input_tokens}{cached} out={record.output_tokens}{thinking}"
        f"  ({record.seconds}s)  {format_money(prices, cost)}"
    )
    print(
        "  "
        + " | ".join(
            f"{call.get('purpose')} {call.get('in')} in / {call.get('out')} out"
            for call in record.calls
        )
    )
    if cost is None:
        print(f"  Add a price for {record.model} to config/pricing.yaml to cost this.")


def _embedder(disabled: bool):
    """None means lexical-only retrieval, which needs no API calls."""
    if disabled:
        return None
    return GeminiEmbedder(api_key=load_settings().gemini_api_key)


def _run_matters() -> int:
    registry = MatterRegistry.discover()
    if not registry.matters:
        print(f"No matters found under {load_matters_root()}")
        print("Create one with: python -m rotem_agent.cli matter-new <slug>")
        return 1
    with ChunkStore() as store:
        for matter in registry.matters:
            documents = store.documents(matter.slug)
            chunks = sum(d.chunks for d in documents)
            print(f"\n{matter.slug}")
            print(f"  client   : {matter.client_name or '-'}  ({matter.category or '-'})")
            print(f"  addresses: {', '.join(matter.client_addresses) or '-'}")
            if matter.agent_addresses:
                print(f"  agents   : {', '.join(matter.agent_addresses)}")
            print(f"  indexed  : {len(documents)} document(s), {chunks} chunk(s)")
            for document in documents:
                if document.needs_ocr:
                    flag = "  NEEDS OCR"
                elif document.machine_read:
                    flag = "  machine-read"
                else:
                    flag = ""
                print(f"    - {document.rel_path} ({document.chunks} chunks){flag}")
    return 0


def _run_matter_new(args) -> int:
    root = load_matters_root()
    directory = root / args.slug
    if directory.exists():
        print(f"{directory} already exists", file=sys.stderr)
        return 1
    (directory / "docs").mkdir(parents=True)
    addresses = args.address or []
    lines = [
        f"client_name: {args.client or args.slug}",
        f"category: {args.category}",
        "",
        "# Addresses belonging to the client. These identify the matter.",
        "addresses:",
        *(f"  - {a}" for a in addresses),
        "",
        "# Third parties who correspond about this matter, such as a relocation",
        "# agency. An agency writes for many clients, so these never identify the",
        "# matter on their own.",
        "agents:",
        "",
        "notes: ''",
    ]
    (directory / "matter.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created {directory}")
    print(f"Put the client's documents in {directory / 'docs'}, then run: ")
    print(f"  python -m rotem_agent.cli ingest --matter {args.slug}")
    return 0


def _run_ingest(args) -> int:
    registry = MatterRegistry.discover()
    targets = registry.matters
    if args.matter:
        matter = registry.by_slug(args.matter)
        if matter is None:
            print(f"No matter with slug {args.matter}", file=sys.stderr)
            return 1
        targets = [matter]
    if not targets:
        print("No matters to index.")
        return 1

    embedder = _embedder(args.no_embed)
    print(f"Embeddings: {embedder.name if embedder else 'disabled (lexical only)'}")
    ocr = _ocr() if args.ocr else None
    print(f"OCR       : {ocr.name if ocr else 'off (pass --ocr to read scans)'}")

    needs_ocr: list[str] = []
    machine_read: list[str] = []
    with ChunkStore() as store:
        for matter in targets:
            print(f"\n{matter.slug}")
            summary = ingest_matter(matter, store, embedder, force=args.force, ocr=ocr)
            print(
                f"  {len(summary.added)} indexed, {len(summary.unchanged)} unchanged, "
                f"{len(summary.removed)} removed, {len(summary.skipped)} unsupported, "
                f"{summary.chunks} new chunk(s)"
            )
            needs_ocr += [f"{matter.slug}/{p}" for p in summary.needs_ocr]
            machine_read += [f"{matter.slug}/{p}" for p in summary.machine_read]
            if summary.machine_read:
                print(
                    f"  transcribed {len(summary.machine_read)} scan(s) by machine; "
                    "confirm names and dates against the originals"
                )
            # Per matter, not per run: an ingest may span several clients and the
            # spend has to be attributable to one of them.
            _record_ocr_usage(ocr, summary.ocr_usage, command="ingest", matter=matter.slug)

    if machine_read:
        print(f"\nMachine-read ({len(machine_read)}):")
        for item in machine_read:
            print(f"  - {item}")

    if needs_ocr:
        # Silence here would be dangerous: the file looks indexed but holds
        # nothing, so the agent would answer as though the document were absent.
        print("\nThese look like scans and are not searchable without OCR:")
        for item in needs_ocr:
            print(f"  - {item}")
        if ocr is None:
            print("  Run again with --ocr to read them.")
    return 0


def _ocr():
    from rotem_agent.docs.ocr import GeminiOcr

    return GeminiOcr(load_settings().gemini_api_key)


def _record_ocr_usage(ocr, records: list, *, command: str, matter: str = "") -> None:
    """OCR spends real tokens, so it belongs in the same ledger as drafting.

    Logged under its own command name rather than folded into the draft, because
    a scan is transcribed once and reused by every later reply; blending the two
    would make the first draft on a matter look wildly expensive.
    """
    if not ocr or not records:
        return
    entry = usage.UsageRecord(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        command=f"{command}:ocr",
        model=ocr.name,
        matter=matter,
        input_tokens=sum(r.input_tokens or 0 for r in records),
        output_tokens=sum(r.output_tokens or 0 for r in records),
        thinking_tokens=sum(r.thinking_tokens or 0 for r in records),
        cached_tokens=sum(r.cached_tokens or 0 for r in records),
        calls=[{"purpose": "ocr", "in": r.input_tokens, "out": r.output_tokens} for r in records],
    )
    usage.UsageLog().record(entry)
    prices = load_prices()
    print(
        f"  OCR: {len(records)} page-call(s), {entry.input_tokens} in / "
        f"{entry.billed_output_tokens} out, {format_money(prices, entry.cost_usd(prices))}"
    )


def _run_audit(args) -> int:
    from rotem_agent import audit as audit_module

    registry = MatterRegistry.discover()
    matter = registry.by_slug(args.matter)
    if matter is None:
        print(f"No matter with slug {args.matter}", file=sys.stderr)
        return 1

    docs = _matter_documents(matter.slug)
    if not docs:
        print(
            f"Nothing indexed for {matter.slug}. Put the certificates in "
            f"{matter.docs_dir} and run:\n"
            f"  python -m rotem_agent.cli ingest --matter {matter.slug} --ocr"
        )
        return 1

    scans = sum(1 for d in docs if d.machine_read)
    print(f"Auditing {matter.slug}: {len(docs)} document(s), {scans} machine-read")

    settings = load_settings()
    client = GeminiClient(api_key=settings.gemini_api_key, model=args.model or settings.model)
    skill = load_skill(audit_module.AUDIT_SKILL)
    report = audit_module.run_audit(
        matter.slug, docs, client, skill, client_name=matter.client_name
    )

    destination = args.out / matter.slug
    destination.mkdir(parents=True, exist_ok=True)
    markdown = destination / "public-documents-audit.md"
    markdown.write_text(
        audit_module.render_markdown(report, matter.client_name), encoding="utf-8"
    )
    (destination / "audit.json").write_text(
        json.dumps(report.data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows = report.rows()
    print(f"\n{len(rows)} document(s) required, {len(report.data.get('gaps') or [])} gap(s)")
    for row in rows:
        urgency = str(row.get("urgency", "")).strip()
        print(f"  - {row.get('document')} ({row.get('country')}){f'  [{urgency}]' if urgency else ''}")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    print(f"\nWrote {markdown}")

    entry = usage.from_report(report, command="audit", matter=matter.slug)
    usage.UsageLog().record(entry)
    _print_cost(entry)
    return 0 if report.ok else 1


def _matter_documents(slug: str) -> list:
    """Every indexed chunk of a matter, reassembled per document.

    The audit needs whole certificates, not the passages closest to a query: a
    name discrepancy lives in whichever document happens to hold it.
    """
    from rotem_agent.audit import SourceDoc

    with ChunkStore() as store:
        records = {record.rel_path: record for record in store.documents(slug)}
        by_path: dict[str, list] = {}
        for chunk in store.load_chunks(slug):
            by_path.setdefault(chunk.rel_path, []).append(chunk)

    docs = []
    for rel_path, chunks in sorted(by_path.items()):
        chunks.sort(key=lambda c: c.idx)
        record = records.get(rel_path)
        docs.append(
            SourceDoc(
                citation=rel_path,
                text="\n".join(chunk.text for chunk in chunks),
                machine_read=bool(record.machine_read) if record else False,
            )
        )
    return docs


def _run_search(args) -> int:
    embedder = _embedder(args.no_embed)
    with ChunkStore() as store:
        hits = search(store, args.matter, args.query, embedder, top_k=args.top)
    if not hits:
        print("No matches. Has this matter been ingested?")
        return 1
    for hit in hits:
        print(f"\n[{hit.citation}]  score {hit.score:.4f}  found by {hit.found_by}")
        print(hit.text[:400] + ("..." if len(hit.text) > 400 else ""))
    return 0


def _retrieve(
    email: ParsedEmail,
    matter_slug: str | None,
    *,
    conversation_id: str | None = None,
    no_embed: bool = False,
    top_k: int = 6,
) -> tuple[list, str, str | None]:
    """Find passages in the client's file that bear on this email.

    Returns the passages, the matter they came from and its category. The slug
    attributes spend to a client; the category decides which of the firm's
    procedures belong in the prompt. No excerpts rather than an error when no
    matter can be identified: a draft written from the thread alone is the
    current behaviour and is safe, whereas guessing a matter would mix one
    client's papers into another's reply.
    """
    try:
        registry = MatterRegistry.discover()
    except ConfigError as exc:
        print(f"Client files not configured, drafting from the thread alone. ({exc})")
        return [], "", None

    if matter_slug:
        matter = registry.by_slug(matter_slug)
        if matter is None:
            print(f"No matter with slug {matter_slug}", file=sys.stderr)
            return [], "", None
    else:
        memory = ConversationMatters()
        resolution = registry.resolve(
            [p.email for p in email.participants],
            known_slug=memory.get(conversation_id),
        )
        if not resolution.ok:
            print(f"No client file attached: {resolution.reason}")
            for candidate in resolution.candidates:
                print(f"  candidate: {candidate.slug}")
            if resolution.ambiguous:
                print("  pass --matter <slug> to choose.")
            return [], "", None
        matter = resolution.matter
        memory.remember(conversation_id, matter.slug)
        print(f"Matter: {matter.slug} ({resolution.reason})")

    query = f"{email.subject}\n{email.latest_body}"[:2000]
    with ChunkStore() as store:
        hits = search(store, matter.slug, query, _embedder(no_embed), top_k=top_k)
    print(f"Retrieved {len(hits)} excerpt(s) from {matter.slug}")
    for hit in hits:
        print(f"  {hit.citation}  ({hit.found_by})")
    return hits, matter.slug, matter.category or None


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

    excerpts: list = []
    attachments: list = []
    matter = ""
    category: str | None = None
    if not args.no_files:
        excerpts, matter, category = _retrieve(
            email,
            args.matter,
            conversation_id=found.conversation_id,
            no_embed=args.no_embed,
        )
        saved = box.save_attachments(found.item, args.out / "attachments")
        attachments = _read_attachments(saved, email, matter=matter)

    report = _compose(
        email, args.model, args.source_policy, excerpts, attachments, category, matter
    )
    _emit(
        report,
        args.out,
        command="outlook-draft",
        sender=found.sender,
        matter=matter,
        key=found.message_id or "",
    )

    if args.save:
        box.create_reply_draft(found.item, report.draft_text, save=True)
        print("\nSaved a threaded reply in your Outlook Drafts folder, tagged 'AI draft'.")
    else:
        print("\nDry run. Pass --save to place this reply in your Outlook Drafts folder.")
    return 0 if report.ok else 1


def _run_outlook_watch(args) -> int:
    # Before Outlook is touched, so a second watcher is turned away rather than
    # racing the first one to draft the same message.
    guard = SingleInstance("watch")
    try:
        guard.acquire()
    except AlreadyRunning as exc:
        print(f"\n{exc}", file=sys.stderr)
        print(
            "Stop the running one first. On Windows, closing its terminal is not "
            "enough:\n"
            "  Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |\n"
            "    Where-Object CommandLine -like '*rotem_agent*'",
            file=sys.stderr,
        )
        return 3
    # A stop left behind by a watcher that was killed rather than asked would
    # otherwise stop this one on its first cycle, which reads as a broken start.
    clear_stop()
    try:
        return _watch_loop(args)
    finally:
        clear_stop()
        guard.release()


def _live_senders(initial: list[str], log=print):
    """Re-read the allowlist each cycle, keeping the last good one on a bad edit.

    Adding a client should not mean stopping the agent, and someone editing the
    file while it runs will sometimes save a half-finished line. Falling back to
    the previous list makes that a logged nuisance instead of a watcher that
    either crashes or quietly starts watching nobody.
    """
    current = list(initial)

    def provide() -> list[str]:
        nonlocal current
        try:
            fresh = list(load_mailbox_config().allowed_senders)
        except Exception as exc:
            log(f"  could not re-read the allowlist, keeping the current one: {exc}")
            return current
        if {s.strip().lower() for s in fresh} != {s.strip().lower() for s in current}:
            log(f"  allowlist changed, now watching: {', '.join(fresh)}")
            current = fresh
        return current

    return provide


def _watch_loop(args) -> int:
    config = load_mailbox_config()
    senders = args.sender or config.allowed_senders
    unknown = [s for s in senders if not config.allows(s)]
    if unknown:
        print(f"Not in allowed_senders: {', '.join(unknown)}", file=sys.stderr)
        return 2

    # An explicit --sender is a deliberate narrowing for one run, so leave it
    # fixed; only the configured list is treated as something that can change.
    watched = senders if args.sender else _live_senders(senders)

    box = _mailbox()
    ledger = DraftLedger()
    compose_draft = _make_drafter(args.model, args.source_policy)
    options = WatchOptions(
        save=args.save,
        interval_seconds=args.interval,
        backlog_days=args.backlog_days,
        start_date=config.start_date,
        max_per_cycle=args.max_per_cycle,
        source_policy=args.source_policy,
        force=args.force,
    )

    print(f"Watching {', '.join(senders)}")
    if not args.sender:
        print("The allowlist is re-read each pass; adding an address needs no restart.")
    cutoff = backlog_cutoff(args.backlog_days, floor=config.start_date)
    if cutoff is not None:
        reason = (
            "start_date"
            if config.start_date is not None and cutoff == config.start_date
            else f"--backlog-days {args.backlog_days}"
        )
        print(f"Ignoring anything received before {cutoff.astimezone():%Y-%m-%d %H:%M} ({reason})")
    print(f"Ledger holds {len(ledger)} answered message(s) at {ledger.path}")
    if not args.save:
        print("Dry run: no drafts will be written. Pass --save to create them.")
    # What the last retrieval resolved to. Retrieval, drafting and emission are
    # separate callbacks in the loop, so the slug (for attributing spend) and the
    # category (for choosing which procedures belong in the prompt) are carried
    # between them here.
    resolved_matter: dict[str, str | None] = {"slug": "", "category": None}

    def drafter(email, excerpts=None, attachments=None):
        return compose_draft(
            email,
            excerpts,
            attachments,
            resolved_matter["category"],
            resolved_matter["slug"] or "",
        )

    def emitter(report, match):
        """One folder per answered message, so the note survives the next run."""
        stamp = re.sub(r"\D", "", str(match.received or ""))[:14] or "unknown"
        slug = safe_filename(match.subject or "message")[:60].rstrip(". ") or "message"
        _emit(
            report,
            OUT_DIR / "drafts" / f"{stamp}-{slug}",
            command="outlook-watch",
            sender=match.sender,
            matter=resolved_matter["slug"],
            key=match.message_id or "",
        )

    def retriever(email, match):
        excerpts, matter, category = _retrieve(
            email, None, conversation_id=match.conversation_id, no_embed=args.no_embed
        )
        resolved_matter["slug"] = matter
        resolved_matter["category"] = category
        saved = box.save_attachments(match.item, OUT_DIR / "attachments")
        return excerpts, _read_attachments(saved, email, matter=matter or "")

    if args.no_files:
        retriever = None
    if args.once:
        created = len(
            run_cycle(box, ledger, watched, drafter, options, print, retriever, emitter)
        )
    else:
        print(f"Polling every {args.interval}s. Press Ctrl+C to stop.")
        try:
            created = watch(
                box,
                ledger,
                watched,
                drafter,
                options,
                retrieve_fn=retriever,
                emit_fn=emitter,
            )
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


def _run_usage(args) -> int:
    log = usage.UsageLog()
    prices = load_prices()
    records = log.read(since=usage.cutoff(args.days))
    if not records:
        window = "ever" if args.days < 0 else f"in the last {args.days} day(s)"
        print(f"No drafts recorded {window} in {log.path}")
        return 0

    print(f"Usage from {log.path}")
    print(f"Prices from {prices.source or 'config/pricing.yaml'}\n")

    if args.by:
        rows = []
        for name, group in usage.group(records, args.by).items():
            rows.append((name, usage.totals(group, prices)))
        rows.sort(key=lambda row: row[1].cost_usd, reverse=True)
        width = max(len(name) for name, _ in rows)
        for name, group_totals in rows:
            print(
                f"  {name:<{width}}  {group_totals.records:>3} run(s)  "
                f"in {group_totals.input_tokens:>8,}  "
                f"out {group_totals.billed_output_tokens:>8,}  "
                f"{format_usd(group_totals.cost_usd)}"
                + (f"  ({group_totals.unpriced} unpriced)" if group_totals.unpriced else "")
            )
    else:
        for record in sorted(records, key=lambda r: r.at, reverse=True)[: args.limit]:
            flag = "" if record.ok else "  PROBLEMS"
            print(
                f"  {record.at[:16].replace('T', ' ')}  {record.model}  "
                f"{record.matter or '(no matter)'}  "
                f"in {record.input_tokens:,}  out {record.billed_output_tokens:,}  "
                f"{record.seconds}s  {format_usd(record.cost_usd(prices))}{flag}"
            )
            print(f"      {record.subject[:70]}")

    grand = usage.totals(records, prices)
    thinking = (
        f" (incl. {grand.thinking_tokens:,} reasoning)" if grand.thinking_tokens else ""
    )
    print(f"\n{grand.records} metered run(s)")
    print(f"  input   {grand.input_tokens:>10,} tokens")
    print(f"  output  {grand.billed_output_tokens:>10,} tokens{thinking}")
    print(f"  time    {grand.seconds:>10.1f} s")
    average = grand.average_usd
    print(
        f"  cost    {format_money(prices, grand.cost_usd):>10}"
        + (f"   average {format_usd(average)} per run" if average is not None else "")
    )
    if grand.unpriced:
        missing = sorted({r.model for r in records if r.cost_usd(prices) is None})
        print(
            f"\n{grand.unpriced} run(s) are not costed because no price is on file for: "
            + ", ".join(missing)
        )
        print("  Add them to config/pricing.yaml and run this again; nothing is lost,")
        print("  because the log stores tokens and the cost is worked out on read.")
    return 0


def _run_outlook_demo(args) -> int:
    email = parse_eml(args.eml)
    _print_summary(email)
    report = _compose(email, args.model, args.source_policy)
    _emit(report, args.out, command="outlook-demo", sender=email.from_)

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
