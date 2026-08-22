from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from rotem_agent.config import CONFIG_DIR, PROJECT_ROOT, ConfigError, read_yaml

MATTER_FILE = "matter.yaml"
DOCS_DIRNAME = "docs"


@dataclass(frozen=True)
class Matter:
    slug: str
    path: Path
    client_name: str
    category: str
    client_addresses: list[str] = field(default_factory=list)
    agent_addresses: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def docs_dir(self) -> Path:
        return self.path / DOCS_DIRNAME

    @property
    def all_addresses(self) -> list[str]:
        return [*self.client_addresses, *self.agent_addresses]

    def has_client_address(self, address: str) -> bool:
        return _norm(address) in {_norm(a) for a in self.client_addresses}

    def has_agent_address(self, address: str) -> bool:
        return _norm(address) in {_norm(a) for a in self.agent_addresses}


@dataclass(frozen=True)
class Resolution:
    """The outcome of matching an email to a matter.

    `candidates` is populated when the answer is genuinely ambiguous. Guessing
    would mean putting one client's documents into another client's draft, so
    ambiguity is surfaced rather than resolved by picking the first match.
    """

    matter: Matter | None
    reason: str
    candidates: list[Matter] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.matter is not None

    @property
    def ambiguous(self) -> bool:
        return self.matter is None and len(self.candidates) > 1


def load_matters_root(path: Path | None = None) -> Path:
    target = path or CONFIG_DIR / "matters.yaml"
    if not target.exists():
        raise ConfigError(
            f"Missing {target}. Copy config/matters.example.yaml to config/matters.yaml "
            "and set the folder that holds your client matters."
        )
    raw = str(read_yaml(target).get("root", "")).strip()
    if not raw:
        raise ConfigError(f"{target} does not set 'root'.")
    root = Path(raw)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root


def load_matter(directory: Path) -> Matter:
    data = read_yaml(directory / MATTER_FILE)
    return Matter(
        slug=directory.name,
        path=directory,
        client_name=str(data.get("client_name") or "").strip(),
        category=str(data.get("category") or "").strip(),
        # A key present but empty parses as None rather than an empty list.
        client_addresses=[str(a).strip() for a in (data.get("addresses") or []) if str(a).strip()],
        agent_addresses=[str(a).strip() for a in (data.get("agents") or []) if str(a).strip()],
        notes=str(data.get("notes") or "").strip(),
    )


class MatterRegistry:
    def __init__(self, matters: Iterable[Matter]) -> None:
        self.matters = list(matters)

    @classmethod
    def discover(cls, root: Path | None = None) -> "MatterRegistry":
        base = root or load_matters_root()
        if not base.exists():
            raise ConfigError(f"Matters root does not exist: {base}")
        found = [
            load_matter(child)
            for child in sorted(base.iterdir())
            if child.is_dir() and (child / MATTER_FILE).exists()
        ]
        return cls(found)

    def by_slug(self, slug: str) -> Matter | None:
        return next((m for m in self.matters if m.slug == slug), None)

    def resolve(
        self,
        addresses: Iterable[str],
        *,
        known_slug: str | None = None,
    ) -> Resolution:
        """Map the participants of an email to exactly one matter.

        `known_slug` comes from having seen this conversation before, and wins
        outright: a thread stays with its matter even when someone new is copied
        in partway through.
        """
        if known_slug:
            remembered = self.by_slug(known_slug)
            if remembered is not None:
                return Resolution(remembered, "this conversation was seen before")

        people = [a for a in (_norm(x) for x in addresses) if a]

        by_client = [m for m in self.matters if any(m.has_client_address(a) for a in people)]
        if len(by_client) == 1:
            return Resolution(by_client[0], "client address matched")
        if len(by_client) > 1:
            return Resolution(None, "more than one matter claims these addresses", by_client)

        # An agency such as a relocation firm corresponds on behalf of many
        # different clients, so its address identifies the intermediary, never
        # the matter. Accept it only when it points at a single matter.
        by_agent = [m for m in self.matters if any(m.has_agent_address(a) for a in people)]
        if len(by_agent) == 1:
            return Resolution(by_agent[0], "agent address matched a single matter")
        if len(by_agent) > 1:
            return Resolution(
                None,
                "an agent on this email represents several matters; a client address is needed",
                by_agent,
            )

        return Resolution(None, "no matter has any of these addresses")


def _norm(address: str) -> str:
    return address.strip().lower()
