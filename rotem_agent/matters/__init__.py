"""Client matters: what a document folder is, and which matter an email belongs to."""

from rotem_agent.matters.registry import (
    Matter,
    MatterRegistry,
    Resolution,
    load_matter,
    load_matters_root,
)

__all__ = [
    "Matter",
    "MatterRegistry",
    "Resolution",
    "load_matter",
    "load_matters_root",
]
