# Hebrew Legal Email Draft Agent

Generates a Hebrew reply draft for incoming law-firm email, for review by the
lawyer. Nothing is ever sent: drafts are written to the Drafts folder and wait
for a human. Phase 0 runs offline from a saved `.eml` file; the Outlook
connector reads a live mailbox and writes real drafts. No vector store or UI
yet.

## Setup

```bash
python -m pip install -r requirements.txt
copy .env.example .env    # then add your GEMINI_API_KEY
```

Python 3.11 or later. A virtual environment is recommended, since installing
into the global interpreter can conflict with unrelated packages:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Use

Inspect an email without calling the model:

```bash
python -m rotem_agent.cli parse samples\anna_reentry_visa.eml
```

Generate a draft:

```bash
python -m rotem_agent.cli draft samples\anna_reentry_visa.eml
```

Outputs land in `out/`: `draft.html` (open in a browser for correct
right-to-left rendering), `draft.txt`, and `report.json` with the coverage
check, placeholders and token usage. The exit code is non-zero when a hard
problem is found, so this can gate a batch evaluation later.

## Client files

Documents live in one folder per matter, not per email address:

```
clients\
  anna-reentry-visa\
    matter.yaml
    docs\
      ministry-letter.pdf
      document-checklist.docx
```

A folder per address looks simpler and misfiles immediately. In the sample
thread the sender is a relocation agent, the client is someone else, and a third
party is copied in; keyed on the sender, the client's papers would file under the
agent, and the day the client writes in herself there would be two half-empty
folders for one matter. `matter.yaml` therefore separates the two roles:

```yaml
client_name: אנה
category: reentry_visa
addresses:        # identify the matter
  - client@example.com
agents:           # correspond about it, never identify it
  - agent@relocation.test
```

That distinction is enforced. An agency address that appears in several matters
resolves to none of them and reports the candidates, because picking one would
put another client's documents into this client's reply. Pass `--matter <slug>`
to decide. Once a thread is placed it is remembered in
`state/conversations.json`, so a new participant joining midway does not move it.

```bash
python -m rotem_agent.cli matter-new anna-reentry-visa --address client@example.com
python -m rotem_agent.cli ingest --matter anna-reentry-visa
python -m rotem_agent.cli matters
python -m rotem_agent.cli search --matter anna-reentry-visa "אילו מסמכים צריך"
```

Ingest is incremental: files are hashed, unchanged ones are skipped, edited ones
are re-indexed and deleted ones are removed from the index, so a document
withdrawn from a matter stops appearing in drafts.

### Why retrieval is hybrid

Retrieval fuses BM25 lexical ranking with vector similarity by reciprocal rank.
Semantic search alone is actively wrong for this domain: `ב/1` and `א/5` are
legally unrelated statuses that sit almost on top of each other in vector space,
and the same goes for file numbers and dates. Lexical search gets those exact,
and contributes nothing when the client describes a concept in different words
from the file. Each hit reports whether it was found by wording, by meaning or by
both.

Hebrew is normalised for the lexical side: vowel points are stripped, final
letters are folded so an inflected mention matches, and attached prefixes such as
ו/ה/ב/ל are indexed alongside the surface form rather than replacing it, so an
exact match still outranks an inflected one. Visa classes are exempt from prefix
stripping, since the ב of `ב/1` is the class itself and not the preposition.

Everything is stored in one SQLite file with embeddings as blobs, and similarity
is a brute-force dot product over one matter's chunks. At a few hundred chunks
per matter that is instant, and an approximate-nearest-neighbour index would add
a fragile native dependency for no measurable gain.

### Attachments on the incoming email

Files attached to the email being answered are read too, and are kept separate
from the matter's filed documents in the prompt. The distinction is deliberate:
a filed document has been through the office, whereas an attachment is what the
sender has just asserted. The model is told to confirm receipt and, where an
attachment appears to contradict the client file, to flag it for the lawyer
rather than resolve the conflict itself.

Attachments are saved to `out/attachments/`, and filenames are sanitised because
a name arriving by email is untrusted and `../` in one would otherwise write
outside that folder. Inline images are skipped, so a signature logo is not
mistaken for a document. A long attachment is trimmed to the passages that best
match the email rather than to its first pages, which would favour letterheads.

A scanned attachment is reported as unread rather than passed through empty:

```
attachment not read: passport.pdf: looks like a scan with no text layer, so its
contents are not available to the draft. Hebrew OCR is not wired up yet.
```

### Grounding

