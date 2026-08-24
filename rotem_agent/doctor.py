"""Environment checks for a fresh install.

Setting this up on the lawyer's own machine fails in a dozen small ways that all
present as the same unhelpful traceback: no key, no Outlook, the new Outlook
instead of the classic one, a mailbox that is signed in but is not the default
store. Each check below answers one of those questions on its own and says what
to do about it, so a non-technical user can read the output and act on it.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from rotem_agent.config import CONFIG_DIR, PROJECT_ROOT, read_yaml

OK = "ok"
WARN = "warn"
FAIL = "fail"

MIN_PYTHON = (3, 11)

_REQUIRED = [
    ("google.genai", "google-genai"),
    ("dotenv", "python-dotenv"),
    ("yaml", "PyYAML"),
    ("bs4", "beautifulsoup4"),
    ("lxml", "lxml"),
    ("pypdf", "pypdf"),
    ("docx", "python-docx"),
    ("numpy", "numpy"),
    ("PIL", "Pillow"),
]

_WINDOWS_ONLY = [("win32com.client", "pywin32")]

_INSTALL_HINT = "python -m pip install -r requirements.txt"

# An authentication failure is final; a transport failure usually is not. Only
# the first should stop the install.
_AUTH_MARKERS = (
    "api key",
    "api_key",
    "unauthenticated",
    "permission_denied",
    "permission denied",
    "invalid_argument",
    "401",
    "403",
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def check_python() -> Check:
    version = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info < MIN_PYTHON:
        wanted = ".".join(str(p) for p in MIN_PYTHON)
        return Check(
            "Python version",
            FAIL,
            f"running {version}, need {wanted} or later",
            "Install Python 3.11+ from python.org, ticking 'Add python.exe to PATH'.",
        )
    return Check("Python version", OK, version)


def check_dependencies() -> list[Check]:
    wanted = list(_REQUIRED)
    if sys.platform == "win32":
        wanted += _WINDOWS_ONLY

    missing = []
    for module, package in wanted:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(package)

    if missing:
        return [
            Check(
                "Python packages",
                FAIL,
                f"not installed: {', '.join(missing)}",
                f"Run: {_INSTALL_HINT}",
            )
        ]
    return [Check("Python packages", OK, f"{len(wanted)} present")]


def check_env(root: Path | None = None) -> list[Check]:
    base = root or PROJECT_ROOT
    checks: list[Check] = []

    env_file = base / ".env"
    if env_file.exists():
        checks.append(Check("Key file (.env)", OK, str(env_file)))
    else:
        checks.append(
            Check(
                "Key file (.env)",
                FAIL,
                "not found",
                "Copy .env.example to .env, then paste the Gemini key after GEMINI_API_KEY=.",
            )
        )

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        checks.append(Check("Gemini API key", OK, f"set, {len(key)} characters"))
    else:
        checks.append(
            Check(
                "Gemini API key",
                FAIL,
                "GEMINI_API_KEY is empty",
                "Get a key from aistudio.google.com/apikey and put it in .env.",
            )
        )

    checks.append(Check("Model", OK, os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()))
    return checks


def check_model_reachable() -> Check:
    """Confirm the key is accepted, without spending tokens on a generation."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return Check("Gemini reachable", FAIL, "skipped, no key set")

    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
    try:
        from google import genai

        # Bound to a name deliberately: the SDK closes its transport when the
        # client is collected, and a temporary can be collected mid-request.
        client = genai.Client(api_key=key)
        client.models.get(model=model)
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if any(marker in lowered for marker in _AUTH_MARKERS):
            return Check(
                "Gemini reachable",
                FAIL,
                f"the API rejected the request: {message[:180]}",
                "Check the key is correct and that the model name in .env exists.",
            )
        return Check(
            "Gemini reachable",
            WARN,
            f"could not reach the API: {message[:180]}",
            "Usually a network or proxy problem. Retry, or check the firewall.",
        )
    return Check("Gemini reachable", OK, f"{model} answered")


def _start_date_check(value: object, path: Path) -> Check:
    """A date the agent will not look before, if one is set.

    Reported even when absent, because the difference between "configured to
    ignore old mail" and "ignoring old mail for reasons nobody understands" is
    the whole value of saying so.
    """
    from datetime import datetime, timezone

    from rotem_agent.outlook.com import parse_start_date

    if value is None or (isinstance(value, str) and not value.strip()):
        return Check(
            "Start date",
            WARN,
            "not set, so old mail is limited only by --backlog-days",
            "Set start_date in config/mailbox.yaml to the day the agent starts "
            "work, or old threads may get replies when it is first turned on.",
        )

    try:
        floor = parse_start_date(value, path)
    except Exception as exc:
        return Check("Start date", FAIL, str(exc), "Write it as 2026-08-20 or 20.08.2026.")

    if floor > datetime.now(timezone.utc):
        return Check(
            "Start date",
            FAIL,
            f"{floor.astimezone():%d.%m.%Y} is in the future, so nothing will be drafted",
            "Set it to today or earlier.",
        )
    return Check("Start date", OK, f"mail from {floor.astimezone():%d.%m.%Y} onwards")


