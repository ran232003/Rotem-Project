# Hebrew Legal Email Draft Agent

Generates a Hebrew reply draft for incoming law-firm email, for review by the
lawyer. Nothing is ever sent: drafts are written to the Drafts folder and wait
for a human. It runs offline from a saved `.eml` file, or against a live
mailbox through the Outlook connector. Client documents are retrieved from a
local hybrid index. There is no UI beyond the command line and the Drafts
folder.

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

On a fresh Windows machine, `setup.ps1` does all of the above in one go,
including seeding the config files from their examples:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Then confirm the machine is actually ready. `doctor` checks the interpreter,
the packages, the key, every config file, and Outlook, and prints a fix beside
anything it finds:

```bash
python -m rotem_agent.cli doctor --online
```

`--online` additionally confirms the API accepts the key; `--no-outlook` skips
the desktop checks. The exit code is non-zero when something is blocking.
[docs/SETUP.md](docs/SETUP.md) is the same ground written for a non-technical
user installing on the lawyer's own machine, including how to update an existing
install without losing the settings and the answered-message ledger, which are
git-ignored and so absent from a fresh download. `update.ps1` does that copy for
someone who installed from a ZIP rather than a clone. Also
[docs/USAGE-he.md](docs/USAGE-he.md) is the day-to-day guide for the lawyer, in
Hebrew: the icon, the switch, and what to check before sending.

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

A scan or a photograph attached to an email is transcribed automatically, because
a client who photographs a certificate expects the reply to address it and one
email carries a page or two. Bulk indexing of a matter folder does not do this
unasked: see below.

### Reading scans

Certificates, apostilles and old passports arrive as photographs of paper, so a
PDF with no text layer and image files are transcribed by the same multimodal
model that writes the drafts. That avoids a second vendor, a second key and a
second data-processing agreement, and the cost lands in the same usage log.

The transcription is verbatim by instruction and at temperature zero, which
matters more here than it sounds. A model asked to transcribe tends to tidy what
it reads, and the point of a certificate audit is to find that a name is spelled
`IVANOVA` on a birth certificate and `IVANOVva` on a passport. A transcription
that normalises one into the other destroys the evidence. Illegible passages are
marked rather than guessed, and the count is reported.

Anything read this way is recorded as machine-read and says so in its citation:

```
attachment: passport.jpg: transcribed from a scan by machine. Names, dates and
numbers taken from it must be checked against the original.
attachment excerpt: passport.jpg#0 (machine-read)
```

Nothing machine-read is ever treated as established fact. The audit below refuses
to assert a name discrepancy from a transcription without marking it as needing
the original.

Because OCR costs tokens per page, a whole matter folder is opt-in:

```bash
python -m rotem_agent.cli ingest --matter anna-status --ocr
```

Roughly \$0.003 per page at current prices. `matters` marks each document as
`NEEDS OCR` or `machine-read` so nothing is silently indexed empty.

### The public documents audit

A separate command, and deliberately not part of drafting. It reads a matter's
documents whole rather than the passages closest to a query, because a name
discrepancy lives in whichever certificate happens to hold it, and it produces an
internal work product rather than an email:

```bash
python -m rotem_agent.cli audit --matter anna-status
```

It builds a year-by-year personal-status timeline, finds the periods no document
accounts for, compares names across every certificate, and writes the firm's
ten-column table of required documents to
`out/audits/<matter>/public-documents-audit.md`.

The procedure it follows is `skills/public-documents-audit/`, from the firm's
"בדיקת תעודות ציבוריות". Four limits are built into it, and all four exist because
the procedure as written states requirements without citing what imposes them:
it may not cite a procedure number or regulation, it may not assert a discrepancy
resting on a machine-read source without flagging the original, it may not invent
a threshold the firm has not set, and it may not guess whether a country is party
to the Hague Convention. Where an answer turns on one of those, it writes a
`[[TBD: ...]]` placeholder and adds the question to the open questions for the
lawyer. A citation to a document not in the matter is reported as a problem.

