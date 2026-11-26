"""Import a synthetic CLIC package in the temporary project used by unittest."""

from copy import deepcopy
from unittest.mock import patch

import bw2calc as bc
import bw2data as bd
from bw2data.parameters import ParameterizedExchange
from bw2data.search import IndexManager
from bw2data.signals import on_database_write

from ab_clic.background import choose_target, suggest_backgrounds
from ab_clic.inventory import prepare_inventory, writable_foregrounds, write_inventory
from ab_clic.records import IMPORT_HISTORY, IMPORT_METADATA, imported_versions
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


def check_append(package, settings):
    database = bd.Database("new")
    root, helper = database.get("root"), database.get("helper")
    original_ids = root.id, helper.id, next(iter(root.technosphere())).id
    dependent = bd.Database("dependent")
    dependent.write(
        {
            ("dependent", "model"): {
                "name": "External model",
                "unit": "kilogram",
                "location": "CH",
                "exchanges": [{"type": "technosphere", "amount": 1, "input": root.key}],
            }
        }
    )
    bd.calculation_setups["CLIC model"] = {"inv": [{root.id: 1}], "ia": []}
    bd.Database("empty").register(read_only=False, searchable=False)
    bd.Database("locked").register(read_only=True)
    bd.Database("Other legacy database").register()
    bd.databases["biosphere"]["read_only"] = False
    bd.databases["new"]["read_only"] = True
    assert writable_foregrounds("background", "biosphere") == ["empty"]
    del bd.databases["new"]["read_only"]
    assert writable_foregrounds("background", "biosphere") == ["empty", "new"]

    additional = deepcopy(package)
    additional["package"].update(
        root_version_ids=[43],
        included_version_ids=[43],
        focal_activity_codes=["second"],
    )
    changed = additional["activities"][0]
    changed.update(code="second", name="Second inventory")
    changed["exchanges"][0]["input"]["code"] = "second"
    changed["exchanges"][0]["output"] = ("new", "root")
    additional["activities"][1]["exchanges"].reverse()
    append_settings = {**settings, "append": True}
    prepared = prepare_inventory(additional, **append_settings)
    assert prepared.append_review.added == ("second",)
    assert prepared.append_review.reused == ("helper",)
    assert not prepared.append_review.conflicts

    helper["name"] = "Locally edited helper"
    helper.save()
    try:
        write_inventory(prepared)
    except ValueError as error:
        assert "destination database changed" in str(error)
    else:
        raise AssertionError("Accepted a local edit after review")
    conflicting = prepare_inventory(additional, **append_settings)
    assert conflicting.append_review.conflicts == ("helper",)
    try:
        write_inventory(conflicting)
    except ValueError as error:
        assert "activity code conflicts" in str(error)
    else:
        raise AssertionError("Accepted a conflicting activity code")
    assert ("new", "second") not in database
    helper["name"] = "helper"
    helper.save()

    before = deepcopy(bd.databases["new"])
    add_to_index = IndexManager.add_datasets

    def fail_after_index_write(index, datasets):
        add_to_index(index, datasets)
        raise OSError("Simulated index failure")

    with patch.object(IndexManager, "add_datasets", fail_after_index_write):
        try:
            write_inventory(prepared)
        except OSError as error:
            assert "Simulated index failure" in str(error)
        else:
            raise AssertionError("Failed write was accepted")
    assert bd.databases["new"] == before
    assert ("new", "second") not in database
    assert not database.search("Second inventory")

    write_inventory(prepared)
    root, helper = database.get("root"), database.get("helper")
    assert (root.id, helper.id, next(iter(root.technosphere())).id) == original_ids
    assert next(iter(dependent.get("model").technosphere())).input.id == root.id
    assert bd.calculation_setups["CLIC model"]["inv"] == [{root.id: 1}]
    assert database.search("Second inventory")[0].key == ("new", "second")
    assert imported_versions() == {42: ["new"], 43: ["new"]}
    assert bd.databases["new"]["number"] == 3
    assert "read_only" not in bd.databases["new"]
    second = database.get("second")
    assert len(list(root.production())) == len(list(second.production())) == 1
    assert next(iter(second.technosphere())).input.id == helper.id
    lca = bc.LCA({second: 1})
    lca.lci()
    assert abs(float(lca.inventory.sum()) - 11) < 1e-9

    retry = prepare_inventory(additional, **append_settings)
    assert not retry.append_review.added
    assert retry.append_review.reused == ("second", "helper")
    write_inventory(retry)
    assert len(bd.databases["new"][IMPORT_HISTORY]) == 1

    empty = prepare_inventory(package, **{**append_settings, "database": "empty"})
    assert empty.append_review.added == ("root", "helper")
    write_inventory(empty)
    assert imported_versions() == {42: ["empty", "new"], 43: ["new"]}


