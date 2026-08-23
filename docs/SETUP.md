# Setting up on the lawyer's machine

This installs the drafting agent on the computer where Outlook is already signed
in. Nothing here needs a password to be shared with anyone: the agent talks to
the copy of Outlook that is already open and logged in on this machine.

**The agent never sends email.** It writes replies into the Drafts folder and
stops. Every draft waits for a human to read, change and send it.

Allow about half an hour, most of which is waiting for downloads.

**Once it is set up, using it is one thing:** double-click the green envelope
icon on the desktop, **סוכן הטיוטות**, and turn the switch on. Everything below
is the one-time installation.

The day-to-day guide for the lawyer herself is [`USAGE-he.md`](USAGE-he.md), in
Hebrew. Hand her that one, not this one.

---

## Before you start

Five things decide whether this will work. Check them first, because two of
them are hard blockers.

**1. Which Outlook is it?** Open Outlook and look at the top of the window. If
there is a toggle labelled **New Outlook** in the top-right corner, switch it
**off** to go back to classic Outlook. The new Outlook cannot be automated at
all, so the agent cannot read mail or create drafts there. Classic Outlook is
required.

**2. Can you install software?** Installing Python needs permission to install
programs. On a machine managed by an IT provider you may need them to do it.

**3. Is there a Gemini API key?** The agent sends each email to Google's Gemini
model to write the reply. You need a key from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey), and someone
has to own the billing for it. Roughly 2.5 cents per draft, so a hundred
emails a month is about £2.

**4. Is everyone comfortable with the data going to Google?** Client emails,
and any client documents the agent is pointed at, leave the machine and go to
Google's API. That is a confidentiality decision for the firm to make
deliberately, not a technical detail. Settle it before the first real email.

**5. Where do client documents live?** Optional at first. The agent can read a
folder per client matter, but it drafts perfectly well without one.

---

## Step 1: Install Python

