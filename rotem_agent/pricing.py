"""Turning token counts into money.

Tokens are what the usage log stores; cost is derived when the log is read. That
ordering matters. Prices change, and the figures in the config file are typed in
by hand from Google's pricing page, so they will be wrong at some point. Storing
a computed amount would freeze that error into the record forever, whereas
pricing on read means correcting the file reprices every draft ever written.

A model with no price entry reports its tokens and an unknown cost. Falling back
to a default rate would produce a plausible number that happens to be fiction,
which is worse than admitting the price is not known.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rotem_agent.config import CONFIG_DIR, ConfigError, read_yaml


@dataclass(frozen=True)
class ModelPrice:
    """USD per one million tokens."""

    input_per_million: float
    output_per_million: float
    # Cache hits are billed at a fraction of the input rate. Absent a rate, they
    # are charged in full, which overstates rather than flatters the bill.
    cached_input_per_million: float | None = None


@dataclass(frozen=True)
class PriceList:
    models: dict[str, ModelPrice]
    usd_to_ils: float | None = None
    source: str = ""

    def price_for(self, model: str) -> ModelPrice | None:
        name = (model or "").strip()
        return self.models.get(name) or self.models.get(name.removeprefix("models/"))

    def cost_usd(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> float | None:
        """None means this model has no price on file, not that it was free.

        Cached tokens are a subset of the input count, so they are charged at
        the cache rate and deducted from the tokens charged in full.
        """
        price = self.price_for(model)
        if price is None:
            return None
        cached = max(0, min(cached_tokens, input_tokens))
        cached_rate = (
            price.input_per_million
            if price.cached_input_per_million is None
            else price.cached_input_per_million
        )
        return (
            (input_tokens - cached) / 1_000_000 * price.input_per_million
            + cached / 1_000_000 * cached_rate
            + output_tokens / 1_000_000 * price.output_per_million
        )

    def in_ils(self, usd: float) -> float | None:
        return None if self.usd_to_ils is None else usd * self.usd_to_ils


EMPTY = PriceList(models={})


def load_prices(path: Path | None = None) -> PriceList:
    """Never raises. A cost report must not be able to stop the agent drafting."""
    target = path or CONFIG_DIR / "pricing.yaml"
    try:
        data = read_yaml(target)
    except (ConfigError, Exception):
        return PriceList(models={}, source=f"{target} (unreadable)")

    models: dict[str, ModelPrice] = {}
    for name, entry in (data.get("models") or {}).items():
        if not isinstance(entry, dict):
            continue
        # A null price is how the file says "not filled in yet", which must stay
        # unknown rather than becoming zero.
        raw_in, raw_out = entry.get("input"), entry.get("output")
        if raw_in is None or raw_out is None:
            continue
        raw_cached = entry.get("cached_input")
        try:
            models[str(name).strip()] = ModelPrice(
                float(raw_in),
                float(raw_out),
                None if raw_cached is None else float(raw_cached),
            )
        except (TypeError, ValueError):
            continue

    rate = data.get("usd_to_ils")
    try:
        usd_to_ils = float(rate) if rate is not None else None
    except (TypeError, ValueError):
        usd_to_ils = None

    return PriceList(models=models, usd_to_ils=usd_to_ils, source=str(target))


def format_usd(amount: float | None) -> str:
    if amount is None:
        return "cost unknown"
    if amount < 0.01:
        return f"${amount:.5f}"
    return f"${amount:,.4f}"


def format_money(prices: PriceList, amount: float | None) -> str:
    """Dollars, plus shekels only when a rate has actually been configured."""
    if amount is None:
        return format_usd(None)
    ils = prices.in_ils(amount)
    return format_usd(amount) + ("" if ils is None else f" (\u20aa{ils:,.2f})")
