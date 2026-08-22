# Hebrew Legal Email Draft Agent — Phase 0

Generates a Hebrew reply draft for incoming law-firm email, for review by the
lawyer. Phase 0 runs entirely offline from a saved `.eml` file: no Microsoft
Graph, no vector store, no UI, and nothing is ever sent.

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
- Matter resolution, Microsoft 365 integration and signature injection are not
  implemented in Phase 0.