Download it from [python.org/downloads](https://www.python.org/downloads/) and
run the installer.

On the very first screen, tick **Add python.exe to PATH** at the bottom. This
is easy to miss and everything afterwards fails without it. Then click
**Install Now**.

## Step 2: Get the project onto the machine

Either download it as a ZIP from GitHub and unzip it, or, if Git is installed:

```powershell
git clone https://github.com/<owner>/legal-email-agent.git
```

Put the folder somewhere your own user account can write to, such as
`C:\Users\<you>\Documents\legal-email-agent`. Do not put it in `Program Files`;
Windows blocks writing there and the agent needs to save its drafts and logs.

## Step 3: Run the setup script

Open PowerShell, move into the folder, and run:

```powershell
cd C:\Users\<you>\Documents\legal-email-agent
powershell -ExecutionPolicy Bypass -File setup.ps1
```

It creates a private Python environment inside the folder, installs everything
needed, creates the two settings files from their examples, and puts an icon on
the desktop named **סוכן הטיוטות**. It is safe to run again if something goes
wrong; it never overwrites settings you have already filled in.

The icon is how the agent gets used day to day, but it will not work until the
settings in the next step are filled in.

## Step 4: Fill in the settings

Two files need real values. Open them in Notepad.

**`.env`** — paste the Gemini key after the equals sign, with no quotes and no
spaces:

```
GEMINI_API_KEY=AIza...your-key-here
GEMINI_MODEL=gemini-3.6-flash
```

**`config\mailbox.yaml`** — the mailbox to read, and the senders the agent is
allowed to read:

```yaml
mailbox: rotem@law-fr.co.il
allowed_senders:
  - first.client@example.com
```

`allowed_senders` is a hard boundary, not a preference. The agent refuses to
read any message from anyone not on this list, which is what makes it safe to
point at a real mailbox holding years of unrelated correspondence. Start with a
single address you are happy to experiment on, and add more once you trust it.

`config\firm.yaml` should already be correct, but check that the name and the
addresses are right, since that is how the agent recognises the lawyer's own
messages inside a quoted thread.

## Step 5: Check the machine

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli doctor --online
```

This prints a line per check. Anything marked `FAIL` comes with a line saying
what to do about it. Fix those, run it again, and carry on when it says
everything checks out.

The check most likely to catch you out is **Default mailbox**. The agent only
reads the mailbox that Outlook opens on by default. If the firm's mailbox was
added as a *second* account alongside another one, the agent cannot see it and
will silently find nothing. The fix is an Outlook profile whose primary account
is the firm mailbox.

## Step 6: Draft from the sample email

This uses a test email included with the project. It does not touch real mail.

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli draft samples\anna_reentry_visa.eml
```

Open `out\draft.html` in a browser to read the result in proper right-to-left
Hebrew, and `out\internal_note.md` for the reasoning, the open questions and
anything the agent flagged for the lawyer's attention.

## Step 7: Draft a reply to a real email

Still without writing anything into Outlook:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli outlook-draft --sender first.client@example.com
```

The sender has to be on the allowlist from Step 4. Read `out\draft.html`. When
you are happy, add `--save` to place the reply in the Drafts folder as a proper
threaded reply:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli outlook-draft --sender first.client@example.com --save
```

It appears in Drafts tagged **AI draft** so it is obvious in the folder list.
It is not sent. Note that the draft deliberately has no sign-off, because
Outlook appends the firm's signature when the draft is opened.

## Step 8: Let it watch for new mail

Once the drafts are consistently good, the agent can watch the mailbox and draft
a reply to each new message from an allowed sender, once and only once.

The easy way is the dashboard. Setup put a green envelope icon named **סוכן
הטיוטות** on the desktop — double-click it. A page opens in the browser with a
switch to turn the agent on and off, and figures for how many emails have been
answered, how many of those replies were actually sent, and what it has cost.

The first click takes a few seconds while it starts up. Double-clicking the icon
again when the dashboard is already open just brings the page back, so there is
no harm in it.

A small console window appears in the taskbar. That window *is* the dashboard —
leave it alone. Closing it closes the dashboard, not the agent; the agent keeps
running until it is switched off from the page.

If the icon is missing, run `setup.ps1` again, or double-click **`dashboard.bat`**
in the project folder, which is exactly what the icon points at.

Outlook must stay open for the agent to work at all.

If you prefer the command line, this does the same thing without the page:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli outlook-watch --save --interval 60
```

### About the switch

Turning the agent off is a request, not a kill. If it is halfway through writing
a reply it finishes that one first, which normally takes a second or two. This
is deliberate: interrupting it could leave half a reply sitting in Drafts.

Very occasionally the agent will not respond to the request, usually because it
was left running from before an update. After a minute and a half the page
offers a forced shutdown, which should be used only then.

### About the sent figures

"Sent" counts threads where a reply actually went out after the agent drafted
one. A reply rewritten from scratch still counts, because the question being
answered is whether the draft was a useful starting point or was thrown away.
The figure is a snapshot and the page says when it was last taken; the refresh
button under the table takes a new one.

---

## When something goes wrong

Run the check again first, since it names most problems directly:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli doctor --online
```

Full detail of every run, including errors, is written to `logs\agent.log`.

A few specific symptoms:

**"Cannot reach Outlook over COM"** — Outlook is closed, or it is the new
Outlook. Open the classic desktop app and leave it running.

**The agent finds no messages from a client who has definitely written** —
either that address is not in `allowed_senders`, or the mailbox is not the
default one in the Outlook profile. The `doctor` output tells you which.

**Everything is slow the first time** — the first draft of the day pays for
loading the model. Around forty seconds per draft is normal.

To see what has been spent:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli usage
```

---

## Letting Claude Code do the work

Claude Code can drive all of this. Open the project folder in it and paste:

> Set up this project on my machine by following `docs/SETUP.md`. I am on
> Windows and not a programmer, so explain each step in plain language before
> you run it, and stop and ask me if anything needs a decision. Start by
> running `setup.ps1`, then `python -m rotem_agent.cli doctor` and work through
> whatever it reports as failing.

Two things it cannot do for you. It cannot sign Outlook in, because that needs
the password and whatever second factor the account uses. And do not paste the
Gemini API key into the chat; type it straight into the `.env` file yourself,
so it stays out of any transcript.

Everything else — installing the packages, filling in the YAML, reading the
`doctor` output and fixing what it complains about — it can handle.
