from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SAMPLES_DIR = PROJECT_ROOT / "samples"
OUT_DIR = PROJECT_ROOT / "out"

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    model: str


def load_settings() -> Settings:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ConfigError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return Settings(gemini_api_key=key, model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip())


@dataclass(frozen=True)
class Firm:
    lawyer_name: str
    firm_name: str
    addresses: list[str]

    def is_own_address(self, address: str) -> bool:
        return address.strip().lower() in {a.lower() for a in self.addresses}


def load_firm(path: Path | None = None) -> Firm:
    data = _read_yaml(path or CONFIG_DIR / "firm.yaml")
    return Firm(
        lawyer_name=data.get("lawyer_name", ""),
        firm_name=data.get("firm_name", ""),
        addresses=list(data.get("addresses", [])),
    )


@dataclass(frozen=True)
class GlossaryTerm:
    he: str
    en: str


def load_glossary(path: Path | None = None) -> list[GlossaryTerm]:
    data = _read_yaml(path or CONFIG_DIR / "glossary.yaml")
    return [GlossaryTerm(he=t["he"], en=t.get("en", "")) for t in data.get("terms", [])]


@dataclass(frozen=True)
class BoilerplateRules:
    truncate_from: list[re.Pattern[str]] = field(default_factory=list)
    remove_lines: list[re.Pattern[str]] = field(default_factory=list)


def load_boilerplate(path: Path | None = None) -> BoilerplateRules:
    data = _read_yaml(path or CONFIG_DIR / "boilerplate.yaml")
    flags = re.MULTILINE | re.IGNORECASE
    return BoilerplateRules(
        truncate_from=[re.compile(p, flags) for p in data.get("truncate_from", [])],
        remove_lines=[re.compile(p, flags) for p in data.get("remove_lines", [])],
    )


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