This is a work product to check, not an answer. It is not sent to anyone.

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
mailbox that also holds unrelated mail cannot expose that mail. An empty list is
rejected rather than treated as "everything". `config/mailbox.yaml` is
git-ignored because it names real mailboxes.

The watcher re-reads the list every pass, so adding a client takes effect within
one interval and needs no restart. A file caught mid-edit keeps the previous list
and logs it: emptying the boundary because someone saved a half-written line is a
worse failure than a stale one. An explicit `--sender` is left fixed, being a
deliberate narrowing for a single run.

`start_date` in the same file is a floor on how far back the agent will look,
distinct from `--backlog-days`. The window is rolling and answers "how much
history on a first run"; the date is fixed and answers "when did this agent start
work". Whichever is later wins, so neither can widen the other. Without it,
switching on against a mailbox holding years of client threads drafts a reply to
whatever the window happens to reach. The day is read in local time, because "from
the 20th" means the 20th where she is, and reading it as UTC would silently drop
the first three hours of it in Israel. `doctor` reports the resolved date, fails a
date in the future — under which nothing would ever be drafted — and warns when
none is set.

The dashboard edits the list, so the lawyer does not need the file or a
developer. `rotem_agent/senders.py` touches only the line being changed, leaving
the comments and the indentation byte-for-byte alone, including the file's
existing line endings — a config meant to be auditable is worth less
if editing it destroys the notes explaining what it is for. The write goes
through a temporary file and a rename, because the watcher reads this file every
pass and a partial write is a window in which the boundary is whatever happened
to be flushed. Removing the last address is refused: an empty list makes
`load_mailbox_config` raise, the running watcher then keeps its previous list,
and the page would show nobody while the agent carried on drafting. Stopping is
what the switch is for.

`mailbox:` is editable from the same page, but it is a claim rather than a
setting and is treated as one. Nothing selects a store: the reader calls
`GetDefaultFolder` and walks whatever mailbox Outlook opens, so the line exists
only to be checked against `account_addresses()`. An edit is therefore refused
unless Outlook is actually signed in to the address, and the refusal names the
ones that would work. Letting the page write an address Outlook has never heard
of would convert a wrong setting into a startup warning seen days later with
nothing linking it to the click that caused it — and would leave the field
asserting one mailbox while the agent read another. There is one value, so the
page offers a change and no way to add or remove.

Asking Outlook costs a subprocess, because COM belongs to the thread that
initialised it and a request handler is the wrong thread. `rotem_agent/accounts.py`
shells out to `cli accounts`, caches the answer for ten minutes, and fills the
cache in the background so the page never waits on it; a save does wait, since
checking against a cache that was never filled is not a check. A failed lookup
is deliberately not cached — Outlook being closed once should not refuse edits
for the next ten minutes — and an empty account list is refused rather than read
as "no address is valid", which is the one case where a missing check could pass
a wrong value through.

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

Each answered message gets a folder under `out/drafts/`, holding the draft and
the internal note. Writing a draft into the mailbox while discarding the analysis
would leave the reviewer with nothing to review against, since the warnings, the
unverified claims and the approval level all live in the note rather than in the
draft.

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

## The dashboard

```bash
python -m rotem_agent.cli dashboard
```

On the lawyer's machine this is a desktop icon instead: `setup.ps1` writes a
shortcut to `dashboard.bat`, drawn with `tools/make_icon.py` so it does not
inherit the generic batch-file icon, and set to open minimised so the console
window that hosts it stays out of the way.

A second, red icon stops the agent without the dashboard:

```bash
python -m rotem_agent.cli stop
python -m rotem_agent.cli stop --force    # only when the polite one goes unanswered
```

It exists because the page was the only way to turn the agent off, and the
fallback if that page would not open — a port taken by something else, a browser
that would not launch — was a PowerShell command to hunt the process, which is no
use to the one person who would need it. The icon points at `pythonw` rather than
at a `.bat`, so nothing flashes on screen, and reports through a Windows message
box rather than a console: a `.bat` runs under the OEM codepage, where the Hebrew
would arrive as rubbish, and a message she cannot read is worse than none. The
console path speaks English for the same reason. Killing the agent can lose a
draft, so force is offered as a question and never taken from silence: `ask`
returns False when no box can be shown.