Retrieved excerpts are quoted into the prompt with an identifier such as
`ministry-letter.pdf#0`, and the model must list the identifiers it relied on.
Naming a document it was never shown is reported as a problem, which catches an
invented citation. Numbers appearing in a retrieved excerpt count as grounded,
so real file numbers and deadlines from the client's own papers stop being
flagged, while a number from nowhere is still caught.

Use `--no-files` to draft from the thread alone, and `--no-embed` for lexical
retrieval with no embedding API calls.

## Outlook desktop

The connector drives classic Outlook for Windows over COM rather than calling
Microsoft Graph. This is deliberate: COM needs no Azure AD app registration, no
tenant admin consent and no client secret, because it reuses the Outlook session
the user is already signed into. On a corporate tenant where you cannot register
an application, it is the only route in. The trade-offs are that it is Windows
only, Outlook must be running, and it cannot poll while the machine is asleep.

Requires the classic Outlook client. The new Outlook for Windows does not expose
a COM object model.

```bash
copy config\mailbox.example.yaml config\mailbox.yaml
```

`allowed_senders` in that file is a hard boundary, not a filter for convenience.
Every read path checks it before returning a message, so pointing the agent at a
mailbox that also holds unrelated mail cannot expose that mail. `config/mailbox.yaml`
is git-ignored because it names real mailboxes.

```bash
python -m rotem_agent.cli outlook-scan  --sender client@example.com
python -m rotem_agent.cli outlook-draft --sender client@example.com
python -m rotem_agent.cli outlook-draft --sender client@example.com --save
```

`outlook-scan` lists matching messages across the whole mailbox, since mail from
an external address is often filed by a rule rather than left in the Inbox.
`outlook-draft` replies to the newest match, or use `--index` for an older one.
Without `--save` it is a dry run that only writes to `out/`. With `--save` it
creates a threaded reply in Drafts, categorised `AI draft` so machine-written
drafts are obvious in the folder list.

### Watching for new mail

```bash
python -m rotem_agent.cli outlook-watch --once           # one dry-run pass
python -m rotem_agent.cli outlook-watch --save           # poll every 60s
python -m rotem_agent.cli ledger                         # what has been answered
```

Each drafted message is recorded in `state/ledger.json`, keyed by its Internet
Message-ID, so a message is answered exactly once no matter how often the loop
runs. The key is per message rather than per thread, so a genuine follow-up in a
thread already answered is still picked up. An Outlook EntryID would not do,
because it changes when an item is filed into another folder and the message
would look new again. The ledger is written only after the draft exists, so an
interrupted run leaves the message pending rather than silently answered, and it
doubles as the audit trail: model, source policy and verification result per
message.

`--backlog-days` (default 7) stops a first run against a mailbox with years of
history from drafting a reply to everything; `--max-per-cycle` caps each pass.
`ledger --forget <key>` makes one message eligible again, and `--force`
re-drafts everything.

To see how a draft renders without touching a real thread:

```bash
python -m rotem_agent.cli outlook-demo samples\thread.eml --to you@example.com --save
```

A caution on corporate mailboxes: message text is sent to the Gemini API, so
running this against an employer's mail may breach their acceptable-use or data
protection policy regardless of how the allowlist is set. Use it on mail you own.

## Source policy

The firm's intake skill requires an official source for any legal or procedural
proposition. Phase 0 has no way to check gov.il or the Population and
Immigration Authority, so the policy is explicit:

```bash
python -m rotem_agent.cli draft <file> --source-policy advisory   # default
python -m rotem_agent.cli draft <file> --source-policy strict
```

`strict` obeys the skill literally: unverifiable propositions are recorded in
the internal note, confidence drops to low, and the output becomes a neutral
holding reply that answers nothing but confirms understanding and states the
next step.

`advisory` is the current default. It allows a substantive answer where the
thread supports it, and lists every claim that would need an official source
under "Claims in this draft that need an official source". **Read that list
before sending anything.** Those sentences are unverified by construction, and
a plausible but wrong procedural claim is the failure mode this project has to
avoid. The choice is temporary: once source lookup exists, `strict` will produce
sourced answers rather than holding replies and this flag becomes unnecessary.

## How it works

1. `mailparse` decodes the MIME message, splits the new content from the quoted
   trail in both English and Hebrew, strips confidentiality boilerplate, and
   discards inline signature logos so they never reach the document pipeline.
2. `analysis` extracts every question and action request. The regex pass
   recalls aggressively, the model decides what counts, and anything the
   regexes found but the model dropped is reported rather than silently lost.
   It also detects a sender stating how many answers they expect.
