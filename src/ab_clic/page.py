"""Activity Browser page for selecting and importing CLIC inventories."""

import bw2data as bd
import requests
from activity_browser.plugins import ABAbstractPage
from qtpy import QtCore, QtWidgets

from .background import choose_target, suggest_backgrounds
from .catalog_table import COLUMNS, CatalogCell, CatalogTable
from .client import (
    MAX_EXPORT_VERSIONS,
    ClicClient,
    ExportDeferred,
    ExportRejected,
    has_noncommercial_license,
)
from .details_panel import CandidateDetails
from .inventory import check_project, prepare_inventory, write_inventory
from .pending import (
    ImportPlan,
    PendingExport,
    pending_exports,
    remove_pending,
    save_pending,
)
from .progress_dialog import run_preparation
from .records import imported_versions
from .review import ImportReview
from .token_entry import TokenEntry

SEARCH_FIELDS = (
    ("Dataset name", "name", "Search by dataset name"),
    ("Reference product", "reference_product", "Enter a reference product"),
    ("Location", "location", "Enter a location, e.g. CH"),
    ("Unit", "unit", "Enter a unit, e.g. kilogram"),
    ("Author", "author", "Enter an author name"),
    ("Project name", "project", "Enter a project name or acronym"),
    ("Keyword", "keyword", "Enter a keyword"),
    ("Classification code", "classification_node", "Enter a code, e.g. energy/solar"),
    ("Source publication year", "publication_year", "Enter a year, e.g. 2024"),
    ("Inventory reference year", "inventory_reference_year", "Enter a year, e.g. 2024"),
)