A page on `127.0.0.1:8765` with a switch to start and stop the agent, counts of
emails answered and replies sent, what has been spent today, this week, this
month and since the beginning, the allowlist with add and remove, and the
declared mailbox alongside the accounts Outlook really has, so a disagreement
between them is visible rather than buried in a log. It is built on the standard
library: no framework, no build step,
nothing to install beyond what the agent already needs, because every dependency
is something that can fail during setup on a machine where nobody can diagnose
it. It binds to loopback only, since the page lists client names and subjects.

Seven properties are less obvious than they look.

**The only writes that matter are guarded by the Origin header.** Loopback is
not a boundary — any site open in the same browser can post to localhost — and
one of those writes now widens what mail the agent may read. A browser will not
let a cross-site request forge `Origin`, so an absent or matching one is the
check, and a refusal is reported as a reason the person at the keyboard can act
on rather than a failure they cannot.

**A second launch shows the page rather than binding.** Double-clicking the icon
again is how anyone checks whether the dashboard is open. The port is probed
before binding because `socketserver` sets `SO_REUSEADDR` by default and Windows
grants it literally: a second bind on a live port succeeds, and requests then
land on whichever server the OS picks.

**The agent is not the dashboard's child.** It is spawned detached, so closing
the window cannot kill it mid-draft and leave half a reply in Outlook with its
spend recorded nowhere. Observed in practice: a watcher started one evening was
still polling fourteen hours later, long after the dashboard that started it had
gone. The corollary is that liveness has to be discovered rather than remembered,
which is what the lock is for — a dashboard opened fresh finds the agent already
running and reports it, and pressing start returns the existing process instead
of launching a second.

**Stopping is a request.** The switch writes `state/stop.request`; the watcher
notices between messages and exits having finished the one it was on.
Terminating it mid-draft could leave a partly written reply in Outlook and a
model call whose spend went unrecorded. The wait between polls is sliced so a
stop lands in about a second rather than after the full interval. A stop that
goes unanswered for ninety seconds — a watcher left running from before an
update, or one wedged in a COM call — offers a forced shutdown as a last resort.

**Whether the agent is running is asked of the lock, not of a recorded PID.**
Failing to take `state/watch.lock` proves a watcher is alive, stays correct for
one started from a terminal, and avoids `os.kill(pid, 0)`, which terminates the
process on Windows rather than testing it.

**The running total has no start date, and the table has one.** The all-time
figure answers "what has this cost me", which a fixed epoch would quietly
undercount, so its window has no floor at all rather than a sentinel date. The
drafts table covers the same seven days as the seven-day card, so the row count
and that card's figure agree — two lists of "recent drafts" differing by a row is
the kind of thing that costs an afternoon to explain. Rows come down whole and
are paged ten at a time in the browser, because a server-side page number would
have to survive a poll every four seconds; the page is clamped rather than reset
when the list shrinks, so a draft arriving while she reads page three does not
throw her back to the top. Beyond two hundred rows the list is capped and the
page says so instead of paging through a truncation silently.

**Nothing touches Outlook from inside a request.** COM is bound to the thread
that initialised it, so reading Sent Items runs as a separate short-lived
process and leaves its answer in `state/outcomes.json`:

```bash
python -m rotem_agent.cli outcomes --days 30
```

That is what turns "12 drafts, $0.30" into "12 drafted, 9 sent, 3 discarded",
which is the only measure of whether the drafts are worth having. A reply the
lawyer rewrote entirely still counts as sent: the distinction being drawn is
between a draft that gave her somewhere to start and one she threw away. Until
the scan has run the answer is unknown rather than "not sent", because
reporting every draft as discarded would invite exactly the wrong conclusion.

Set `usd_to_ils` in `config/pricing.yaml` to show shekels alongside dollars.

## Logs and cost

Everything printed is mirrored to `logs/agent.log`, five rotating files of two
megabytes. A background watcher outlives the terminal it was started from, and
the run worth reading is always the one that already scrolled away. Uncaught
errors and failed watch cycles write their full traceback there, which is the
only thing that makes an intermittent COM fault diagnosable after the fact.

