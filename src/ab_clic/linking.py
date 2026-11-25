"""Match each external exchange uniquely and retain the reasons for failures."""

from collections import Counter, defaultdict
from dataclasses import dataclass

import bw2data as bd

TECHNOSPHERE_FIELDS = ("name", "reference product", "location", "unit")
BIOSPHERE_FIELDS = ("name", "categories", "unit")


@dataclass(frozen=True)
class LinkIssue:
    activity: str
    exchange: str
    database: str
    reason: str
    next_action: str


def describe_exchange(exchange: dict) -> str:
    fields = [exchange.get("name") or exchange.get("type") or "Exchange"]
    fields.extend(
        exchange[key]
        for key in ("reference product", "location", "unit")
        if exchange.get(key)
    )
    if categories := exchange.get("categories"):
        fields.append(" / ".join(categories))
    return " · ".join(map(str, fields))


def _identity(record, fields):
    values = (record.get(field) or "" for field in fields)
    return tuple(
        tuple(part.lower() for part in value)
        if isinstance(value, (list, tuple))
        else value.lower()
        for value in values
    )


def match_external_links(
    activities: list[dict],
    kind: str,
    database: str,
    *,
    check_legacy_foreground: bool = False,
) -> list[LinkIssue]:
    fields = BIOSPHERE_FIELDS if kind == "biosphere" else TECHNOSPHERE_FIELDS
    foreground_counts = (
        Counter(_identity(activity, fields) for activity in activities)
        if check_legacy_foreground and kind == "technosphere"
        else {}
    )
    issues = []
    pending = defaultdict(list)
    for activity in activities:
        for exchange in activity["exchanges"]:
            if exchange.get("type") != kind or exchange.get("input"):
                continue
            key = _identity(exchange, fields)
            # Older CLIC exports omitted input IDs when suppliers shared labels.
            # Keep those exchanges out of background matching.
            if foreground_counts.get(key, 0) > 1:
                issues.append(
                    LinkIssue(
                        activity["name"],
                        describe_exchange(exchange),
                        activity["database"],
                        "CLIC export omitted a supplier ID for matching foreground activities",
                        "Prepare smaller batches or ask CLIC to regenerate the export.",
                    )
                )
                continue
            pending[key].append((activity["name"], exchange))
    if not pending:
        return issues

    candidates = defaultdict(list)
    for node in bd.Database(database):
        key = _identity(node, fields)
        if key in pending:
            candidates[key].append(node.key)

    for key, exchanges in pending.items():
        matches = candidates[key]
        if len(matches) == 1:
            for _, exchange in exchanges:
                exchange["input"] = matches[0]
            continue
        if matches:
            reason = f"{len(matches)} matching nodes"
            next_action = "Choose a database with a unique match or resolve the duplicate nodes in Brightway."
        else:
            reason = "No matching node"
            next_action = "Check the local background and the exchange name, unit, and location or compartment."
        issues.extend(
            LinkIssue(name, describe_exchange(exchange), database, reason, next_action)
            for name, exchange in exchanges
        )
    return issues