class ClicPage(ABAbstractPage):
    title = "CLIC"
    basePage = True

    def __init__(self, *args, host, **kwargs):
        super().__init__(*args, **kwargs)
        self.host = host
        self.selected_versions = {}
        self.previewed_version = None
        self.active_search = None
        self.page_number = 1
        self.background_project = None
        self.background_suggestions = {}
        self.imported = {}

        self.search_field = QtWidgets.QComboBox()
        self.search_field.setAccessibleName("Search field")
        for label, field, _placeholder in SEARCH_FIELDS:
            self.search_field.addItem(label, field)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(SEARCH_FIELDS[0][2])
        self.search_field.currentIndexChanged.connect(
            lambda index: self.search.setPlaceholderText(SEARCH_FIELDS[index][2])
        )
        self.search.returnPressed.connect(self._search)
        search_button = QtWidgets.QPushButton("Search")
        search_button.clicked.connect(self._search)
        paste_link = QtWidgets.QPushButton("Paste CLIC link")
        paste_link.clicked.connect(self._paste_link)
        self.exclude_noncommercial = QtWidgets.QCheckBox(
            "Exclude non-commercial licenses"
        )
        self.exclude_noncommercial.setToolTip(
            "Hide versions with a Creative Commons NonCommercial license. "
            "Undisclosed licenses stay visible."
        )
        self.exclude_noncommercial.toggled.connect(self._license_filter_changed)
        search_bar = QtWidgets.QHBoxLayout()
        search_bar.addWidget(self.search_field)
        search_bar.addWidget(self.search, 1)
        search_bar.addWidget(self.exclude_noncommercial)
        search_bar.addWidget(search_button)
        search_bar.addWidget(paste_link)

        self.results = CatalogTable()
        self.results.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.results.itemChanged.connect(self._toggle_version)
        self.results.cellClicked.connect(self._show_details)
        self.results.cellActivated.connect(self._show_details)
        self.results.column_filters_requested.connect(self._filter_columns)
        self.details = CandidateDetails(self)
        self.details.select_button.clicked.connect(self._select_preview)
        self.catalog_preview = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.catalog_preview.addWidget(self.results)
        self.catalog_preview.addWidget(self.details)
        self.catalog_preview.setStretchFactor(0, 3)
        self.catalog_preview.setStretchFactor(1, 2)
        self.catalog_preview.setChildrenCollapsible(False)
        self.details.hide()

        self.previous = QtWidgets.QPushButton("Previous")
        self.previous.clicked.connect(lambda: self._browse(-1))
        self.next = QtWidgets.QPushButton("Next")
        self.next.clicked.connect(lambda: self._browse(1))
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.status = QtWidgets.QLabel("Search CLIC to find inventories.")
        self.status.setTextFormat(QtCore.Qt.PlainText)
        pagination = QtWidgets.QHBoxLayout()
        pagination.addWidget(self.status, 1)
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)

        self.selection = QtWidgets.QGroupBox()
        self.selection_list = QtWidgets.QListWidget()
        self.selection_list.setMaximumHeight(95)
        self.selection_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.remove_button = QtWidgets.QPushButton("Remove selected")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._remove_selected)
        self.selection_list.itemSelectionChanged.connect(
            lambda: self.remove_button.setEnabled(
                bool(self.selection_list.selectedItems())
            )
        )
        self.clear_button = QtWidgets.QPushButton("Clear all")
        self.clear_button.clicked.connect(self._clear_selection)
        selection_buttons = QtWidgets.QVBoxLayout()
        selection_buttons.addWidget(self.remove_button)
        selection_buttons.addWidget(self.clear_button)
        selection_buttons.addStretch()
        selection_layout = QtWidgets.QHBoxLayout(self.selection)
        selection_layout.addWidget(self.selection_list, 1)
        selection_layout.addLayout(selection_buttons)

        self.target_version = QtWidgets.QLineEdit()
        self.target_version.setPlaceholderText("e.g. 3.12")
        self.target_system = QtWidgets.QComboBox()
        for label, code in [
            ("Select a system model", None),
            ("Cutoff", "cutoff"),
            ("Consequential", "consequential"),
        ]:
            self.target_system.addItem(label, code)
        self.technosphere = QtWidgets.QComboBox()
        self.biosphere = QtWidgets.QComboBox()
        self.background_status = QtWidgets.QLabel()
        self.background_status.setTextFormat(QtCore.Qt.PlainText)
        self.background_status.setWordWrap(True)
        self.use_background = QtWidgets.QPushButton("Use suggested background")
        self.use_background.clicked.connect(self._use_background)
        self.technosphere.currentTextChanged.connect(self._refresh_background_status)
        self.biosphere.currentTextChanged.connect(self._refresh_background_status)
        self.target_version.textChanged.connect(self._refresh_background_status)
        self.target_system.currentIndexChanged.connect(self._refresh_background_status)
        background_row = QtWidgets.QHBoxLayout()
        background_row.addWidget(self.background_status, 1)
        background_row.addWidget(self.use_background)
        self.database = QtWidgets.QLineEdit()
        self.database.setPlaceholderText("Use the CLIC package name")
        self.token = TokenEntry()
        form = QtWidgets.QFormLayout()
        form.addRow("ecoinvent version", self.target_version)
        form.addRow("ecoinvent system model", self.target_system)
        form.addRow("Project technosphere database", self.technosphere)
        form.addRow("Project biosphere database", self.biosphere)
        form.addRow(background_row)
        form.addRow("New foreground database", self.database)
        form.addRow("CLIC API token", self.token)

        self.import_button = QtWidgets.QPushButton("Prepare import")
        self.import_button.clicked.connect(self._prepare)
        self.pending_button = QtWidgets.QPushButton("Pending exports")
        self.pending_menu = QtWidgets.QMenu(self.pending_button)
        self.pending_button.setMenu(self.pending_menu)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.pending_button)
        buttons.addStretch(1)
        buttons.addWidget(self.import_button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(search_bar)
        layout.addWidget(self.catalog_preview, 1)
        layout.addLayout(pagination)
        layout.addWidget(self.selection)
        layout.addLayout(form)
        layout.addLayout(buttons)

        self.host.signals.project.changed.connect(self._load_databases)
        self.host.signals.database.written.connect(self._load_databases)
        self.host.signals.database.deleted.connect(self._load_databases)
        self._load_databases()

    def _load_databases(self, *_):
        project = bd.projects.current
        changed_project = project != self.background_project
        self.background_project = project
        names = sorted(bd.databases)
        for picker in (self.technosphere, self.biosphere):
            selected = "" if changed_project else picker.currentText()
            with QtCore.QSignalBlocker(picker):
                picker.clear()
                picker.addItem("")
                picker.addItems(names)
                picker.setCurrentText(selected if selected in names else "")
        self.background_suggestions = suggest_backgrounds()
        if changed_project:
            self.target_version.clear()
            self.target_system.setCurrentIndex(0)
            if len(self.background_suggestions) == 1:
                self._use_background()
        self._refresh_background_status()
        self._refresh_pending()
        self.imported = imported_versions()
        self._sync_selection()

    def _background_suggestion(self):
        name = self.technosphere.currentText()
        if name:
            return self.background_suggestions.get(name)
        if len(self.background_suggestions) == 1:
            return next(iter(self.background_suggestions.values()))
        return None

    def _use_background(self):
        suggestion = self._background_suggestion()
        if suggestion is not None:
            self.technosphere.setCurrentText(suggestion.technosphere)
            self.biosphere.setCurrentText(suggestion.biosphere)
            self.target_version.setText(suggestion.profile.version)
            self.target_system.setCurrentIndex(
                self.target_system.findData(suggestion.profile.model)
            )

    def _refresh_background_status(self, *_):
        suggestion = self._background_suggestion()
        if suggestion is None:
            self.use_background.setEnabled(False)
            text = (
                "Choose a technosphere database to see its suggested background."
                if self.background_suggestions and not self.technosphere.currentText()
                else "Choose the local databases and CLIC export target manually."
            )
        else:
            current_pair = (
                self.technosphere.currentText() == suggestion.technosphere
                and self.biosphere.currentText() == suggestion.biosphere
                and self.target_version.text().strip() == suggestion.profile.version
                and self.target_system.currentData() == suggestion.profile.model
            )
            self.use_background.setEnabled(not current_pair)
            text = f"Suggested target {suggestion.profile.label} with biosphere {suggestion.biosphere}."
        self.background_status.setText(text)

    def showEvent(self, event):
        self._load_databases()
        super().showEvent(event)

    def _search(self):
        self._load_page(self.search_field.currentData(), self.search.text().strip(), 1)

    def _browse(self, direction):
        if self.active_search is not None:
            self._load_page(
                *self.active_search, self.page_number + direction, direction=direction
            )

    def _filter_columns(self, filters):
        if self.active_search is None or self._load_page(
            *self.active_search, 1, column_filters=filters
        ):
            self.results.set_column_filters(filters)

    def _license_filter_changed(self, exclude):
        if exclude:
            self.selected_versions = {
                version_id: version
                for version_id, version in self.selected_versions.items()
                if not has_noncommercial_license(version)
            }
        self.results.setRowCount(0)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self._sync_selection()
        self._search()

    def _operation(self, title, func):
        try:
            return self.host.run_blocking_operation(title, func)
        except Exception:
            # The host has already displayed the worker error.
            return None

    def _load_page(self, field, query, number, *, direction=None, column_filters=None):
        exclude_noncommercial = self.exclude_noncommercial.isChecked()
        filters = (
            self.results.column_filters if column_filters is None else column_filters
        )

        def lookup():
            with requests.Session() as session:
                return ClicClient(session).search_datasets(
                    query,
                    number,
                    field=field,
                    exclude_noncommercial=exclude_noncommercial,
                    column_filters=filters,
                    direction=direction or 1,
                )

        page = self._operation("Search CLIC", lookup)
        if page is None:
            return False
        filters_active = exclude_noncommercial or bool(filters)
        if filters_active and not page["results"] and direction is not None:
            (self.previous if direction < 0 else self.next).setEnabled(False)
            self.status.setText(
                "No more datasets match the current filters in this direction."
            )
            return True
        self.active_search = (field, query)
        self.page_number = page["page"]
        with QtCore.QSignalBlocker(self.results):
            self.results.clearContents()
            self.results.setRowCount(len(page["results"]))
            for row, version in enumerate(page["results"]):
                check = QtWidgets.QTableWidgetItem()
                check.setData(QtCore.Qt.UserRole, version)
                check.setCheckState(
                    QtCore.Qt.Checked
                    if version["id"] in self.selected_versions
                    else QtCore.Qt.Unchecked
                )
                if not version["downloads_available"]:
                    check.setFlags(check.flags() & ~QtCore.Qt.ItemIsEnabled)
                    check.setToolTip("Export unavailable for this version")
                self.results.setItem(row, 0, check)
                for column, (key, _, _) in enumerate(COLUMNS[1:], start=1):
                    self.results.setItem(row, column, CatalogCell(key, version[key]))
            self.results.apply_sort()
        if not page["results"]:
            self.previous.setEnabled(False)
            self.next.setEnabled(False)
            self.status.setText("No published datasets match your search.")
        else:
            self.previous.setEnabled(bool(page["previous"]))
            self.next.setEnabled(bool(page["next"]))
            if filters_active:
                self.status.setText(
                    f"Catalog page {self.page_number} · {len(page['results'])} datasets shown"
                )
            else:
                self.status.setText(
                    f"Page {self.page_number} · {page['count']} published datasets"
                )
        return True

    def _show_details(self, row, column):
        if column == 0:
            return
        version = self.results.item(row, 0).data(QtCore.Qt.UserRole)
        self._preview(version)

    def _paste_link(self):
        link, accepted = QtWidgets.QInputDialog.getText(
            self, "Open a CLIC link", "Dataset or published-version link"
        )
        if not accepted or not link.strip():
            return

        def lookup():
            with requests.Session() as session:
                return ClicClient(session).dataset_from_link(link)

        version = self._operation("Open CLIC record", lookup)
        if version is not None:
            self._preview(version)

    def _preview(self, version):
        self.previewed_version = version
        self.details.set_version(version)
        self._sync_preview_selection()
        if self.details.isHidden():
            self.details.show()
            width = self.catalog_preview.width()
            self.catalog_preview.setSizes([width * 3 // 5, width * 2 // 5])

    def _sync_preview_selection(self):
        version = self.previewed_version
        if version is not None:
            selected = version["id"] in self.selected_versions
            self.details.select_button.setText(
                "Remove from selection" if selected else "Add to selection"
            )
            allowed = version.get("downloads_available", False) and (
                not self.exclude_noncommercial.isChecked()
                or not has_noncommercial_license(version)
            )
            self.details.select_button.setEnabled(selected or allowed)
            self.details.set_imported(self.imported.get(version["id"], []))

    def _select_preview(self):
        version = self.previewed_version
        if version is not None:
            self._set_version_selected(
                version, version["id"] not in self.selected_versions
            )

    def _toggle_version(self, item):
        if item.column() != 0:
            return
        version = item.data(QtCore.Qt.UserRole)
        self._set_version_selected(version, item.checkState() == QtCore.Qt.Checked)

    def _set_version_selected(self, version, checked):
        if checked:
            if len(self.selected_versions) >= MAX_EXPORT_VERSIONS:
                self._sync_selection()
                self._message(
                    f"Select up to {MAX_EXPORT_VERSIONS} versions per import."
                )
                return
            self.selected_versions[version["id"]] = version
        else:
            self.selected_versions.pop(version["id"], None)
        self._sync_selection()

    def _remove_selected(self):
        for item in self.selection_list.selectedItems():
            self.selected_versions.pop(item.data(QtCore.Qt.UserRole))
        self._sync_selection()

    def _clear_selection(self):
        self.selected_versions.clear()
        self._sync_selection()

    def _sync_selection(self):
        with QtCore.QSignalBlocker(self.results):
            for row in range(self.results.rowCount()):
                check = self.results.item(row, 0)
                version_id = check.data(QtCore.Qt.UserRole)["id"]
                checked = version_id in self.selected_versions
                check.setCheckState(
                    QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
                )
        self.selection_list.clear()
        for version in self.selected_versions.values():
            imported = self.imported.get(version["id"], [])
            status = " · Already imported" if imported else ""
            item = QtWidgets.QListWidgetItem(
                f"{version['name']} · {version['location']} · {version['semantic_version']}{status}"
            )
            item.setData(QtCore.Qt.UserRole, version["id"])
            if imported:
                item.setToolTip(f"Already imported in {', '.join(imported)}")
            self.selection_list.addItem(item)
        self.selection.setTitle(f"Selected versions ({len(self.selected_versions)})")
        self.clear_button.setEnabled(bool(self.selected_versions))
        self.import_button.setEnabled(bool(self.selected_versions))
        self._sync_preview_selection()

    def _prepare(self):
        versions = list(self.selected_versions.values())
        if not versions:
            return
        technosphere = self.technosphere.currentText()
        biosphere = self.biosphere.currentText()
        database = self.database.text().strip()
        target = {
            "family": "ecoinvent",
            "version": self.target_version.text().strip(),
            "system_model": self.target_system.currentData() or "",
        }
        self._run_import(
            ImportPlan(versions, target, technosphere, biosphere, database)
        )

    def _pending_path(self):
        return bd.projects.dir / "ab-clic-exports.json"

    def _refresh_pending(self):
        self.pending_menu.clear()
        try:
            saved = pending_exports(self._pending_path())
        except (OSError, ValueError, TypeError, KeyError):
            action = self.pending_menu.addAction("Unable to read saved exports")
            action.setEnabled(False)
            self.pending_button.show()
            return
        for entry in saved:
            plan = entry.plan
            name = (
                plan.versions[0]["name"]
                if len(plan.versions) == 1
                else f"{len(plan.versions)} selected versions"
            )
            menu = self.pending_menu.addMenu(
                f"{name} · {plan.target['version']} {plan.target['system_model']}"
            )
            resume = menu.addAction("Resume preparation")
            resume.triggered.connect(
                lambda _, export=entry: self._run_import(export.plan, export.status_url)
            )
            forget = menu.addAction("Remove from list")
            forget.triggered.connect(
                lambda _, export=entry: self._forget_export(export.plan)
            )
        self.pending_button.setText(f"Pending exports ({len(saved)})")
        self.pending_button.setVisible(bool(saved))

    def _forget_export(self, plan):
        try:
            remove_pending(self._pending_path(), plan)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._message(f"Could not update saved CLIC exports.\n\n{exc}")
        self._refresh_pending()

    def _run_import(self, plan: ImportPlan, status_url: str = ""):
        project = bd.projects.current
        token = self.token.text().strip()
        if not token:
            self._message("Enter a CLIC token with inventory download access.")
            return
        technosphere, biosphere = plan.technosphere, plan.biosphere
        if not all((project, technosphere, biosphere)):
            self._message(
                "Choose a Brightway project and both local background databases."
            )
            return
        path = self._pending_path()
        try:
            check_project(project, plan.database, technosphere, biosphere)
            choose_target(
                technosphere,
                biosphere,
                plan.target["version"],
                plan.target["system_model"],
            )
            if not status_url:
                saved = next(
                    (
                        entry
                        for entry in pending_exports(path)
                        if plan.same_export(entry.plan)
                    ),
                    None,
                )
                if saved is not None:
                    status_url = saved.status_url
                    if plan != saved.plan:
                        save_pending(path, PendingExport(plan, status_url))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._message(str(exc))
            return
        self.token.remember()

        def prepare(on_progress, stop):
            with requests.Session() as session:
                client = ClicClient(session)
                package = client.export(
                    plan.version_ids,
                    plan.target,
                    token,
                    on_progress=on_progress,
                    status_url=status_url,
                    on_job=lambda url: save_pending(path, PendingExport(plan, url)),
                    stop=stop,
                )
                client.add_inventory_metadata(
                    package, plan.versions, on_progress=on_progress
                )
            with self.host.safe_bw_connection():
                return prepare_inventory(
                    package,
                    project=project,
                    technosphere=technosphere,
                    biosphere=biosphere,
                    database=plan.database,
                    expected_target=plan.target,
                    on_progress=on_progress,
                )

        with self.host.protect_databases(
            [technosphere, biosphere], reason="Preparing CLIC import"
        ):
            try:
                prepared = run_preparation(self, prepare)
            except ExportDeferred:
                return
            except ExportRejected as exc:
                self._forget_export(plan)
                self._message(str(exc))
                return
            except Exception as exc:
                self._message(f"Could not prepare the CLIC import.\n\n{exc}")
                return
            finally:
                self._refresh_pending()
            if not self._confirm(prepared):
                return

            # AB3 also refreshes metadata synchronously on Brightway database
            # registration and flush. Keep that part on the Qt GUI thread.
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                write_inventory(prepared)
            except Exception as exc:
                error = str(exc)
            else:
                error = None
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

        if error is not None:
            self._message(f"Brightway could not write the inventory.\n\n{error}")
        else:
            self._forget_export(plan)
            self.imported = imported_versions()
            self._sync_selection()
            self._message(
                f"Imported {len(prepared.importer.data)} activities into {prepared.database}."
            )

    def _confirm(self, prepared):
        return ImportReview(prepared, self).exec() == QtWidgets.QDialog.Accepted

    def _message(self, text):
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("CLIC")
        dialog.setTextFormat(QtCore.Qt.PlainText)
        dialog.setText(text)
        dialog.exec()
