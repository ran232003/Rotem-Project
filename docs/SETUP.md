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

## Step 2: Install Git

Strictly optional — you can skip to the ZIP route in Step 3 — but worth the five
minutes. With Git, every future update is two lines. Without it, each update
means downloading a new copy and hand-carrying the settings across, which is
where the answered-message ledger gets forgotten and clients receive a second
reply to an email already dealt with.

Download it from
[git-scm.com/download/win](https://git-scm.com/download/win). The download
starts on its own; if it does not, click **64-bit Git for Windows Setup**.

Run the installer and **accept every default** by clicking Next through it. The
screens look intimidating and mention editors, branch names and line endings;
none of it matters here. The only screen worth a glance is the one offering
**Git from the command line and also from 3rd-party software**, which is the
default and the one you want.

Then close any PowerShell window that was already open and open a new one, or it
will not know Git exists yet. Check it worked:

```powershell
git --version
```

That should print something like `git version 2.47.1.windows.1`. If instead you
get "not recognized", the installer did not add it to the PATH — reboot and try
again, and if it still fails, use the ZIP route instead.

You do not need a GitHub account, and you never need to sign in. This project is
public and you are only ever reading from it.

## Step 3: Get the project onto the machine

With Git installed, pick a folder you can write to and clone it:

```powershell
cd $HOME\Documents
git clone https://github.com/ran232003/Rotem-Project.git
cd Rotem-Project
```

That creates `Documents\Rotem-Project` with everything in it. Later, updating is
`git pull` from inside that folder, and nothing you have configured is touched,
because the settings files are deliberately not part of the repository.

Without Git, open
[the repository](https://github.com/ran232003/Rotem-Project), click the green
**Code** button, choose **Download ZIP**, and unzip it. Right-click the
downloaded file, choose **Extract All**, and point it at your Documents folder.

Either way, put the folder somewhere your own user account can write to, such as
`C:\Users\<you>\Documents`. Do not put it in `Program Files`; Windows blocks
writing there and the agent needs to save its drafts and logs.

## Step 4: Run the setup script

Open PowerShell, move into the folder, and run:

```powershell
cd $HOME\Documents\Rotem-Project
powershell -ExecutionPolicy Bypass -File setup.ps1
```

It creates a private Python environment inside the folder, installs everything
needed, creates the two settings files from their examples, and puts two icons on
the desktop: a green **סוכן הטיוטות**, which opens the dashboard, and a red
**כיבוי הסוכן**, which turns the agent off without it. It is safe to run again if
something goes wrong; it never overwrites settings you have already filled in.

The green icon is how the agent gets used day to day, but it will not work until
the settings in the next step are filled in.

## Step 5: Fill in the settings

Two files need real values. Open them in Notepad.

**`.env`** — paste the Gemini key after the equals sign, with no quotes and no
spaces:

```
GEMINI_API_KEY=AIza...your-key-here
GEMINI_MODEL=gemini-3.6-flash
```

**`config\mailbox.yaml`** — the mailbox being worked on, and the senders the
agent is allowed to read:

```yaml
mailbox: rotem@law-fr.co.il
allowed_senders:
  - first.client@example.com

start_date: 2026-08-20
```

`mailbox` must be the address Outlook on this machine is signed in to. It does
not choose anything: the agent reads whatever mailbox Outlook opens by default,
and this line exists so `doctor` can tell you when the two disagree. Setting it
to some other mailbox will not make the agent read that mailbox. It can also be
changed from the dashboard later, where it is checked against Outlook before
being saved.

`allowed_senders` is a hard boundary, not a preference. The agent refuses to
read any message from anyone not on this list, which is what makes it safe to
point at a real mailbox holding years of unrelated correspondence. Start with a
single address you are happy to experiment on, and add more once you trust it.
Once it is running, this list can be edited from the dashboard instead of here.

`start_date` is the day the agent starts work. Mail that arrived before it is
left alone permanently, so switching the agent on does not produce a draft reply
to every old thread in a client's history. Set it to today, or to the day you
want it to begin from. Write it as `2026-08-20` or `20.08.2026`; the day is read
in local time, so mail from 00:30 that morning counts. Delete the line entirely
and there is no floor at all, which is rarely what you want on a real mailbox.

`config\firm.yaml` should already be correct, but check that the name and the
addresses are right, since that is how the agent recognises the lawyer's own
messages inside a quoted thread.

## Step 6: Check the machine

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

## Step 7: Draft from the sample email

This uses a test email included with the project. It does not touch real mail.

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli draft samples\anna_reentry_visa.eml
```

Open `out\draft.html` in a browser to read the result in proper right-to-left
Hebrew, and `out\internal_note.md` for the reasoning, the open questions and
anything the agent flagged for the lawyer's attention.

## Step 8: Draft a reply to a real email

Still without writing anything into Outlook:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli outlook-draft --sender first.client@example.com
```

The sender has to be on the allowlist from Step 5. Read `out\draft.html`. When
you are happy, add `--save` to place the reply in the Drafts folder as a proper
threaded reply:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli outlook-draft --sender first.client@example.com --save
```

It appears in Drafts tagged **AI draft** so it is obvious in the folder list.
It is not sent. Note that the draft deliberately has no sign-off, because
Outlook appends the firm's signature when the draft is opened.

## Step 9: Let it watch for new mail

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
leave it alone. Closing it closes the dashboard, not the agent; the agent is
launched detached precisely so that it survives, and it keeps running until it is
switched off. Reopening the icon shows the same agent, not a second one.

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

### Stopping it without the dashboard

The red **כיבוי הסוכן** icon stops the agent on its own, for the case where the
page will not open at all. It shows a short message saying what happened and asks
before resorting to force. Pressing it when nothing is running is harmless — it
says so and does nothing.

The same thing from a terminal, which reports in English:

```powershell
.venv\Scripts\python.exe -m rotem_agent.cli stop
.venv\Scripts\python.exe -m rotem_agent.cli stop --force   # only if it will not answer
```

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

## Updating to a newer version

Six things are deliberately not in the repository, because they hold either
secrets or privileged material: `.env`, `config\mailbox.yaml`,
`config\matters.yaml`, and the `state\`, `logs\` and `clients\` folders. Nothing
that arrives from GitHub can overwrite them, which is what makes updating in
place safe.

If the project was cloned with Git, an update is two lines:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` is safe to re-run: it reuses the existing environment, installs only
what is missing, never touches a settings file that has been filled in, and
refreshes the desktop icon. Turn the agent off from the dashboard first, so it is
not running old code halfway through.

If it was downloaded as a ZIP, unzip the new copy **next to** the old folder
rather than over it. Then, from inside the new folder, point `update.ps1` at the
old one:

```powershell
powershell -ExecutionPolicy Bypass -File update.ps1 -From "C:\Users\<you>\Documents\old-copy"
```

That carries over the five things worth keeping — `.env`, both YAML settings
files, and the `state\` and `clients\` folders — and then runs `setup.ps1` for
you. Add `-DryRun` first to see what it would move without moving anything. The
old `logs\` folder is left behind deliberately; it is only a diagnostic
transcript, and a new one starts on the next run.

It never overwrites a file already present in the new folder, so running it twice
is safe. It also checks afterwards that `state\ledger.json` came across and says
so loudly if it did not: that file is the record of which emails have already
been answered, and without it the agent drafts a second reply to every one of
them. Doing this copy by hand is where that gets forgotten, which is why the
script exists.

Delete the old folder once a draft has worked.

A new version needs new packages only if `requirements.txt` changed. Re-running
`setup.ps1` settles that either way, so there is no need to check.

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