def check_configs(config_dir: Path | None = None) -> list[Check]:
    base = config_dir or CONFIG_DIR
    checks: list[Check] = []

    firm = base / "firm.yaml"
    try:
        data = read_yaml(firm)
        addresses = [str(a).strip() for a in data.get("addresses", []) if str(a).strip()]
        name = str(data.get("lawyer_name", "")).strip()
        if not addresses:
            checks.append(
                Check(
                    "Firm identity",
                    FAIL,
                    "firm.yaml lists no addresses",
                    "Add every address the lawyer sends from, so her own replies are "
                    "recognised in a quoted thread.",
                )
            )
        else:
            checks.append(Check("Firm identity", OK, f"{name or 'unnamed'}, {len(addresses)} address(es)"))
    except Exception as exc:
        checks.append(Check("Firm identity", FAIL, str(exc), "Restore config/firm.yaml."))

    mailbox = base / "mailbox.yaml"
    if not mailbox.exists():
        checks.append(
            Check(
                "Mailbox config",
                FAIL,
                "config/mailbox.yaml not found",
                "Copy config/mailbox.example.yaml to config/mailbox.yaml, set 'mailbox' "
                "to her address and list the senders the agent may read.",
            )
        )
    else:
        try:
            data = read_yaml(mailbox)
            address = str(data.get("mailbox", "")).strip()
            senders = [str(s).strip() for s in data.get("allowed_senders", []) if str(s).strip()]
            if not address:
                checks.append(
                    Check("Mailbox config", FAIL, "'mailbox' is empty", "Set it to her email address.")
                )
            elif not senders:
                checks.append(
                    Check(
                        "Mailbox config",
                        FAIL,
                        "allowed_senders is empty",
                        "List at least one client address. The agent refuses to scan a "
                        "whole mailbox without it.",
                    )
                )
            elif "example.com" in address.lower():
                checks.append(
                    Check(
                        "Mailbox config",
                        FAIL,
                        f"still the example address: {address}",
                        "Replace it with her real address.",
                    )
                )
            else:
                checks.append(
                    Check("Mailbox config", OK, f"{address}, {len(senders)} allowed sender(s)")
                )
                checks.append(_start_date_check(data.get("start_date"), mailbox))
        except Exception as exc:
            checks.append(Check("Mailbox config", FAIL, str(exc), "Fix the YAML syntax."))

    matters = base / "matters.yaml"
    if not matters.exists():
        checks.append(
            Check(
                "Client files",
                WARN,
                "config/matters.yaml not found",
                "Optional at first. Copy matters.example.yaml when you want the agent "
                "to read client documents.",
            )
        )
    else:
        try:
            from rotem_agent.matters.registry import load_matters_root

            root = load_matters_root(matters)
            if root.exists():
                folders = [p for p in root.iterdir() if p.is_dir()]
                checks.append(Check("Client files", OK, f"{root}, {len(folders)} matter folder(s)"))
            else:
                checks.append(
                    Check(
                        "Client files",
                        WARN,
                        f"root does not exist: {root}",
                        "Create the folder, or point 'root' at where the client folders live.",
                    )
                )
        except Exception as exc:
            checks.append(Check("Client files", WARN, str(exc)))

    return checks


def check_writable(root: Path | None = None) -> list[Check]:
    base = root or PROJECT_ROOT
    checks = []
    for name in ("out", "logs", "state"):
        target = base / name
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".doctor-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks.append(Check(f"Writable {name}/", OK, str(target)))
        except Exception as exc:
            checks.append(
                Check(
                    f"Writable {name}/",
                    FAIL,
                    str(exc),
                    "Move the project somewhere the user can write, such as Documents. "
                    "Program Files will not work.",
                )
            )
    return checks


def check_templates(root: Path | None = None) -> Check:
    base = (root or PROJECT_ROOT) / "templates"
    if not base.exists():
        return Check("Firm templates", WARN, "templates/ not found", "Re-clone the repository.")
    count = len(list(base.glob("*.md")))
    if count == 0:
        return Check("Firm templates", WARN, "no templates found")
    return Check("Firm templates", OK, f"{count} template(s)")