def check_replacement(package, settings):
    bd.projects.set_current("CLIC replacement integration")
    make_background()
    settings = {**settings, "project": bd.projects.current, "database": "model"}
    write_inventory(prepare_inventory(package, **settings))
    database = bd.Database("model")
    root, helper = database.get("root"), database.get("helper")
    root_id, helper_id = root.id, helper.id
    old_biosphere = next(iter(root.biosphere()))
    bd.parameters.new_activity_parameters(
        [{"name": "factor", "amount": 2, "database": "model", "code": "root"}],
        "root parameters",
    )
    ParameterizedExchange.create(
        exchange=old_biosphere.id, group="root parameters", formula="factor"
    )
    bd.calculation_setups["Existing setup"] = {"inv": [{root_id: 1}], "ia": []}
    dependent = helper.new_exchange(input=root.key, type="technosphere", amount=0)
    dependent.save()

    incoming = deepcopy(package)
    incoming["package"].update(
        root_version_ids=[46, 47],
        included_version_ids=[46, 47],
        focal_activity_codes=["root", "third"],
    )
    replacement = incoming["activities"][0]
    replacement["name"] = "Updated inventory"
    replacement["exchanges"][1]["amount"] = 3
    replacement["exchanges"].pop()
    third = deepcopy(replacement)
    third.update(code="third", name="Third inventory")
    third["exchanges"][0]["input"]["code"] = "third"
    third["exchanges"][1]["input"]["code"] = "root"
    third["provenance"] = {"dataset_slug": "third", "semantic_version": "1.0.0"}
    incoming["activities"].insert(1, third)
    incoming["activities"][2]["exchanges"].append(
        {
            "type": "technosphere",
            "amount": 0,
            "input": {"database": "__clic__", "code": "root"},
        }
    )

    replace_settings = {**settings, "append": True, "replace": True}
    prepared = prepare_inventory(incoming, **replace_settings)
    assert prepared.append_review.added == ("third",)
    assert prepared.append_review.reused == ("helper",)
    assert not prepared.append_review.conflicts
    assert [item.code for item in prepared.append_review.replacements] == ["root"]
    try:
        write_inventory(prepared)
    except ValueError as error:
        assert "Confirm the listed replacements" in str(error)
    else:
        raise AssertionError("Replaced an activity without confirmation")
    root["comment"] = "Edit after preview"
    root.save()
    try:
        write_inventory(prepared, confirm_replacement=True)
    except ValueError as error:
        assert "destination database changed" in str(error)
    else:
        raise AssertionError("Replaced an activity edited after preview")
    assert database.get("root")["comment"] == "Edit after preview"

    prepared = prepare_inventory(incoming, **replace_settings)
    before = deepcopy(bd.databases["model"])
    update_index = IndexManager.update_dataset

    def fail_after_index_update(index, activity):
        update_index(index, activity)
        if activity["name"] == "Updated inventory":
            raise OSError("Simulated replacement index failure")

    with patch.object(IndexManager, "update_dataset", fail_after_index_update):
        try:
            write_inventory(prepared, confirm_replacement=True)
        except OSError as error:
            assert "Simulated replacement index failure" in str(error)
        else:
            raise AssertionError("Failed replacement was accepted")
    assert database.get("root")["name"] == "root"
    assert bd.databases["model"] == before
    assert ("model", "third") not in database
    assert not database.search("Updated inventory")
    assert ParameterizedExchange.get_or_none(exchange=old_biosphere.id)
    assert old_biosphere.id in [
        exchange.id for exchange in database.get("root").biosphere()
    ]

    write_inventory(prepared, confirm_replacement=True)
    root, helper = database.get("root"), database.get("helper")
    assert (root.id, helper.id) == (root_id, helper_id)
    assert bd.calculation_setups["Existing setup"]["inv"] == [{root_id: 1}]
    assert (
        next(edge for edge in helper.technosphere() if edge.id == dependent.id).input.id
        == root_id
    )
    assert next(iter(database.get("third").technosphere())).input.id == root_id
    assert not list(root.biosphere())
    assert not ParameterizedExchange.get_or_none(exchange=old_biosphere.id)
    assert next(iter(root.technosphere()))["amount"] == 3
    assert database.search("Updated inventory")[0].id == root_id
    assert imported_versions() == {46: ["model"], 47: ["model"]}
    lca = bc.LCA({root: 1})
    lca.lci()
    assert abs(float(lca.inventory.sum()) - 18) < 1e-9
    retry = prepare_inventory(incoming, **replace_settings)
    assert retry.append_review.reused == ("root", "third", "helper")
    write_inventory(retry)
    assert len(bd.databases["model"][IMPORT_HISTORY]) == 1


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
    check_append(package, settings)
    bd.Database("new").get("root").delete()
    assert imported_versions() == {42: ["empty"], 43: ["new"]}
    check_replacement(package, settings)