The log holds mail subjects, client names and message bodies, so it is
privileged material and `logs/` is git-ignored along with `clients/`.

On Windows PowerShell, read it with an explicit encoding or the Hebrew will look
like mojibake, because `Get-Content` defaults to the system code page:

```powershell
Get-Content logs\agent.log -Tail 40 -Encoding UTF8
```

Spend is recorded per draft in `logs/usage.jsonl`, one JSON object per line,
appended and never rewritten, so a run killed mid-draft cannot corrupt earlier
records.

```bash
python -m rotem_agent.cli usage                  # last 30 days, draft by draft
python -m rotem_agent.cli usage --by matter      # spend per client
python -m rotem_agent.cli usage --by day --days -1
```

Three things make the total honest, each of which was wrong or missing at first:

A draft is two model calls, not one. The asks are extracted before the reply is
written, so the meter wraps the client rather than sitting at either call site,
and counts whatever passes through it.

Reasoning tokens are billed at the output rate but reported separately by the
API. On this model they routinely exceed the visible reply, so counting only the
visible output understated the bill roughly fourfold.

Tokens are stored and money is worked out on read, from `config/pricing.yaml`.
Prices are typed in by hand and go stale, so correcting that file reprices every
draft ever recorded. A model with no price on file reports its tokens with the
cost marked unknown rather than assuming a rate, because a plausible wrong
figure is worse than no figure when it may reach a client bill.

Cached input is charged at the cache rate where one is configured; with no cache
rate it is charged in full, which overstates rather than flatters. Embedding
calls are not metered at all, which is an omission rather than a zero: each
draft embeds one short query, and indexing a matter embeds it once.

The current model's introductory rate ends on 31 December 2026, after which
Google's published standard rate doubles it. `config/pricing.yaml` says so, in
the place you would look when the totals jump.

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

## The firm's templates

`templates/` holds the firm's own reply templates, one markdown file each, with
frontmatter saying which situation the template governs. Their content is
Rotem's, taken from her template library; only the sign-off is removed, because
Outlook appends the real signature.

A model asked to invent a reply from a description of a house style produces
something plausible and slightly off, every time. Handing it the firm's actual
template for the genre and asking it to adapt is cheaper and lands much closer.
Her diagnostic question sets and her limits paragraphs are the product of
practice, and they are worth reusing verbatim.

The template is chosen before the drafting call, because it goes into the prompt
for that call. That rules out using the model's own classification, so selection
uses what is already known: whether the sender resolves to an open matter, that
matter's category, and the words in the email. Frontmatter fields:

- `genre` — what kind of message this answers.
- `client_type` — `existing_client`, `potential_client`, or a list. Omit for any.
- `applies_to` — matter categories. Empty means any.
- `signals` — Hebrew words that select it. Single stems work better than phrases,
  because Hebrew attaches possessives and articles: `זוג` reaches `זוגי`, whereas
  `בן זוג` does not.
- `fallback` — use when nothing else matches. Exactly one template has it.
- `defers_answers` — optional override; otherwise inferred from the genre.

Two behaviours exist because getting them wrong was worse than having no
templates at all.

A template scoped to this matter's category wins a tie, but never wins on its
own. Without that rule an email saying only "thank you" selected the
border-emergency acknowledgement, because the matter happened to be an entry
refusal.

Prior correspondence from the firm in the thread means an existing client,
whatever the address suggests. A referring agency writes about a client from an
address no `matter.yaml` lists, so the sender looks new; the first-contact
template then instructs the model to decline advising until intake, and a
substantive reply to a live matter becomes a refusal to answer. Measured on the
test thread, that dropped question coverage from five of five to none.

Every guardrail applies to a template-derived draft unchanged. A template is a
form of words, not an authority: it cannot license a legal claim, and the
verification still catches unfilled slots, a copied sign-off, forbidden wording
and ungrounded numbers.

Because the firm's templates are all intake and acknowledgement, they withhold a
substantive answer on purpose. The coverage check knows this from the genre, so
"what can be done?" going unanswered is reported as deferred rather than as a
defect. A template that does answer questions should say `defers_answers: false`.

