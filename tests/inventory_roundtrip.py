"""Import a synthetic CLIC package in the temporary project used by unittest."""

from copy import deepcopy

import bw2calc as bc
import bw2data as bd
from bw2data.signals import on_database_write

from ab_clic.inventory import prepare_inventory, write_inventory


def make_background():
    bd.Database("biosphere").write(
        {
            ("biosphere", "co2"): {
                "name": "Carbon dioxide",
                "categories": ("air",),
                "unit": "kilogram",
                "type": "emission",
            },
        }
    )
    bd.Database("background").write(
        {
            ("background", "supply"): {
                "name": "Supply",
                "reference product": "input",
                "location": "CH",
                "unit": "kilogram",
                "exchanges": [
                    {
                        "input": ("background", "supply"),
                        "type": "production",
                        "amount": 1,
                    },
                    {"input": ("biosphere", "co2"), "type": "biosphere", "amount": 3},
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
        "package": {"suggested_database_name": "original", "root_version_ids": [42]},
        "activities": activities,
    }


if __name__ == "__main__":
    bd.projects.set_current("CLIC integration test")
    make_background()
    package = make_package()
    settings = dict(
        project=bd.projects.current,
        technosphere="background",
        biosphere="biosphere",
        database="new",
    )
    missing = deepcopy(package)
    missing["activities"][1]["exchanges"][1]["name"] = "Missing supply"
    try:
        prepare_inventory(missing, **settings)
    except ValueError as exc:
        assert "Missing supply" in str(exc)
    else:
        raise AssertionError("An unlinked exchange was accepted")
    assert "new" not in bd.databases

    prepared = prepare_inventory(package, **settings)
    assert package["activities"][0]["database"] == "original"
    signalled = []

    @on_database_write.connect
    def record_write(_sender, name):
        signalled.append(name)

    write_inventory(prepared)
    assert "new" in signalled, signalled
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
