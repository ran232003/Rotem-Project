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
from rotem_agent.matters import MatterRegistry, load_matters_root
from rotem_agent.outlook import OutlookError, OutlookMailbox, load_mailbox_config
from rotem_agent.retrieval import ChunkStore, GeminiEmbedder, ingest_matter, search
from rotem_agent.skill import load_skill
from rotem_agent.state import ConversationMatters, DraftLedger
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

    search_cmd = sub.add_parser("search", help="Query a matter's documents")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--matter", required=True)
    search_cmd.add_argument("--top", type=int, default=6)
    search_cmd.add_argument("--no-embed", action="store_true")

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
        if args.command == "matters":
            return _run_matters()
        if args.command == "matter-new":
            return _run_matter_new(args)
        if args.command == "ingest":
            return _run_ingest(args)
        if args.command == "search":
            return _run_search(args)
        if args.command == "outlook-demo":
            return _run_outlook_demo(args)
        return _run_draft(args)
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


def _run_draft(args) -> int:
    email = parse_eml(args.eml)
    _print_summary(email)
    excerpts = (
        []
        if args.no_files
        else _retrieve(email, args.matter, no_embed=args.no_embed)
    )
    report = _compose(email, args.model, args.source_policy, excerpts)
    _emit(report, args.out)
    return 0 if report.ok else 1


def _make_drafter(model: str | None, source_policy: str):
    """Build the drafting callable once; the watch loop reuses it every cycle."""
    settings = load_settings()
    client = GeminiClient(api_key=settings.gemini_api_key, model=model or settings.model)
    skill = load_skill()
    print(f"\nDrafting with {client.model}, source policy '{source_policy}' ...")
    return lambda email, excerpts=None: compose(
        email, client, skill=skill, source_policy=source_policy, excerpts=excerpts
    )


def _compose(email: ParsedEmail, model: str | None, source_policy: str, excerpts=None):
    return _make_drafter(model, source_policy)(email, excerpts)


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
                flag = "  NEEDS OCR" if document.needs_ocr else ""
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
    needs_ocr: list[str] = []
    with ChunkStore() as store:
        for matter in targets:
            print(f"\n{matter.slug}")
            summary = ingest_matter(matter, store, embedder, force=args.force)
            print(
                f"  {len(summary.added)} indexed, {len(summary.unchanged)} unchanged, "
                f"{len(summary.removed)} removed, {len(summary.skipped)} unsupported, "
                f"{summary.chunks} new chunk(s)"
            )
            needs_ocr += [f"{matter.slug}/{p}" for p in summary.needs_ocr]

    if needs_ocr:
        # Silence here would be dangerous: the file looks indexed but holds
        # nothing, so the agent would answer as though the document were absent.
        print("\nThese look like scans and are not searchable without OCR:")
        for item in needs_ocr:
            print(f"  - {item}")
    return 0


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
) -> list:
    """Find passages in the client's file that bear on this email.

    Returns an empty list rather than raising when no matter can be identified:
    a draft written from the thread alone is the current behaviour and is safe,
    whereas guessing a matter would mix one client's papers into another's reply.
    """
    try:
        registry = MatterRegistry.discover()
    except ConfigError as exc:
        print(f"Client files not configured, drafting from the thread alone. ({exc})")
        return []

    if matter_slug:
        matter = registry.by_slug(matter_slug)
        if matter is None:
            print(f"No matter with slug {matter_slug}", file=sys.stderr)
            return []
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
            return []
        matter = resolution.matter
        memory.remember(conversation_id, matter.slug)
        print(f"Matter: {matter.slug} ({resolution.reason})")

    query = f"{email.subject}\n{email.latest_body}"[:2000]
    with ChunkStore() as store:
        hits = search(store, matter.slug, query, _embedder(no_embed), top_k=top_k)
    print(f"Retrieved {len(hits)} excerpt(s) from {matter.slug}")
    for hit in hits:
        print(f"  {hit.citation}  ({hit.found_by})")
    return hits


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

    excerpts = (
        []
        if args.no_files
        else _retrieve(
            email,
            args.matter,
            conversation_id=found.conversation_id,
            no_embed=args.no_embed,
        )
    )
    report = _compose(email, args.model, args.source_policy, excerpts)
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
    retriever = (
        None
        if args.no_files
        else lambda email, conversation_id: _retrieve(
            email, None, conversation_id=conversation_id, no_embed=args.no_embed
        )
    )
    if args.once:
        created = len(run_cycle(box, ledger, senders, drafter, options, print, retriever))
    else:
        print(f"Polling every {args.interval}s. Press Ctrl+C to stop.")
        try:
            created = watch(
                box, ledger, senders, drafter, options, retrieve_fn=retriever
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
