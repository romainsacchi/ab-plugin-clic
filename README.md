# CLIC for Activity Browser 3

Browse published life cycle inventories from the [Curated Life cycle Inventory Collection (CLIC)](https://clic.psi.ch/) and import them into your active Brightway project.

## Install the alpha

Use a dedicated Python environment. Python 3.12 on macOS is the tested setup. The plugin requires Activity Browser's [plugin-enabled development build](https://github.com/LCA-ActivityBrowser/activity-browser/tree/aa164283a3a171ccdeed7fba1fc431a89b9d5c12). The standard Activity Browser 3.0.0 release and its standalone installers lack the plugin loader.

From the root of this repository, run:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install \
  'activity-browser @ git+https://github.com/LCA-ActivityBrowser/activity-browser.git@aa164283a3a171ccdeed7fba1fc431a89b9d5c12' \
  .
activity-browser
```

To install from a built wheel, replace the final `.` with the wheel path. For development, replace it with `-e .`.

In Activity Browser, open **Settings → Plugins**, enable **CLIC**, save, and restart. Then open **Plugins → CLIC → Browse and import**.

## Browse and import

1. Search by dataset name, reference product, location, unit, author, project name or acronym, keyword, classification code, source publication year, or inventory reference year. Click a result to preview its metadata. Use **Paste CLIC link** to open a dataset or a specific published version.
2. Check the datasets to import. The **Selected versions** list follows you across pages and searches. **Exclude non-commercial licenses** hides versions with Creative Commons NonCommercial terms and removes them from the selection. Datasets with undisclosed licenses stay visible. [CLIC license guide](https://clic.psi.ch/licenses/)
3. Choose the local technosphere and biosphere databases and the matching ecoinvent target. The plugin suggests a pair when it recognizes the ecoinvent release and finds one linked biosphere database.
4. Select **Get your token** to create a CLIC API token with inventory download access. The plugin remembers it in your operating system’s credential store when available. Use **Forget token** to remove it.
5. Select **Prepare import** to request an export for up to 100 selected versions and their connected suppliers. Review the included datasets, licenses, conversion warnings, and any unresolved links. Select **Import** to write a new foreground database.

The catalog shows the latest published version of each dataset. Click a column header to sort the current page, drag its borders to resize it, or right-click the header to filter across pages.

If CLIC is still preparing an export, select **Continue later** and resume through **Pending exports** in the same Brightway project. After import, Activity Browser’s **Description** tab shows the available CLIC metadata for each version, including publication details and technology readiness level. The new database stores an import receipt in its Brightway metadata under `clic_import`.

## Backgrounds and unresolved links

The alpha supports classic single-output ecoinvent cutoff and consequential databases using CLIC Brightway JSON schema 1.2. It imports the exported exchange amounts and retains parameter declarations as metadata. Parameter groups for recalculating formulas, product-node and multifunctional backgrounds, and UVEK backgrounds are outside the scope of this alpha.

An unresolved link prevents the import. Check the exchange and database shown in the review. If the review says CLIC omitted a supplier ID, prepare smaller batches. For the battery-pack datasets, separate NMC622 and NMC811. The fix for combined exports is on the CLIC server side.

## Development

Use the same environment as Activity Browser. To run the tests and lint checks, install the plugin in editable mode and install `ruff`.

```bash
python -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

The tests use simulated CLIC responses and an isolated Brightway project. To build and check the source distribution and wheel, install `build` and a current `twine`.

```bash
python -m build
python -m twine check --strict dist/*
```

[Issue tracker](https://github.com/romainsacchi/ab-plugin-clic/issues) · [Activity Browser plugin API](https://github.com/LCA-ActivityBrowser/activity-browser/blob/aa164283a3a171ccdeed7fba1fc431a89b9d5c12/docs/plugins/api-reference.md) · [CLIC API](https://clic.psi.ch/api/docs/)

## Releases

Use a Git tag that matches the version in `pyproject.toml`, such as `v0.1.0a1`.
Run **Publish to PyPI** manually on the tag to build and check both distributions.
Publishing the corresponding draft GitHub release starts the PyPI upload workflow.

For the first release, set up a [pending Trusted Publisher](https://pypi.org/manage/account/publishing/) on PyPI with project name `ab-plugin-clic`, owner `romainsacchi`, repository `ab-plugin-clic`, workflow `publish-pypi.yml`, and environment `pypi`. GitHub Actions exchanges its identity for short-lived PyPI upload credentials.

## License

The plugin is licensed under LGPL-3.0-or-later. See [LICENSE](https://github.com/romainsacchi/ab-plugin-clic/blob/main/LICENSE) and the accompanying [GPL text](https://github.com/romainsacchi/ab-plugin-clic/blob/main/COPYING). Imported datasets retain their individual licenses.
