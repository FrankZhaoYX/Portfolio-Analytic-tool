"""Timestamp handling for ingest.

Rule: everything is stored in UTC. Display-side conversion to Eastern happens
in the frontend (see frontend/timefmt.py), so the database stays timezone-neutral
and a restart, a host in another timezone, or a DST change can't reinterpret
stored data.

The DB Service will not parse an ISO string carrying a UTC offset - a value like
'2026-08-23T22:10:54.826+00:00' is stored as null rather than rejected. On an
ordinary column that is silent data loss (every `trades.createdat` was empty for
a day before anyone noticed); on a partition column it fails the whole ingest
with "Null partition column values found". So timestamps must be written as
*naive* ISO strings that are UTC by convention.
"""
from datetime import datetime, timezone


def utc_now_iso(timespec: str = "microseconds") -> str:
    """Current UTC time as a naive ISO string the DB Service accepts.

    >>> utc_now_iso()          # doctest: +SKIP
    '2026-08-23T22:10:54.826000'

    Note the absence of a '+00:00' suffix - that is the whole point.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec=timespec)


def to_utc_naive_iso(value: datetime, timespec: str = "microseconds") -> str:
    """Normalise any datetime to a naive-UTC ISO string for ingest.

    Aware datetimes are converted to UTC; naive ones are assumed to already be
    UTC and passed through. Either way the result carries no offset.
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec=timespec)
