"""Activity Browser page for selecting and importing a CLIC inventory."""

import bw2data as bd
import requests
from activity_browser.plugins import ABAbstractPage
from qtpy import QtCore, QtWidgets

from .client import ClicClient
from .inventory import prepare_inventory, write_inventory


class ClicPage(ABAbstractPage):
    title = "CLIC"
    basePage = True

    def __init__(self, *args, host, **kwargs):
        super().__init__(*args, **kwargs)
        self.host = host
        self.versions = []
        self.search_name = ""
        self.page_number = 1

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search published inventories by name")
        self.search.returnPressed.connect(self._search)
        search_button = QtWidgets.QPushButton("Search")
        search_button.clicked.connect(self._search)
        search_bar = QtWidgets.QHBoxLayout()
        search_bar.addWidget(self.search)
        search_bar.addWidget(search_button)

        self.results = QtWidgets.QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(
            ["Inventory", "Location", "Version", "CLIC ID"]
        )
        self.results.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        self.results.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.results.currentCellChanged.connect(self._select_version)

        self.previous = QtWidgets.QPushButton("Previous")
        self.previous.clicked.connect(
            lambda: self._load_page(self.search_name, self.page_number - 1)
        )
        self.next = QtWidgets.QPushButton("Next")
        self.next.clicked.connect(
            lambda: self._load_page(self.search_name, self.page_number + 1)
        )
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.status = QtWidgets.QLabel("Search CLIC to select an inventory.")
        self.status.setTextFormat(QtCore.Qt.PlainText)
        pagination = QtWidgets.QHBoxLayout()
        pagination.addWidget(self.status, 1)
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)

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
        self.token = QtWidgets.QLineEdit()
        self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        form = QtWidgets.QFormLayout()
        form.addRow("ecoinvent version", self.target_version)
        form.addRow("ecoinvent system model", self.target_system)
        form.addRow("Project technosphere database", self.technosphere)
        form.addRow("Project biosphere database", self.biosphere)
        form.addRow("New foreground database", self.database)
        form.addRow("CLIC API token", self.token)

        self.import_button = QtWidgets.QPushButton("Prepare import")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._prepare)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(search_bar)
        layout.addWidget(self.results, 1)
        layout.addLayout(pagination)
        layout.addLayout(form)
        layout.addWidget(self.import_button, 0, QtCore.Qt.AlignRight)

        self.host.signals.project.changed.connect(self._load_databases)
        self._load_databases()

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
        self._load_page(self.search.text().strip(), 1)

    def _operation(self, title, func):
        try:
            return self.host.run_blocking_operation(title, func)
        except Exception:
            # The host has already displayed the worker error.
            return None

    def _load_page(self, name, number):
        def lookup():
            with requests.Session() as session:
                return ClicClient(session).search_versions(name, number)

        page = self._operation("Search CLIC", lookup)
        if page is None:
            return
        self.search_name = name
        self.page_number = number
        self.versions = page["results"]
        self.results.setRowCount(0)
        self.results.setRowCount(len(self.versions))
        for row, version in enumerate(self.versions):
            for column, field in enumerate(
                ("name", "location", "semantic_version", "id")
            ):
                self.results.setItem(
                    row, column, QtWidgets.QTableWidgetItem(str(version[field]))
                )
        self.previous.setEnabled(bool(page["previous"]))
        self.next.setEnabled(bool(page["next"]))
        self.status.setText(f"Page {number} · {page['count']} published versions")
        if self.versions:
            self.results.setCurrentCell(0, 0)
        else:
            self.import_button.setEnabled(False)

    def _select_version(self, row, *_):
        available = (
            0 <= row < len(self.versions) and self.versions[row]["downloads_available"]
        )
        self.import_button.setEnabled(available)

    def _prepare(self):
        row = self.results.currentRow()
        if not 0 <= row < len(self.versions):
            return
        version = self.versions[row]
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

        def prepare():
            with requests.Session() as session:
                package = ClicClient(session).export(version["id"], target, token)
            return prepare_inventory(
                package,
                project=project,
                technosphere=technosphere,
                biosphere=biosphere,
                database=database,
            )

        with self.host.protect_databases(
            [technosphere, biosphere], reason="Preparing CLIC import"
        ):
            prepared = self._operation("Prepare CLIC import", prepare)
            if prepared is None or not self._confirm(version, prepared):
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

    def _confirm(self, version, prepared):
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Import CLIC inventory")
        dialog.setTextFormat(QtCore.Qt.PlainText)
        dialog.setText(
            f"Import {version['name']} ({version['semantic_version']}) into {prepared.project}?"
        )
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
