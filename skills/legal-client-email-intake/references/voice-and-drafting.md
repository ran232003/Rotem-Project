# Voice and drafting

The firm's voice, taken from its own template library and from outgoing
correspondence. Match it closely; a draft that reads like generic professional
Hebrew will be rewritten every time.

Where a template exists for the genre, it is supplied with the email and it
governs. This file is the fallback, and it explains what the templates have in
common so a reply to something they do not cover still sounds like the firm.

## Structure

Observed in every template, in this order:

1. Greeting: the name, then `שלום רב,` on its own line. Name every person being
   addressed, not only the sender.
2. One line acknowledging what arrived: `תודה על פנייתך למשרדנו` for a new
   enquiry, `קיבלנו את פנייתך` for an existing client. For a matter already in
   progress, `בהמשך לשיחתנו` or `בהמשך לפנייתך`.
3. Why the firm is asking for what comes next, before asking for it. The firm
   explains the reason for a request rather than simply issuing it.
4. The substance: numbered questions, or a bulleted list of documents. This is
   the only place lists appear, and they are frequent here.
5. What happens once the client responds, and when.
6. An explicit limits paragraph. Near-universal, and the most characteristic
   feature of the firm's writing.
7. Nothing. No sign-off: Outlook appends the signature.

Length runs from about 600 to 1900 characters. A reply much shorter than that is
probably missing the limits paragraph.

## Register

Formal but not stiff, and never bureaucratic. Full sentences in the prose, though
the document and question lists are deliberately terse.

First person plural for the firm's actions, and it is the office speaking rather
than an individual: `קיבלנו`, `נבקש`, `נעדכן`, `משרדנו מכין`, `אנו בודקים`.
Second person for the client's own decisions and obligations. The lawyer is
referred to in the third person, as `עורכת הדין`, even in mail sent from her own
address.

Impersonal constructions carry instructions rather than the imperative: `יש לצרף`
and `אין להשיב` rather than `תצרף` or `אל תשיב`. `נבקש` rather than `אני מבקשת`.

## The limits paragraph

The firm systematically records what it cannot yet determine, and this is not
stylistic hedging. Reproduce the pattern with the wording that fits:

- What cannot be determined yet, and why:
  `בשלב זה, ולפני עיון מלא במסמכים ובהיסטוריית ההליך, לא ניתן לקבוע את המסלול
  המשפטי המתאים או להעריך את סיכויי ההליך`.
- What the firm will not commit to: `אין באפשרותנו להתחייב` — to a quota, a
  route, a number of workers, a decision date, or an outcome.
- Formally marked limits open with `יובהר כי`.
- Receipt is not action: `קבלת פנייתך אינה מהווה עדיין אישור שבוצעה פעולה
  משפטית`.
- Do not act alone: `אין להשיב לרשות, לחתום על מסמך, לצאת מישראל, להזמין טיסה או
  לבצע פעולה עצמאית לפני קבלת הנחיה מעורכת הדין`.
- Where a limit protects the client, say so. The firm explains that withholding a
  premature route prevents a step that could damage the case.
- Attribute discretion to the Authority rather than predicting its behaviour.

A draft that is too cautious costs an edit. A draft that is confidently wrong
costs the client's status.

## Asking for information

Between three and five questions, and only ones that change the diagnosis. The
firm's own templates carry the instruction `[להוסיף כאן רק 3–5 שאלות האבחון
הרלוונטיות לפנייה]`, which is the rule stated in its own words.

Never ask for something the incoming email already supplied. Where a document is
requested, ask for the complete one: `נבקש לצרף את המסמך המלא`.

## Never in a client draft

- A promise of approval, entry, a visa, citizenship, a timeframe from the
  Authority, or a litigation outcome.
- A new fee, a new scope of work, or a commitment to attend somewhere. Scope and
  cost are always `יתואם בנפרד`.
- A commitment to a deadline the firm has not already made. The 48-hour
  commitment for a tailored document list appears in the onboarding templates and
  may be restated from one, but never invented or adjusted.
- Internal strategy, risk assessment, negotiating limits, or chosen precedents.
- Any statement that a lawyer has personally reviewed the message.
- A sign-off. `בברכה`, `בכבוד רב`, the firm name and the lawyer's name all belong
  to the Outlook signature, which is appended after the draft.

## Wording the firm does not use

`אין מה לדאוג`, `בוודאות`, `מובטח`, `אין בעיה`, `כפי שכבר הסברנו`. A preliminary
view is never called `חוות דעת משפטית`.

These are also checked against the finished draft in code, from
`config/forbidden_phrases.yaml`, so a breach is reported rather than merely
discouraged. Certainty being denied is fine and often required: `לא ניתן לקבוע
בוודאות` is the firm's own construction.

## Language

Match the language of the incoming email. Hebrew replies are written for
right-to-left rendering; keep Latin-script terms and case numbers intact and do
not transliterate proper names. Prefer `רשות האוכלוסין וההגירה` in full.
