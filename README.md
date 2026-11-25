# CLIC for Activity Browser 3

Development prototype for browsing and importing published inventories from the [Curated Life cycle Inventory Collection](https://clic.psi.ch/) into the active Brightway project.

## Run the prototype

Use a dedicated environment with Python 3.11–3.14. The upstream `plugins` branch at commit `aa164283a3a171ccdeed7fba1fc431a89b9d5c12` is the reference host and requires `bw2data` 4.8 for startup. Activity Browser 3.0.0 ships without the plugin loader.

```bash
python -m pip install 'activity-browser @ git+https://github.com/LCA-ActivityBrowser/activity-browser.git@aa164283a3a171ccdeed7fba1fc431a89b9d5c12'
python -m pip install -e .
activity-browser
```

Enable CLIC under **Settings → Plugins**, save, and restart. Open **Plugins → CLIC → Browse and import**. Open a project with compatible ecoinvent technosphere and biosphere databases. Search by name and tick the boxes beside the published versions you want. The **Selected versions** list follows you across searches and pages. Choose the local databases and export target, and provide a CLIC token with inventory download scope. The token stays in the masked input for the lifetime of the page.

The plugin requests one export with up to 100 selected versions and their connected CLIC suppliers. CLIC includes shared suppliers once. The plugin checks links and lets you review conversion warnings before writing one new foreground database. A blank foreground name uses the package's suggested name. Existing databases are protected from overwrite.

## Feasibility

- AB3's provisional contribution API supports an independent page and **Plugins** menu action. The prototype uses the public `PluginContext` API for worker operations and database protection. Integration directly into AB's **Database** menu would need an upstream contribution hook.
- CLIC exposes anonymous version search and asynchronous authenticated Brightway JSON export. Schema 1.2 carries the inventory, parameters, uncertainty, and provenance. The prototype retains activity parameters as metadata and targets classic single-output ecoinvent projects. Support for product-node and multifunctional backgrounds needs a separate import check. UVEK targets also need validation before exposing them in the UI.
- Brightway's `LCIImporter` can match the external links. The prototype writes through `Database.write(..., signal=True)` because `LCIImporter.write_database()` does not forward the write signal to the backend. Downloads and link preparation run in the AB worker. The final write runs on the GUI thread because the host's metadata subscriber can create Qt objects synchronously during a worker write. An upstream fix to marshal those metadata callbacks to the GUI thread would let large writes move into the worker.
- The AB host and plugin are installable in the same Python environment. Standalone builds need an upstream deployment decision about how they can discover and load third-party plugin distributions.

### Checks

```bash
python -m unittest discover -s tests -v
```

The suite uses a synthetic Brightway project and simulated CLIC export responses to exercise import without using an account token or licensed background data.

The first macOS smoke test verified entry-point activation, opening the CLIC page through the real AB menu, import of two synthetic activities, and the subsequent AB database event and metadata refresh. The live anonymous catalog returned published versions. A live authenticated export, a real ecoinvent import, and standalone installation still need validation.

[AB plugin API](https://github.com/LCA-ActivityBrowser/activity-browser/blob/plugins/docs/plugins/api-reference.md) · [CLIC API](https://clic.psi.ch/api/docs/)
