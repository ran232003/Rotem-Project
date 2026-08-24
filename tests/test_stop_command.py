"""Turning the agent off without the dashboard.

This exists for the moment the dashboard will not open, so the tests lean on the
cases where something has already gone wrong: a watcher that ignores the request,
a stop file left behind by a killed one, and a caller with no way to answer a
question.

Nothing here may show a real message box. A modal dialog in a test suite hangs
it on the machine it was meant to be tested on, so the dialog is always stubbed.
"""

from __future__ import annotations

import argparse

import pytest

from rotem_agent import cli, control, dialog


class _Agent:
    """A watcher that is running, or not, and may or may not answer."""

    def __init__(self, *, running=True, answers=True):
        self.running = running
        self.answers = answers
        self.asked = False
        self.killed = False
        self.cleared = False

    def status(self, *a, **k):
        return control.WatcherStatus(running=self.running, pid=4242 if self.running else None)

    def stop_watcher(self, *, timeout=90.0, **k):
        self.asked = True
        if self.answers:
            self.running = False
        return self.status()

    def force_stop(self, **k):
        self.killed = True
        self.running = False
        return self.status()

    def clear_stop(self, *a, **k):
        self.cleared = True


class _Said:
    """Records what the lawyer would have been shown."""

    def __init__(self, answer=False):
        self.answer = answer
        self.told = []
        self.questions = []

    def tell(self, text, **kwargs):
        self.told.append(text)

    def ask(self, text, **kwargs):
        self.questions.append(text)
        return self.answer


@pytest.fixture
def agent(monkeypatch):
    fake = _Agent()
    monkeypatch.setattr(control, "watcher_status", fake.status)
    monkeypatch.setattr(control, "stop_watcher", fake.stop_watcher)
    monkeypatch.setattr(control, "force_stop", fake.force_stop)
    monkeypatch.setattr(control, "clear_stop", fake.clear_stop)
    return fake


@pytest.fixture
def said(monkeypatch):
    voice = _Said()
    monkeypatch.setattr(dialog, "tell", voice.tell)
    monkeypatch.setattr(dialog, "ask", voice.ask)
    return voice


def _args(**kwargs):
    return argparse.Namespace(
        timeout=kwargs.pop("timeout", 5.0),
        force=kwargs.pop("force", False),
        dialog=kwargs.pop("dialog", False),
        **kwargs,
    )


def test_a_running_agent_is_asked_and_stops(agent):
    assert cli._run_stop(_args()) == 0
    assert agent.asked is True
    assert agent.killed is False


def test_stopping_is_a_request_not_a_kill(agent):
    """A draft caught mid-write would be lost, and its spend recorded nowhere."""
    cli._run_stop(_args())
    assert agent.killed is False


def test_nothing_running_is_not_an_error(agent):
    """She will press this when unsure, which is exactly when it is already off."""
    agent.running = False
    assert cli._run_stop(_args()) == 0
    assert agent.asked is False


def test_a_leftover_stop_request_is_cleared_when_nothing_is_running(agent):
    """Left in place it would stop the next watcher on its first cycle, which
    reads as the start button not working."""
    agent.running = False
    cli._run_stop(_args())
    assert agent.cleared is True


def test_an_agent_that_never_answers_is_reported_rather_than_killed(agent):
    agent.answers = False
    assert cli._run_stop(_args()) == 4
    assert agent.killed is False


def test_force_skips_the_asking(agent):
    agent.answers = False
    assert cli._run_stop(_args(force=True)) == 0
    assert agent.killed is True
    assert agent.asked is False


def test_a_force_that_fails_says_so(agent, monkeypatch):
    agent.answers = False
    monkeypatch.setattr(control, "force_stop", lambda **k: control.WatcherStatus(running=True, pid=1))
    assert cli._run_stop(_args(force=True)) == 4


# ------------------------------------------------------------------ the icon


def test_the_icon_reports_through_a_box_not_the_console(agent, said, capsys):
    """Hebrew in a console under the OEM codepage is unreadable."""
    assert cli._run_stop(_args(dialog=True)) == 0
    assert said.told and "כובה" in said.told[0]
    assert capsys.readouterr().out == ""


def test_the_console_path_stays_in_english(agent, said, capsys):
    cli._run_stop(_args())
    assert said.told == []
    assert "stopped" in capsys.readouterr().out


def test_the_icon_offers_to_force_when_nothing_answers(agent, said):
    agent.answers = False
    said.answer = True

    assert cli._run_stop(_args(dialog=True)) == 0
    assert said.questions and "בכוח" in said.questions[0]
    assert agent.killed is True


def test_declining_to_force_leaves_the_agent_alone(agent, said):
    agent.answers = False
    said.answer = False

    assert cli._run_stop(_args(dialog=True)) == 4
    assert agent.killed is False


def test_the_console_never_forces_without_being_told_to(agent, said):
    """There is nobody at a console to answer, and silence is not consent."""
    agent.answers = False
    assert cli._run_stop(_args()) == 4
    assert said.questions == []
    assert agent.killed is False


# --------------------------------------------------------------- the dialog itself


def test_a_box_that_cannot_be_shown_falls_back_to_printing(monkeypatch, capsys):
    monkeypatch.setattr(dialog, "_box", lambda *a, **k: None)
    dialog.tell("שלום")
    assert "שלום" in capsys.readouterr().out


def test_an_unanswerable_question_answers_no(monkeypatch):
    """The only caller uses this to confirm killing the agent."""
    monkeypatch.setattr(dialog, "_box", lambda *a, **k: None)
    assert dialog.ask("לכבות בכוח?") is False


def test_a_yes_is_a_yes_and_anything_else_is_not(monkeypatch):
    monkeypatch.setattr(dialog, "_box", lambda *a, **k: 6)
    assert dialog.ask("?") is True
    monkeypatch.setattr(dialog, "_box", lambda *a, **k: 7)
    assert dialog.ask("?") is False


def test_the_command_is_registered(monkeypatch):
    """Wired into the parser, since the desktop icon calls it by name."""
    called = {}

    def record(args):
        called["args"] = args
        return 0

    monkeypatch.setattr(cli, "_run_stop", record)

    assert cli.main(["stop", "--dialog"]) == 0
    assert called["args"].dialog is True
