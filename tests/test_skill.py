import pytest

from rotem_agent.config import ConfigError
from rotem_agent.drafting.prompt import build_system_prompt
from rotem_agent.config import load_firm, load_glossary
from rotem_agent.skill import load_skill


@pytest.fixture(scope="module")
def skill():
    return load_skill()


def test_loads_frontmatter_and_references(skill):
    assert skill.name == "legal-client-email-intake"
    assert "Israeli law firm" in skill.description
    assert set(skill.references) >= {
        "matter routing",
        "safety escalation",
        "source verification",
        "voice and drafting",
    }


def test_prompt_section_includes_reference_content(skill):
    section = skill.as_prompt_section()
    assert "Holding reply rule" in section
    assert "Identity gate" in section
    assert "status_spousal" in section


def test_missing_reference_is_an_error(tmp_path):
    root = tmp_path / "broken"
    (root / "references").mkdir(parents=True)
    (root / "references" / "only.md").write_text("x", encoding="utf-8")
    (root / "SKILL.md").write_text(
        "---\nname: broken\n---\nSee references/nope.md for rules.\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="nope.md"):
        load_skill("broken", skills_dir=tmp_path)


def test_strict_policy_reaches_the_system_prompt(skill):
    prompt = build_system_prompt(load_firm(), load_glossary(), skill, source_policy="strict")
    assert "Source policy: strict" in prompt
    assert "is_holding_reply" in prompt
    assert "רותם פרגון" in prompt


def test_advisory_policy_is_selectable(skill):
    prompt = build_system_prompt(load_firm(), load_glossary(), skill, source_policy="advisory")
    assert "Source policy: advisory" in prompt
    assert "Source policy: strict" not in prompt