3. `skill` loads `skills/legal-client-email-intake`, which governs workflow,
   matter routing, escalation, voice and source discipline. It refuses to load
   if the skill cites a reference document that does not exist, because a
   missing reference silently removes rules.
4. `drafting` builds the prompt from the skill, the firm's own previous replies
   as style examples, and the terminology glossary. It returns an internal note
   plus a client draft, then verifies coverage, grounding of numbers, language
   match, approval routing and that no internal wording leaked into the draft.
5. `llm` keeps all Gemini specifics behind one interface so other providers can
   be compared without touching application code.

Outputs include `internal_note.md`, which is the intake note in the skill's
format: client type, matter category, urgency, key and missing facts, likely
official sources, unverified propositions, confidence and approval level. It is
never part of the email.

## Client data boundary

This repository must never contain privileged material.

- Real correspondence lives in `samples/` and generated drafts in `out/`. Both
  are git-ignored.
- Tests run against `tests/fixtures/synthetic_thread.eml`, a fabricated message
  that reproduces the structure of a real thread: RFC 2047 Hebrew subject and
  display name, base64 bodies, `multipart/related` over `multipart/alternative`,
  an inline `cid:` signature logo, an English attribution block quoting Hebrew,
  numbered questions and a stated answer count. Regenerate with
  `python tools/make_fixture.py`.
- Never put a client name, address or case detail in a test assertion. If a real
  message exposes a parsing bug, reproduce the shape of it in the fixture.

## Configuration

- `config/firm.yaml` — lawyer name and mailbox addresses, used to recognise her
  own messages in a quoted trail.
- `config/glossary.yaml` — terms of art, to stop the model paraphrasing where
  the exact term matters.
- `config/boilerplate.yaml` — patterns for disclaimers and signature blocks.
- `config/mailbox.yaml` — which mailbox to read and which senders may be read.
  Git-ignored; copy from `config/mailbox.example.yaml`.
- `config/matters.yaml` — the folder holding client matters. Git-ignored; point it
  outside the repository in production.
- `GEMINI_EMBED_MODEL` — defaults to `gemini-embedding-001`, chosen because it
  returns one vector per input. `gemini-embedding-2` accepts a batch and returns
  a single vector without erroring, so the count is verified and the batch redone
  one item at a time when it does not match. Whether the newer model retrieves
  Hebrew better is unmeasured, and there is no evaluation harness yet to find out.

## Known limits

- The number check verifies that a number **appears** in the source, not that it
  is used to mean the same thing. Observed failure: the thread mentions 45 days
  as the deadline to complete documents after closing an asylum claim, and a
  draft reused it as the Authority's expected response time for a re-entry visa.
  The check passed it because 45 was present. Read numbers in context.
- Unsupported legal assertions are reported, not blocked, under `advisory`.
  Always read "Claims in this draft that need an official source" before
  sending.
- Output varies noticeably between runs on the same email, from four to six asks
  answered. Quality needs measuring across a set of emails rather than judging
  from one run.
- The glossary can induce over-specificity: the source said documents must be
  "מאומתים ומתורגמים כדין" and the draft upgraded that to apostille and
  notarised translation because both terms were in the vocabulary list. Watch
  for this when editing the glossary.
- Hebrew wording is occasionally wrong in ways only a native reader catches, so
  every draft needs review regardless of what the checks say.
- Signature handling is incomplete. A draft that ends with a typed sign-off is
  flagged, because Outlook appends the real signature separately and the two
  would duplicate. The connector does not yet inject the firm signature.
- Polling only runs while the command is running, and there is no delta
  tracking: every cycle re-runs the sender restriction over the mailbox. That is
  cheap at one allowlisted sender but will not scale to a whole mailbox.
- Scanned documents are detected and reported, not read. A PDF with no text
  layer is recorded as present but unsearchable and listed under "these look like
  scans", because indexing it as empty would make the agent answer as though the
  document did not exist. Hebrew OCR is not wired up yet, and most immigration
  paperwork is scans.
- Retrieval uses one query built from the subject and body. Querying per
  extracted question would retrieve better for a message asking several
  unrelated things.
- Retrieved context can shift the model's own matter classification, which was
  observed changing from `reentry_visa` to `status_spousal` once the client's
  documents were attached. Neither is wrong for that thread, but it shows the
  excerpts influence triage and not only wording.
- Nothing summarises a document as a whole. Retrieval returns passages, so a
  question answered only by reading an entire file will not be answered well.
