"""Activity Browser page for selecting and importing CLIC inventories."""

import bw2data as bd
import requests
from activity_browser.plugins import ABAbstractPage
from qtpy import QtCore, QtWidgets

from .catalog_table import COLUMNS, CatalogCell, CatalogTable
from .client import MAX_EXPORT_VERSIONS, ClicClient, has_noncommercial_license
from .details_dialog import CandidateDetails
from .inventory import prepare_inventory, write_inventory
from .progress_dialog import run_preparation
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
        self.details_dialog = None
        self.active_search = None
        self.page_number = 1

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

        self.results = CatalogTable()
        self.results.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.results.itemChanged.connect(self._toggle_version)
        self.results.cellClicked.connect(self._show_details)
        self.results.cellActivated.connect(self._show_details)
        self.results.column_filters_requested.connect(self._filter_columns)

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

        self.target_version = QtWidgets.QLineEdit("3.12")
        self.target_system = QtWidgets.QComboBox()
        for label, code in [
            ("Cutoff", "cutoff"),
            ("APOS", "apos"),
            ("Consequential", "consequential"),
        ]:
            self.target_system.addItem(label, code)
        self.technosphere = QtWidgets.QComboBox()
        self.biosphere = QtWidgets.QComboBox()
        self.database = QtWidgets.QLineEdit()
        self.database.setPlaceholderText("Use the CLIC package name")
        self.token = TokenEntry()
        form = QtWidgets.QFormLayout()
        form.addRow("ecoinvent version", self.target_version)
        form.addRow("ecoinvent system model", self.target_system)
        form.addRow("Project technosphere database", self.technosphere)
        form.addRow("Project biosphere database", self.biosphere)
        form.addRow("New foreground database", self.database)
        form.addRow("CLIC API token", self.token)

        self.import_button = QtWidgets.QPushButton("Prepare import")
        self.import_button.clicked.connect(self._prepare)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(search_bar)
        layout.addWidget(self.results, 1)
        layout.addLayout(pagination)
        layout.addWidget(self.selection)
        layout.addLayout(form)
        layout.addWidget(self.import_button, 0, QtCore.Qt.AlignRight)

        self.host.signals.project.changed.connect(self._load_databases)
        self._load_databases()
        self._sync_selection()

    def _load_databases(self, *_):
        names = sorted(bd.databases)
        for picker in (self.technosphere, self.biosphere):
            selected = picker.currentText()
            picker.clear()
            picker.addItem("")
            picker.addItems(names)
            picker.setCurrentText(selected if selected in names else "")

        candidates = [name for name in names if "biosphere" in name.casefold()]
        if not self.biosphere.currentText() and len(candidates) == 1:
            self.biosphere.setCurrentText(candidates[0])

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
        if self.details_dialog is None:
            self.details_dialog = CandidateDetails(self)
        self.details_dialog.set_version(version)
        self.details_dialog.show()
        self.details_dialog.raise_()

    def _toggle_version(self, item):
        if item.column() != 0:
            return
        version = item.data(QtCore.Qt.UserRole)
        if item.checkState() == QtCore.Qt.Checked:
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
            item = QtWidgets.QListWidgetItem(
                f"{version['name']} · {version['location']} · {version['semantic_version']}"
            )
            item.setData(QtCore.Qt.UserRole, version["id"])
            self.selection_list.addItem(item)
        self.selection.setTitle(f"Selected versions ({len(self.selected_versions)})")
        self.clear_button.setEnabled(bool(self.selected_versions))
        self.import_button.setEnabled(bool(self.selected_versions))

    def _prepare(self):
        versions = list(self.selected_versions.values())
        if not versions:
            return
        project = bd.projects.current
        token = self.token.text().strip()
        technosphere = self.technosphere.currentText()
        biosphere = self.biosphere.currentText()
        database = self.database.text().strip()
        target = {
            "family": "ecoinvent",
            "version": self.target_version.text().strip(),
            "system_model": self.target_system.currentData(),
        }
        if not all((project, token, technosphere, biosphere, target["version"])):
            self._message(
                "Choose both Brightway databases, enter an ecoinvent version and provide a CLIC token."
            )
            return
        if technosphere == biosphere:
            self._message("Choose separate technosphere and biosphere databases.")
            return
        self.token.remember()

        def prepare(on_progress):
            with requests.Session() as session:
                client = ClicClient(session)
                package = client.export(
                    [version["id"] for version in versions],
                    target,
                    token,
                    on_progress=on_progress,
                )
                client.add_inventory_metadata(
                    package, versions, on_progress=on_progress
                )
            with self.host.safe_bw_connection():
                return prepare_inventory(
                    package,
                    project=project,
                    technosphere=technosphere,
                    biosphere=biosphere,
                    database=database,
                    on_progress=on_progress,
                )

        with self.host.protect_databases(
            [technosphere, biosphere], reason="Preparing CLIC import"
        ):
            try:
                prepared = run_preparation(self, prepare)
            except Exception as exc:
                self._message(f"Could not prepare the CLIC import.\n\n{exc}")
                return
            if not self._confirm(versions, prepared):
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
            self._message(
                f"Imported {len(prepared.importer.data)} activities into {prepared.database}."
            )

    def _confirm(self, versions, prepared):
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Import from CLIC")
        dialog.setTextFormat(QtCore.Qt.PlainText)
        if len(versions) == 1:
            version = versions[0]
            subject = f"{version['name']} ({version['semantic_version']})"
        else:
            subject = f"{len(versions)} CLIC versions"
        dialog.setText(f"Import {subject} into {prepared.project}?")
        details = f"{len(prepared.importer.data)} activities will be written to {prepared.database}."
        if prepared.warnings:
            details += f" CLIC reported {len(prepared.warnings)} conversion warnings."
            dialog.setDetailedText(
                "\n".join(
                    warning.get("message") or warning.get("detail") or str(warning)
                    for warning in prepared.warnings
                )
            )
        dialog.setInformativeText(details)
        import_button = dialog.addButton("Import", QtWidgets.QMessageBox.AcceptRole)
        dialog.addButton(QtWidgets.QMessageBox.Cancel)
        dialog.exec()
        return dialog.clickedButton() == import_button

    def _message(self, text):
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("CLIC")
        dialog.setTextFormat(QtCore.Qt.PlainText)
        dialog.setText(text)
        dialog.exec()
