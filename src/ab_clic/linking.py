"""Match each external exchange uniquely and retain the reasons for failures."""

from collections import defaultdict
from dataclasses import dataclass

import bw2data as bd
from bw2io.utils import activity_hash


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


def match_external_links(
    activities: list[dict], kind: str, database: str
) -> list[LinkIssue]:
    fields = (
        ["name", "categories", "unit"]
        if kind == "biosphere"
        else ["name", "reference product", "location", "unit"]
    )
    pending = defaultdict(list)
    for activity in activities:
        for exchange in activity["exchanges"]:
            if exchange.get("type") == kind and not exchange.get("input"):
                pending[activity_hash(exchange, fields=fields)].append(
                    (activity["name"], exchange)
                )
    if not pending:
        return []

    candidates = defaultdict(list)
    for node in bd.Database(database):
        key = activity_hash(node, fields=fields)
        if key in pending:
            candidates[key].append(node.key)

    issues = []
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
