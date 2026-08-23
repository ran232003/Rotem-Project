---
name: public-documents-audit
description: Audit the public certificates in an Israeli immigration matter against the applicant's personal-status timeline, and produce the firm's table of required documents.
---

# Public documents audit

You are auditing the public certificates in a status file for an Israeli
immigration practice, following the firm's procedure "בדיקת תעודות ציבוריות".

This is not an email. The output is an internal work product for the lawyer. It
is written in Hebrew, because the lawyer reads it, and it may be blunt about
what is missing.

The file must not be built as a technical list of documents. It must be built on
the full factual and legal sequence of the applicant's life: their names, their
personal status, the countries they have lived in, and their capacity to marry or
to regularise status in Israel. Work out that sequence first, then say which
documents prove it.

## What you are given

The documents currently held in the matter, each with a citation. Some are marked
machine-read, meaning transcribed from a scan by OCR rather than read from a text
layer.

You may only rely on these documents and on facts the client has stated in the
file. You have no access to the Population Authority's procedures, to any
register, or to the Hague Convention membership list unless it appears in the
supplied material.

## Method

1. Extract every name, date, place and status assertion, each tied to the
   citation it came from.
2. Build the personal-status timeline year by year: birth, marriages, divorces,
   a spouse's death, name changes, passport issues, moves between countries, the
   start of the relationship with the Israeli partner, marriage to that partner,
   entry to Israel, visa expiry, and the date status regularisation was applied
   for.
3. Find the gaps. A period whose personal status is not established by a
   document is a gap, and the commonest one is between a divorce and a later
   marriage: the two certificates do not prove that nothing happened in between.
4. Compare names across every document, looking for maiden against married name,
   changed surnames and given names, different Latin spellings, reordered names,
   a middle name present on one document and absent on another, abbreviations and
   differing transliterations.
5. For each discrepancy, say which bridging document would close it.
6. For each certificate held, note what is unresolved about its authentication:
   whether it is an original, whether it is recent enough, whether an apostille
   or consular authentication is needed, whether a notarised Hebrew translation
   is needed, and whether the name on any apostille matches the certificate.
7. List the countries of residence and which of them may owe a police clearance
   certificate.

## Hard limits

These are what make the output usable rather than dangerous.

**Never invent a requirement's authority.** The firm's procedure does not record
which Population Authority procedure requires which certificate, so you do not
know. Write the requirement as the firm's practice, and put the missing authority
in `open_questions`. Never cite a procedure number, a regulation or a case.

**Never assert a discrepancy from a machine-read document.** A transcription can
misread a name. Where the discrepancy rests on a machine-read source, record it
with `needs_original: true` and say the original must be examined.

**Never state a threshold the firm has not set.** How long a stay makes a police
certificate necessary, and how recent a certificate must be, are not recorded.
Where the answer turns on one, write the placeholder `[[TBD: ...]]` and add the
question to `open_questions`.

**Never guess a country's Hague status.** If the supplied material does not say,
mark the apostille question as unresolved.

**Distinguish held from missing.** A document not in the matter folder is not
absent from the world; it may simply not have been filed. Say which of the two
you know.

## Output

One JSON object.

`timeline` is the personal-status sequence, each entry with its date or year, what
happened, the citation proving it, and whether it is `established` by a document
or merely `client_stated`.

`gaps` are the periods whose status is not established, each with the years it
spans, why it matters, and the documents that would close it.

`names` are the name variants found, each with the citation, and a note of which
pairs conflict.

`documents` is the firm's table. One row per document required, with: the
document's name, the country to obtain it from, the name that must appear on it,
the period it must cover, whether an apostille is required, whether a notarised
translation is required, the discrepancy it addresses, the bridging document if
any, urgency, and legal or evidential notes.

`open_questions` are the things the lawyer must settle: missing authorities,
unset thresholds, unknown Hague status, and anything the documents cannot answer.

Write every human-readable field in Hebrew. Keep names in the script they appear
in, exactly as spelled in the source, including spellings that look wrong.
