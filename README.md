# CLIC for Activity Browser 3

Development prototype for browsing and importing published inventories from the [Curated Life cycle Inventory Collection](https://clic.psi.ch/) into the active Brightway project.

## Run the prototype

Use a dedicated environment with Python 3.11–3.14. The upstream `plugins` branch at commit `aa164283a3a171ccdeed7fba1fc431a89b9d5c12` is the reference host and requires `bw2data` 4.8 for startup. Activity Browser 3.0.0 ships without the plugin loader.

```bash
python -m pip install 'activity-browser @ git+https://github.com/LCA-ActivityBrowser/activity-browser.git@aa164283a3a171ccdeed7fba1fc431a89b9d5c12'
python -m pip install -e .
activity-browser
```

Enable CLIC under **Settings → Plugins**, save, and restart. Open **Plugins → CLIC → Browse and import**. Open a project with compatible ecoinvent technosphere and biosphere databases. Use the search dropdown to look up versions by name, reference product, location, unit, author, project name or acronym, keyword, classification code, source publication year, or inventory reference year. **Exclude non-commercial licenses** hides versions with a Creative Commons NonCommercial license and removes those versions from the current selection. Versions with undisclosed licenses stay visible. Click a result name to preview its metadata. Tick the boxes beside the versions you want. The **Selected versions** list follows you across searches and pages. [CLIC license guide](https://clic.psi.ch/licenses/)

The catalog shows the latest published version of each dataset. Click a column header to sort the current page and click it again to reverse the order. The current candidate stays in view. Drag the header dividers to resize columns. Right-click **Inventory**, **Location**, **Version**, or **CLIC ID** to show or hide matching rows, or to clear a filter. Column filters apply across pages and preserve the import selection.

The preview opens beside the catalog. **Paste CLIC link** accepts a dataset page or a link to an exact published version. Add that version from the preview to keep your current search results and selection.

Confirm the local technosphere and biosphere databases and the CLIC export target. The plugin suggests a pair when it recognizes the ecoinvent release and sees a unique elementary-flow database in its recorded Brightway dependencies. If several pairs are available, choose a technosphere database and use **Use suggested background**. Custom projects can enter their background manually. Use **Get your token** to open your CLIC profile and create a token with inventory download access. The plugin stores the token in the system credential store and restores it on startup. Use **Forget token** to remove it from the credential store. If the system credential store is unavailable, the token can still be used for the current session.

The plugin requests one export with up to 100 selected versions and their connected CLIC suppliers. CLIC includes shared suppliers once. The review lists selected datasets, connected suppliers, generated helpers, available licenses, and conversion warnings. An unresolved link identifies the exchange, database checked, and what to try next. A blank foreground name uses the package's suggested name. Existing databases are protected from overwrite.

**Prepare import** shows a progress bar that advances by step. While CLIC prepares an export, use **Continue later** and return through **Pending exports** in the same Brightway project. The saved job retains its version selection and target. The **Description** tab retains any export comment and adds the published CLIC metadata for that exact version, including the source publication, authors and year, and technology readiness level where provided.

Each completed foreground database stores a `clic_import` record in Brightway metadata. It includes the selected and dependency version IDs, source links, export target, local background databases, and conversion warnings. The preview and selection show **Already imported** for exact CLIC versions present in the active project.

## Feasibility

- AB3's provisional contribution API supports an independent page and **Plugins** menu action. The prototype uses the public `PluginContext` API for worker operations and database protection. Integration directly into AB's **Database** menu would need an upstream contribution hook.
- CLIC exposes anonymous version search and asynchronous authenticated Brightway JSON export. Schema 1.2 carries the inventory, parameters, uncertainty, and provenance. The prototype retains activity parameters as metadata and targets classic single-output ecoinvent projects. Support for product-node and multifunctional backgrounds needs a separate import check. UVEK targets also need validation before exposing them in the UI.
- The plugin matches technosphere and biosphere links by exact Brightway field hashes and reports missing or ambiguous matches before import. It writes through `Database.write(..., signal=True)` so Activity Browser can refresh the database pane. Downloads and link preparation run in a worker using Activity Browser's Brightway connection cleanup. The final write stays on the GUI thread because the host's metadata subscriber can create Qt objects synchronously during a worker write.
- The AB host and plugin are installable in the same Python environment. Standalone builds need an upstream deployment decision about how they can discover and load third-party plugin distributions.

### Checks

```bash
python -m unittest discover -s tests -v
```

The suite uses a synthetic Brightway project and simulated CLIC export responses to exercise import without using an account token or licensed background data.

The macOS Activity Browser smoke test verified project-aware suggestions, a saved export resumed without a second submission, the dependency and license review, exact-version links alongside the latest-version catalog, a confirmed write to an isolated project, and the resulting **Already imported** indicator. A live authenticated export for CLIC version `6435` linked against an ecoinvent 3.12 cutoff project with zero unresolved exchanges. The live check opened the project in read-only mode. Standalone installation remains unverified.

[AB plugin API](https://github.com/LCA-ActivityBrowser/activity-browser/blob/plugins/docs/plugins/api-reference.md) · [CLIC API](https://clic.psi.ch/api/docs/)
