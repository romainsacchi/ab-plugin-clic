"""Import a synthetic CLIC package in the temporary project used by unittest."""

from copy import deepcopy

import bw2calc as bc
import bw2data as bd
from bw2data.signals import on_database_write

from ab_clic.background import choose_target, suggest_backgrounds
from ab_clic.inventory import prepare_inventory, write_inventory
from ab_clic.records import IMPORT_METADATA, imported_versions
from ab_clic.review import package_activities


def make_background(technosphere="background", biosphere="biosphere"):
    bd.Database(biosphere).write(
        {
            (biosphere, "co2"): {
                "name": "Carbon dioxide",
                "categories": ("air",),
                "unit": "kilogram",
                "type": "emission",
            },
        }
    )
    bd.Database(technosphere).write(
        {
            (technosphere, "supply"): {
                "name": "Supply",
                "reference product": "input",
                "location": "CH",
                "unit": "kilogram",
                "exchanges": [
                    {
                        "input": (technosphere, "supply"),
                        "type": "production",
                        "amount": 1,
                    },
                    {"input": (biosphere, "co2"), "type": "biosphere", "amount": 3},
                ],
            },
        }
    )


def make_package():
    activities = [
        {
            "database": "original",
            "code": code,
            "name": code,
            "reference product": code,
            "location": "CH",
            "unit": "kilogram",
            "type": "process",
            "exchanges": [
                {
                    "type": "production",
                    "amount": 1,
                    "input": {"database": "__clic__", "code": code},
                }
            ],
        }
        for code in ("root", "helper")
    ]
    root, helper = activities
    root["comment"] = "Published CLIC description"
    root["provenance"] = {
        "dataset_slug": "root",
        "semantic_version": "1.0.0",
        "clic_catalog": {
            "public_url": "https://clic.psi.ch/datasets/root/versions/1.0.0/",
            "selected_license": "CC-BY-4.0",
        },
    }
    root["parameters"] = [{"name": "scale", "amount": 2}]
    root["exchanges"].extend(
        [
            {
                "type": "technosphere",
                "amount": 2,
                "input": {"database": "__clic__", "code": "helper"},
            },
            {
                "type": "biosphere",
                "amount": -1,
                "name": "Carbon dioxide",
                "categories": ["air"],
                "unit": "kilogram",
                "uncertainty type": 3,
                "loc": -1,
                "scale": 0.1,
            },
        ]
    )
    helper["exchanges"].append(
        {
            "type": "technosphere",
            "amount": 2,
            "name": "Supply",
            "reference product": "input",
            "location": "CH",
            "unit": "kilogram",
        }
    )
    return {
        "schema": "clic.brightway-json",
        "schema_version": "1.2",
        "package": {
            "suggested_database_name": "original",
            "root_version_ids": [42],
            "included_version_ids": [42],
            "focal_activity_codes": ["root"],
            "generated_helper_codes": ["helper"],
        },
        "resolved_target": {
            "family": "ecoinvent",
            "version": "3.12",
            "system_model": "cutoff",
        },
        "conversion": {"warnings": [{"message": "Sample conversion warning"}]},
        "activities": activities,
    }


