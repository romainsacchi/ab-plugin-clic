"""Find ecoinvent export targets supported by the active Brightway databases."""

from dataclasses import dataclass
import re

import bw2data as bd
from bw2data.backends import ActivityDataset
from bw2data.configuration import labels, typo_settings

ECOINVENT_NAME = re.compile(
    r"ecoinvent[- ](?P<version>3\.\d+(?:\.\d+)?)[- ](?P<model>cut-?off|consequential|apos)",
    re.IGNORECASE,
)
VERSION = re.compile(r"3\.\d+(?:\.\d+)?")
MODELS = {"cutoff", "consequential"}
CUTOFF_ALIASES = {"3.9": "3.9.1", "3.10": "3.10.1"}


@dataclass(frozen=True)
class EcoinventProfile:
    version: str
    model: str

    @property
    def label(self) -> str:
        return f"ecoinvent {self.version} {self.model}"

    @property
    def target(self) -> dict[str, str]:
        return {
            "family": "ecoinvent",
            "version": self.version,
            "system_model": self.model,
        }


@dataclass(frozen=True)
class BackgroundSuggestion:
    technosphere: str
    biosphere: str
    profile: EcoinventProfile


def ecoinvent_profile(database: str) -> EcoinventProfile | None:
    metadata = bd.databases.get(database, {})
    version = str(metadata.get("ecoinvent_version") or "")
    model = str(
        metadata.get("ecoinvent_system_model") or metadata.get("system_model") or ""
    )
    if version and model and VERSION.fullmatch(version):
        return EcoinventProfile(version, model.casefold().replace("-", ""))
    match = ECOINVENT_NAME.fullmatch(database)
    if match:
        return EcoinventProfile(
            version or match["version"],
            (model or match["model"]).casefold().replace("-", ""),
        )
    return None


def linked_biospheres(technosphere: str) -> list[str]:
    dependencies = bd.databases.get(technosphere, {}).get("depends", []) or []
    flow_types = set(typo_settings.node_types) - set(labels.lci_node_types)
    biospheres = []
    for name in dependencies:
        if name == technosphere or name not in bd.databases:
            continue
        types = {
            row[0]
            for row in ActivityDataset.select(ActivityDataset.type)
            .where(ActivityDataset.database == name)
            .distinct()
            .tuples()
        }
        if types and types <= flow_types:
            biospheres.append(name)
    return sorted(set(biospheres))


def _export_profile_error(profile: EcoinventProfile) -> str:
    if profile.model not in MODELS:
        return f"CLIC does not offer {profile.model} as an ecoinvent export target."
    if profile.model == "cutoff" and profile.version in CUTOFF_ALIASES:
        resolved = CUTOFF_ALIASES[profile.version]
        return f"CLIC exports ecoinvent {resolved} for {profile.version} cutoff. Use a matching local release."
    return ""


def suggest_backgrounds() -> dict[str, BackgroundSuggestion]:
    suggestions = {}
    for name in bd.databases:
        profile = ecoinvent_profile(name)
        if profile is None or _export_profile_error(profile):
            continue
        biospheres = linked_biospheres(name)
        if len(biospheres) == 1:
            suggestions[name] = BackgroundSuggestion(name, biospheres[0], profile)
    return suggestions


def choose_target(
    technosphere: str, biosphere: str, version: str, model: str
) -> dict[str, str]:
    if not VERSION.fullmatch(version) or model not in MODELS:
        raise ValueError("Enter the ecoinvent release and select its system model.")
    requested = EcoinventProfile(version, model)
    if error := _export_profile_error(requested):
        raise ValueError(error)
    local = ecoinvent_profile(technosphere)
    if local is not None and local != requested:
        raise ValueError(
            f"The selected database identifies itself as {local.label}. Match the CLIC target or choose a different database."
        )
    if local is not None:
        linked = linked_biospheres(technosphere)
        if linked and biosphere not in linked:
            raise ValueError(
                f"Choose a biosphere database linked by {technosphere} ({', '.join(linked)})."
            )
    return requested.target
