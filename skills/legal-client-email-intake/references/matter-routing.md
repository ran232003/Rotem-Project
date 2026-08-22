# Matter routing

Classify into exactly one primary category. Where two apply, pick the one that
governs the nearest deadline.

| Category | Hebrew | Typical signals | Default urgency |
| --- | --- | --- | --- |
| `status_spousal` | הליך מדורג על בסיס קשר זוגי | B/1 permit, genuineness of relationship, centre of life, annual renewal, route to A5 | prompt |
| `asylum` | בקשת מקלט | open or withdrawn asylum claim, RSD interview, conflicting tracks | prompt |
| `reentry_visa` | אשרת חוזר | travel while a status process is pending, document collection abroad | urgent |
| `entry_refusal` | סירוב כניסה | refusal at the border, detention at the airport, removal | emergency |
| `foreign_expert` | מומחה זר | employer sponsorship, work permit, quota, salary threshold | prompt |
| `elderly_parent` | הורה קשיש | dependent parent of a resident or citizen, humanitarian grounds | routine |
| `citizenship` | אזרחות | naturalisation, Law of Return, citizenship by descent, revocation | routine |
| `family` | דיני משפחה | marriage, divorce, custody, maintenance interacting with status | prompt |
| `inheritance` | ירושה | probate, succession order, estate with a foreign element | routine |
| `admin` | אדמיניסטרטיבי | scheduling, fees, invoices, document logistics | routine |
| `not_a_matter` | לא רלוונטי | newsletters, marketing, automated notices | routine |

## Facts to extract on every matter

Deadlines and their source, current physical location, current status or permit
type and its expiry, nationality, family relationship relied upon, prior
decisions by the Authority and their dates, upcoming travel or hearings, and
the outcome the sender is actually asking for.

Record each as client-stated or firm-verified. Never promote a client-stated
fact to a verified one without a document.

## Routing consequences

- `entry_refusal` and any matter with a deadline inside 72 hours go to the
  principal lawyer, never to a standard draft.
- `asylum` combined with `reentry_visa` is a known conflicting-track situation:
  the interaction between the two must be treated as a legal proposition
  requiring a source, not as general knowledge.
- `admin` and `not_a_matter` do not need a substantive legal draft.
