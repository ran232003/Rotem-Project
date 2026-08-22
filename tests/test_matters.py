from __future__ import annotations

import pytest

from rotem_agent.config import ConfigError
from rotem_agent.matters.registry import MatterRegistry, load_matters_root


def _matter(root, slug, *, addresses=(), agents=(), name="Client", category="reentry_visa"):
    directory = root / slug
    (directory / "docs").mkdir(parents=True)
    lines = [f"client_name: {name}", f"category: {category}", "addresses:"]
    lines += [f"  - {a}" for a in addresses]
    lines += ["agents:"] + [f"  - {a}" for a in agents]
    (directory / "matter.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory


def test_discovery_ignores_folders_without_a_matter_file(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"])
    (tmp_path / "not-a-matter").mkdir()
    registry = MatterRegistry.discover(tmp_path)
    assert [m.slug for m in registry.matters] == ["anna-reentry"]


def test_client_address_resolves_the_matter(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"])
    registry = MatterRegistry.discover(tmp_path)
    resolution = registry.resolve(["ANNA@example.com "])
    assert resolution.ok and resolution.matter.slug == "anna-reentry"


def test_an_agency_representing_two_clients_is_ambiguous_not_a_guess(tmp_path):
    """A relocation agency writes on behalf of many clients.

    Picking one would put another client's documents into the draft, so this has
    to come back unresolved with both candidates named.
    """
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"], agents=["agent@relo.test"])
    _matter(tmp_path, "boris-work-visa", addresses=["boris@example.com"], agents=["agent@relo.test"])
    registry = MatterRegistry.discover(tmp_path)

    resolution = registry.resolve(["agent@relo.test"])
    assert not resolution.ok
    assert resolution.ambiguous
    assert {m.slug for m in resolution.candidates} == {"anna-reentry", "boris-work-visa"}


def test_a_client_address_wins_over_a_shared_agent(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"], agents=["agent@relo.test"])
    _matter(tmp_path, "boris-work-visa", addresses=["boris@example.com"], agents=["agent@relo.test"])
    registry = MatterRegistry.discover(tmp_path)

    resolution = registry.resolve(["agent@relo.test", "anna@example.com"])
    assert resolution.matter.slug == "anna-reentry"


def test_a_lone_agent_address_resolves_when_only_one_matter_uses_it(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"], agents=["agent@relo.test"])
    registry = MatterRegistry.discover(tmp_path)
    assert registry.resolve(["agent@relo.test"]).matter.slug == "anna-reentry"


def test_two_matters_claiming_one_client_address_is_ambiguous(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"])
    _matter(tmp_path, "anna-citizenship", addresses=["anna@example.com"])
    registry = MatterRegistry.discover(tmp_path)
    resolution = registry.resolve(["anna@example.com"])
    assert resolution.ambiguous and len(resolution.candidates) == 2


def test_a_remembered_conversation_overrides_address_matching(tmp_path):
    """A new participant joining a known thread must not move it to another matter."""
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"])
    _matter(tmp_path, "boris-work-visa", addresses=["boris@example.com"])
    registry = MatterRegistry.discover(tmp_path)

    resolution = registry.resolve(["boris@example.com"], known_slug="anna-reentry")
    assert resolution.matter.slug == "anna-reentry"


def test_unknown_addresses_resolve_to_nothing(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"])
    registry = MatterRegistry.discover(tmp_path)
    resolution = registry.resolve(["stranger@example.com"])
    assert not resolution.ok and not resolution.ambiguous


def test_docs_dir_is_derived_from_the_matter_folder(tmp_path):
    _matter(tmp_path, "anna-reentry", addresses=["anna@example.com"])
    matter = MatterRegistry.discover(tmp_path).by_slug("anna-reentry")
    assert matter.docs_dir == tmp_path / "anna-reentry" / "docs"


def test_missing_root_config_is_explained(tmp_path):
    with pytest.raises(ConfigError, match="matters.example.yaml"):
        load_matters_root(tmp_path / "absent.yaml")


def test_root_without_a_root_key_is_rejected(tmp_path):
    path = tmp_path / "matters.yaml"
    path.write_text("other: value\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="does not set 'root'"):
        load_matters_root(path)