To add a batch:

```bash
python -m tools.extract_templates "C:\path\to\folder"   # writes the stubs
python -m tools.survey_corpus "C:\path\to\folder"       # voice and calibration
```

`extract_templates` leaves the frontmatter as `TODO`, which is deliberate: only a
person can say which categories a template governs. A test fails while any
template still says `TODO`.

## Forbidden wording

The firm's Hebrew conventions list phrases it does not use: `אין מה לדאוג`,
`מובטח`, `בוודאות`, `אין בעיה`, `כפי שכבר הסברנו`, and calling a preliminary view
`חוות דעת משפטית`. The prompt passes those on, but a prompt is a request, so the
list is also enforced against the finished draft in `rotem_agent/phrases.py`.

A categorical assurance is reported as a problem and holds the draft back; a
merely brusque phrase is reported as a warning beside it. Which is which is set
per phrase in `config/forbidden_phrases.yaml`, not in code.

Two details stop the check from being either useless or annoying. Only the
client-facing draft is checked, never the internal note, which should be free to
record that nothing is guaranteed. And a phrase marked `unless_negated` is
cleared by a negator shortly before it, because `לא ניתן לקבוע בוודאות` is the
hedging the firm insists on while `בוודאות תאושר` is the wording it forbids. That
negator match respects word boundaries with an allowance for attached
conjunctions, so `ולא` negates but the `לא` inside `מלא` does not.

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
- `config/forbidden_phrases.yaml` — wording the firm does not use in client-facing
  text, with a severity per phrase. Checked against the draft in code rather than
  asked for in the prompt, because it is decidable by looking at the text. Editing
  this file needs no code change.
- `config/mailbox.yaml` — which mailbox to read and which senders may be read.
  Git-ignored; copy from `config/mailbox.example.yaml`.
- `config/matters.yaml` — the folder holding client matters. Git-ignored; point it
  outside the repository in production.
- `config/pricing.yaml` — model prices per million tokens, typed in by hand and
  applied when the usage log is read. Also where a shekel exchange rate goes, if
  you want totals in both currencies.
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
- Only the default store is read. `mailbox` in `mailbox.yaml` is compared
  against the signed-in accounts but does not select anything, so a mailbox
  added as a second account, or reached by Exchange delegation, is invisible to
  the reader while still looking correctly configured. `doctor` reports this as
  a blocking **Default mailbox** failure rather than letting it pass silently,
  but the fix is a separate Outlook profile, not a setting.
- A machine-read certificate is evidence of what the model saw, not of what the
  paper says. Transcription has been checked against known ground truth and did
  preserve a deliberate name discrepancy rather than normalising it, but that is
  one test, not a measurement. Every name and date taken from a scan needs
  checking against the original before anything is asserted from it.
- The audit gets facts about a document subtly wrong in ways the checks do not
  catch. Observed: a cell described 01.09.2026 as the date of the Authority's
  letter when it is the deadline the letter sets. The citation was right and the
  date was right; the relationship between them was not.
- The audit has no evaluation harness either, and it is a longer output than a
  draft with more room to be confidently wrong. Treat the first several as
  drafts of a checklist rather than a checklist.
- Category gating decides which procedures reach the prompt from the matter's
  `category` in `matter.yaml`. A miscategorised matter therefore silently loses
  a procedure. An unknown category keeps every procedure, so a first enquiry
  with no folder yet is covered.
- Retrieval uses one query built from the subject and body. Querying per
  extracted question would retrieve better for a message asking several
  unrelated things.
- Retrieved context can shift the model's own matter classification, which was
  observed changing from `reentry_visa` to `status_spousal` once the client's
  documents were attached. Neither is wrong for that thread, but it shows the
  excerpts influence triage and not only wording.
- Nothing summarises a document as a whole. Retrieval returns passages, so a
  question answered only by reading an entire file will not be answered well.
- Cost figures depend on prices maintained by hand in `config/pricing.yaml`, and
  embedding calls are not metered at all, so a total is an estimate rather than a
  bill. Check it against the real Google Cloud billing console before charging
  anything to a client.