if __name__ == "__main__":
    bd.projects.set_current("CLIC integration test")
    make_background()
    make_background("ecoinvent-3.12-cutoff", "Renamed elementary flows")
    suggestion = suggest_backgrounds()["ecoinvent-3.12-cutoff"]
    assert suggestion.biosphere == "Renamed elementary flows"
    assert suggestion.profile.target == choose_target(
        suggestion.technosphere, suggestion.biosphere, "3.12", "cutoff"
    )
    try:
        choose_target(suggestion.technosphere, suggestion.biosphere, "3.11", "cutoff")
    except ValueError as exc:
        assert "identifies itself as ecoinvent 3.12 cutoff" in str(exc)
    else:
        raise AssertionError("Accepted an incompatible local background")
    package = make_package()
    settings = dict(
        project=bd.projects.current,
        technosphere="background",
        biosphere="biosphere",
        database="new",
    )
    missing = deepcopy(package)
    missing["activities"][1]["exchanges"][1]["name"] = "Missing supply"
    blocked = prepare_inventory(missing, **settings)
    assert len(blocked.issues) == 1
    assert "Missing supply" in blocked.issues[0].exchange
    assert blocked.issues[0].database == "background"
    try:
        write_inventory(blocked)
    except ValueError as exc:
        assert "Resolve all exchange links" in str(exc)
    else:
        raise AssertionError("An unlinked exchange was accepted")
    assert "new" not in bd.databases

    same_concatenation = deepcopy(package)
    exchange = same_concatenation["activities"][1]["exchanges"][1]
    exchange.update({"name": "Suppl", "reference product": "yinput"})
    result = prepare_inventory(same_concatenation, **settings)
    assert len(result.issues) == 1
    assert result.issues[0].reason == "No matching node"

    ambiguous_foreground = deepcopy(package)
    for code in ("older-supplier", "newer-supplier"):
        ambiguous_foreground["activities"].append(
            {
                "name": "Supply",
                "reference product": "input",
                "location": "CH",
                "unit": "kilogram",
                "code": code,
                "exchanges": [
                    {
                        "type": "production",
                        "amount": 1,
                        "input": {"database": "__clic__", "code": code},
                    }
                ],
            }
        )
    result = prepare_inventory(ambiguous_foreground, **settings)
    assert len(result.issues) == 1
    assert "omitted a supplier ID" in result.issues[0].reason
    assert "input" not in result.importer.data[1]["exchanges"][1]
    fixed_export = deepcopy(ambiguous_foreground)
    fixed_export["package"]["foreground_link_version"] = 1
    fixed_export["activities"][1]["exchanges"][1]["input"] = {
        "database": "__clic__",
        "code": "newer-supplier",
    }
    result = prepare_inventory(fixed_export, **settings)
    assert not result.issues
    assert result.importer.data[1]["exchanges"][1]["input"] == ("new", "newer-supplier")
    # A marked export can still intentionally refer to the exact local supplier.
    del fixed_export["activities"][1]["exchanges"][1]["input"]
    result = prepare_inventory(fixed_export, **settings)
    assert not result.issues
    assert result.importer.data[1]["exchanges"][1]["input"] == ("background", "supply")

    bd.Database("duplicates").write(
        {
            ("duplicates", code): {
                "name": "Supply",
                "reference product": "input",
                "location": "CH",
                "unit": "kilogram",
                "exchanges": [
                    {"type": "production", "amount": 1, "input": ("duplicates", code)}
                ],
            }
            for code in ("first", "second")
        }
    )
    duplicate_link = prepare_inventory(
        package, **{**settings, "technosphere": "duplicates"}
    ).issues[0]
    assert duplicate_link.reason == "2 matching nodes"
    assert "duplicate nodes" in duplicate_link.next_action

    prepared = prepare_inventory(package, **settings)
    assert not prepared.issues
    assert [activity.role for activity in package_activities(prepared)] == [
        "Selected dataset",
        "Generated helper",
    ]
    assert package["activities"][0]["database"] == "original"
    signalled = []

    @on_database_write.connect
    def record_write(_sender, name):
        signalled.append(name)

    write_inventory(prepared)
    assert "new" in signalled, signalled
    record = bd.databases["new"][IMPORT_METADATA]
    assert record["completed_at"]
    assert record["root_version_ids"] == [42]
    assert (
        record["activities"][0]["source_url"]
        == "https://clic.psi.ch/datasets/root/versions/1.0.0/"
    )
    assert record["activities"][0]["version_id"] == 42
    assert record["target"] == package["resolved_target"]
    assert (record["technosphere_database"], record["biosphere_database"]) == (
        "background",
        "biosphere",
    )
    assert record["conversion_warnings"] == package["conversion"]["warnings"]
    assert imported_versions() == {42: ["new"]}
    root = bd.Database("new").get("root")
    assert root["comment"] == "Published CLIC description"
    assert root["parameters"][0]["amount"] == 2
    assert next(iter(root.biosphere()))["scale"] == 0.1
    assert next(iter(root.technosphere())).input.key == ("new", "helper")
    lca = bc.LCA({root: 1})
    lca.lci()
    assert abs(float(lca.inventory.sum()) - 11) < 1e-9
    try:
        write_inventory(prepared)
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("An existing database was overwritten")
    bd.projects.set_current("Other project")
    assert not imported_versions()
    bd.projects.set_current(settings["project"])
    assert imported_versions() == {42: ["new"]}
    bd.Database("new").get("root").delete()
    assert not imported_versions()
