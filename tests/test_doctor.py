"""The setup checks have to be right about a machine they are diagnosing.

A false 'ok' is worse than no check at all, because it sends someone looking for
the problem somewhere else.
"""

from __future__ import annotations

import sys

from rotem_agent.doctor import (
    FAIL,
    OK,
    WARN,
    Check,
    check_configs,
    check_env,
    check_python,
    check_templates,
    check_writable,
    format_report,
)

_FIRM = """
lawyer_name: רותם פרגון
firm_name: משרד עורכי דין
addresses:
  - rotem@law-fr.co.il
"""

_MAILBOX = """
mailbox: rotem@law-fr.co.il
allowed_senders:
  - client@example.org
"""


def _config_dir(tmp_path, *, firm=_FIRM, mailbox=_MAILBOX, matters=None):
    base = tmp_path / "config"
    base.mkdir()
    if firm is not None:
        (base / "firm.yaml").write_text(firm, encoding="utf-8")
    if mailbox is not None:
        (base / "mailbox.yaml").write_text(mailbox, encoding="utf-8")
    if matters is not None:
        (base / "matters.yaml").write_text(matters, encoding="utf-8")
    return base


def _named(checks, name):
    return next(c for c in checks if c.name == name)


def test_the_running_interpreter_is_new_enough():
    assert check_python().status == OK


def test_a_good_config_passes(tmp_path):
    checks = check_configs(_config_dir(tmp_path))
    assert _named(checks, "Firm identity").status == OK
    assert _named(checks, "Mailbox config").status == OK


def test_a_missing_mailbox_file_is_blocking(tmp_path):
    checks = check_configs(_config_dir(tmp_path, mailbox=None))
    check = _named(checks, "Mailbox config")
    assert check.status == FAIL
    assert "mailbox.example.yaml" in check.fix


def test_the_untouched_example_address_is_blocking(tmp_path):
    """Copying the example and forgetting to edit it must not look like success."""
    mailbox = "mailbox: you@example.com\nallowed_senders:\n  - client@example.com\n"
    checks = check_configs(_config_dir(tmp_path, mailbox=mailbox))
    assert _named(checks, "Mailbox config").status == FAIL


def test_an_empty_allowlist_is_blocking(tmp_path):
    """Without it the agent would be free to read an entire firm mailbox."""
    mailbox = "mailbox: rotem@law-fr.co.il\nallowed_senders: []\n"
    check = _named(check_configs(_config_dir(tmp_path, mailbox=mailbox)), "Mailbox config")
    assert check.status == FAIL
    assert "allowed_senders" in check.detail


def test_a_firm_with_no_addresses_is_blocking(tmp_path):
    firm = "lawyer_name: רותם פרגון\nfirm_name: משרד\naddresses: []\n"
    assert _named(check_configs(_config_dir(tmp_path, firm=firm)), "Firm identity").status == FAIL


def test_missing_client_files_only_warn(tmp_path):
    """Documents are optional; the agent drafts without them."""
    checks = check_configs(_config_dir(tmp_path))
    assert _named(checks, "Client files").status == WARN


def test_a_matters_root_that_does_not_exist_warns(tmp_path):
    matters = f"root: {tmp_path / 'nowhere'}\n"
    checks = check_configs(_config_dir(tmp_path, matters=matters))
    assert _named(checks, "Client files").status == WARN


def test_a_present_matters_root_passes(tmp_path):
    root = tmp_path / "clients"
    (root / "anna-cohen").mkdir(parents=True)
    checks = check_configs(_config_dir(tmp_path, matters=f"root: {root}\n"))
    check = _named(checks, "Client files")
    assert check.status == OK
    assert "1 matter folder" in check.detail


def test_a_missing_key_is_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    check = _named(check_env(tmp_path), "Gemini API key")
    assert check.status == FAIL
    assert "aistudio" in check.fix


def test_a_present_key_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    assert _named(check_env(tmp_path), "Gemini API key").status == OK


def test_a_missing_env_file_is_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    assert _named(check_env(tmp_path), "Key file (.env)").status == FAIL


def test_the_output_folders_are_created_if_absent(tmp_path):
    checks = check_writable(tmp_path)
    assert all(c.status == OK for c in checks)
    for name in ("out", "logs", "state"):
        assert (tmp_path / name).is_dir()


def test_missing_templates_only_warn(tmp_path):
    assert check_templates(tmp_path).status == WARN


def test_the_report_shows_a_fix_for_failures_only():
    report = format_report(
        [
            Check("Good thing", OK, "fine", "never shown"),
            Check("Bad thing", FAIL, "broken", "do this instead"),
        ]
    )
    assert "do this instead" in report
    assert "never shown" not in report
    assert "1 blocking problem" in report


def test_the_report_is_encouraging_when_all_is_well():
    assert "ready" in format_report([Check("Thing", OK, "fine")]).lower()


def test_warnings_do_not_read_as_failure():
    report = format_report([Check("Thing", WARN, "partial")])
    assert "blocking" not in report


def test_outlook_is_reported_as_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    from rotem_agent.doctor import check_outlook

    checks = check_outlook()
    assert checks[0].status == WARN