def check_outlook() -> list[Check]:
    """Reach Outlook the same way the connector does, and check the default store.

    The default store matters more than it looks. A mailbox added as a second
    account is listed in Accounts and passes a naive check, but the reader only
    ever walks the default store, so the agent would quietly scan the wrong
    mailbox and report that the client has never written.
    """
    if sys.platform != "win32":
        return [Check("Outlook", WARN, f"not Windows ({sys.platform}), the connector is unavailable")]

    try:
        import win32com.client
    except Exception:
        return [
            Check(
                "Outlook",
                FAIL,
                "pywin32 is not installed",
                f"Run: {_INSTALL_HINT}",
            )
        ]

    try:
        app = win32com.client.Dispatch("Outlook.Application")
        namespace = app.GetNamespace("MAPI")
    except Exception as exc:
        return [
            Check(
                "Outlook",
                FAIL,
                f"cannot reach Outlook over COM: {str(exc)[:160]}",
                "Open the classic Outlook desktop app and leave it running. The new "
                "Outlook for Windows has no COM support and cannot be driven at all.",
            )
        ]

    checks = [Check("Outlook", OK, "reachable over COM")]

    accounts: list[str] = []
    try:
        accounts = [str(a.SmtpAddress) for a in namespace.Accounts if a.SmtpAddress]
    except Exception as exc:
        checks.append(Check("Outlook accounts", WARN, f"could not list accounts: {str(exc)[:120]}"))

    if accounts:
        checks.append(Check("Outlook accounts", OK, ", ".join(accounts)))
    else:
        checks.append(
            Check(
                "Outlook accounts",
                FAIL,
                "no account is signed in",
                "Add the mailbox to Outlook and let it finish synchronising.",
            )
        )

    default_address = _default_store_address(namespace, accounts)
    configured = _configured_mailbox()

    if not configured:
        checks.append(Check("Default mailbox", WARN, "nothing configured to compare against"))
    elif default_address is None:
        checks.append(
            Check(
                "Default mailbox",
                WARN,
                "could not identify the default mailbox",
                f"Confirm by hand that Outlook opens on {configured}.",
            )
        )
    elif default_address.lower() == configured.lower():
        checks.append(Check("Default mailbox", OK, default_address))
    else:
        checks.append(
            Check(
                "Default mailbox",
                FAIL,
                f"Outlook opens on {default_address}, but mailbox.yaml says {configured}",
                "The agent only reads the default mailbox. Use an Outlook profile whose "
                "primary account is the configured one, or change mailbox.yaml to match.",
            )
        )

    try:
        drafts = namespace.GetDefaultFolder(16)  # olFolderDrafts
        checks.append(Check("Drafts folder", OK, str(drafts.Name)))
    except Exception as exc:
        checks.append(
            Check(
                "Drafts folder",
                FAIL,
                str(exc)[:160],
                "The agent writes replies here, so it must be reachable.",
            )
        )

    return checks


def _configured_mailbox() -> str:
    try:
        return str(read_yaml(CONFIG_DIR / "mailbox.yaml").get("mailbox", "")).strip()
    except Exception:
        return ""


def _default_store_address(namespace, accounts: list[str]) -> str | None:
    """Match the default store back to the account that delivers into it."""
    try:
        default_store = namespace.GetDefaultFolder(6).Store  # olFolderInbox
        store_name = str(default_store.DisplayName)
    except Exception:
        return accounts[0] if accounts else None

    try:
        for account in namespace.Accounts:
            delivery = getattr(account, "DeliveryStore", None)
            if delivery is not None and str(delivery.DisplayName) == store_name:
                return str(account.SmtpAddress)
    except Exception:
        pass

    # Exchange often names the store after the address itself.
    for address in accounts:
        if address.lower() == store_name.lower():
            return address
    return accounts[0] if accounts else None


def run_all(*, online: bool = False, skip_outlook: bool = False) -> list[Check]:
    checks: list[Check] = [check_python()]
    checks += check_dependencies()
    checks += check_env()
    if online:
        checks.append(check_model_reachable())
    checks += check_configs()
    checks.append(check_templates())
    checks += check_writable()
    if not skip_outlook:
        checks += check_outlook()
    return checks


_MARK = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}


def format_report(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    lines = []
    for check in checks:
        lines.append(f"[{_MARK[check.status]}] {check.name.ljust(width)}  {check.detail}")
        if check.fix and check.status != OK:
            lines.append(f"{' ' * (width + 11)}-> {check.fix}")

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    lines.append("")
    if failed:
        lines.append(f"{len(failed)} blocking problem(s), {len(warned)} warning(s).")
        lines.append("Fix the FAIL lines above, then run this again.")
    elif warned:
        lines.append(f"Ready, with {len(warned)} warning(s) that will not stop a draft.")
    else:
        lines.append("Everything checks out. The agent is ready to draft.")
    return "\n".join(lines)
