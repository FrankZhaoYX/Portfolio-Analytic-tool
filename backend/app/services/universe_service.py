"""Asset-class classification for stored symbols, from data/universe/*.csv.

`eod_prices` has no asset-class column - only pxdate, symbol, exchange, OHLCV.
The universe CSVs are the sole place that distinction lives, and they are
version-controlled on purpose, so the classification stays reviewable rather
than hiding in a hard-coded list. Reading them here keeps that server-side:
the front end asks one question and gets an answer instead of reaching into
the repository layout itself.
"""
import csv
from functools import lru_cache

from app.config import REPO_ROOT
from app.logging_config import get_logger

log = get_logger(__name__)

UNIVERSE_DIR = REPO_ROOT / "data" / "universe"

# A ticker can legitimately appear in two lists: GLD is one of the most-traded
# ETFs *and* a commodity trust, so it sits in both etf_us.csv and etp_us.csv.
# The narrower structural classification wins, so a grantor trust is not filed
# under plain ETF. Anything missing from every list stays "other" rather than
# being assumed a stock - an index or a hand-fetched ticker should read as
# unclassified, not silently mislabelled.
_PRECEDENCE = {"etp": 3, "etf": 2, "stock": 1}
DEFAULT_KIND = "other"

# Display order for a picker: the broad category first, specialised last.
KIND_ORDER = ["stock", "etf", "etp", DEFAULT_KIND]


def _dir_signature() -> tuple:
    """Names and mtimes of the universe files, so edits invalidate the cache.

    Caching on content-identity rather than forever means adding a universe
    file does not require restarting the backend to see it.
    """
    try:
        return tuple(sorted(
            (p.name, p.stat().st_mtime_ns) for p in UNIVERSE_DIR.glob("*.csv")
        ))
    except OSError:
        return ()


@lru_cache(maxsize=4)
def _load(signature: tuple) -> dict[str, str]:
    """Build SYMBOL -> kind. `signature` is the cache key, not read directly."""
    kinds: dict[str, str] = {}
    conflicts: list[str] = []

    for path in sorted(UNIVERSE_DIR.glob("*.csv")):
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    sym = (row.get("sym") or "").strip().upper()
                    kind = (row.get("kind") or "").strip().lower()
                    if not sym or kind not in _PRECEDENCE:
                        continue
                    current = kinds.get(sym)
                    if current is None:
                        kinds[sym] = kind
                    elif current != kind:
                        winner = max((current, kind), key=lambda k: _PRECEDENCE[k])
                        conflicts.append(f"{sym}: {current}/{kind} -> {winner}")
                        kinds[sym] = winner
        except OSError as exc:
            log.warning("Could not read universe file %s: %s", path.name, exc)

    if conflicts:
        log.info("Asset-class conflicts resolved by precedence: %s", ", ".join(conflicts))
    log.debug("Loaded asset classes for %d symbol(s)", len(kinds))
    return kinds


def symbol_kinds() -> dict[str, str]:
    """SYMBOL -> "stock" | "etf" | "etp", for every symbol in the universe files."""
    return _load(_dir_signature())


def classify(symbols: list[str]) -> list[dict]:
    """Pair each symbol with its asset class, preserving the given order."""
    kinds = symbol_kinds()
    return [
        {"symbol": s.upper(), "kind": kinds.get(s.upper(), DEFAULT_KIND)}
        for s in symbols
    ]
