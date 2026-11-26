"""Review the CLIC package and link diagnostics before writing to Brightway."""

import json
from dataclasses import dataclass

from qtpy import QtCore, QtWidgets

from .inventory import PreparedInventory


@dataclass(frozen=True)
class PackageActivity:
    name: str
    role: str
    version: str
    license: str
    public_url: str


def package_activities(prepared: PreparedInventory) -> list[PackageActivity]:
    selected = set(prepared.manifest.get("focal_activity_codes") or ())
    if not selected and (code := prepared.manifest.get("focal_activity_code")):
        selected.add(code)
    helpers = set(prepared.manifest.get("generated_helper_codes") or ())
    rows = []
    for activity in prepared.importer.data:
        provenance = activity.get("provenance") or {}
        catalog = provenance.get("clic_catalog") or {}
        code = activity["code"]
        if code in helpers:
            role = "Generated helper"
        elif code in selected:
            role = "Selected dataset"
        else:
            role = "Connected supplier"
        license_code = catalog.get("selected_license")
        if license_code == "UNDISCLOSED":
            license = "Undisclosed · Review terms"
        elif license_code and license_code.startswith("CC-BY-NC-"):
            license = f"{catalog.get('selected_license_label') or license_code} · Non-commercial"
        elif role == "Generated helper":
            license = ""
        else:
            license = (
                catalog.get("selected_license_label") or license_code or "Unavailable"
            )
        rows.append(
            PackageActivity(
                activity["name"],
                role,
                provenance.get("semantic_version", ""),
                license,
                catalog.get("public_url", ""),
            )
        )
    return rows


class ImportReview(QtWidgets.QDialog):
    def __init__(self, prepared: PreparedInventory, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review CLIC import")
        self.resize(930, 565)
        summary = QtWidgets.QFormLayout()
        target = " ".join(
            prepared.target.get(key, "")
            for key in ("family", "version", "system_model")
        ).strip()
        for label, value in (
            ("Brightway project", prepared.project),
            ("Destination database", prepared.database),
            ("CLIC export target", target),
            ("Technosphere", prepared.technosphere),
            ("Biosphere", prepared.biosphere),
        ):
            field = QtWidgets.QLabel(value)
            field.setTextFormat(QtCore.Qt.PlainText)
            field.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            summary.addRow(label, field)

        activities = package_activities(prepared)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(
            _table(
                ["Activity", "Role", "Version", "CLIC license", "CLIC record"],
                [
                    (item.name, item.role, item.version, item.license, item.public_url)
                    for item in activities
                ],
            ),
            f"Activities ({len(activities)})",
        )
        if prepared.warnings:
            warnings = QtWidgets.QPlainTextEdit()
            warnings.setReadOnly(True)
            warnings.setPlainText(
                "\n\n".join(
                    (
                        json.dumps(item, ensure_ascii=False, indent=2)
                        if isinstance(item, dict)
                        else str(item)
                    )
                    for item in prepared.warnings
                )
            )
            tabs.addTab(warnings, f"Conversion warnings ({len(prepared.warnings)})")
        if prepared.issues:
            diagnostics = _table(
                ["Activity", "Exchange", "Database checked", "Problem", "Next action"],
                [
                    (
                        issue.activity,
                        issue.exchange,
                        issue.database,
                        issue.reason,
                        issue.next_action,
                    )
                    for issue in prepared.issues
                ],
            )
            tabs.addTab(diagnostics, f"Unresolved links ({len(prepared.issues)})")
            tabs.setCurrentWidget(diagnostics)

        append = prepared.append_review
        status = QtWidgets.QLabel()
        replacements = append.replacements if append is not None else ()
        if append is not None:
            changes = (
                f"{len(append.added)} to add · {len(append.reused)} identical to reuse"
            )
            if replacements:
                changes += f" · {len(replacements)} to replace"
            summary.addRow(
                "Destination changes",
                QtWidgets.QLabel(changes),
            )
        if replacements or (append is not None and append.conflicts):
            names = {
                activity["code"]: activity["name"]
                for activity in prepared.importer.data
            }
        if replacements:
            replace_tab = _table(
                ["Existing activity", "Incoming activity", "Activity code"],
                [
                    (item.existing_name, names[item.code], item.code)
                    for item in replacements
                ],
            )
            tabs.addTab(replace_tab, f"Replacements ({len(replacements)})")
            if not prepared.issues:
                tabs.setCurrentWidget(replace_tab)
        if append is not None and append.conflicts:
            conflicts = _table(
                ["Incoming activity", "Activity code"],
                [(names[code], code) for code in append.conflicts],
            )
            tabs.addTab(
                conflicts, f"Conflicting activity codes ({len(append.conflicts)})"
            )
            tabs.setCurrentWidget(conflicts)
            status.setText(
                "The destination has different data for the listed activity codes. "
                "Choose another destination or review the existing activities."
            )
        elif prepared.issues:
            status.setText("Resolve the listed exchange links before importing.")
        elif replacements:
            status.setText(
                "This replaces the listed activity data and outgoing exchanges, including local edits. "
                "Activity IDs and incoming links are kept."
            )
        elif append is not None:
            status.setText(
                "Ready to add activities to the destination database."
                if append.added
                else "All activities in this package are already present and identical."
            )
        else:
            status.setText(f"Ready to write {len(activities)} activities to Brightway.")
        status.setWordWrap(True)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        self.import_button = buttons.addButton(
            "Replace and import" if replacements else "Import",
            QtWidgets.QDialogButtonBox.AcceptRole,
        )
        can_import = not prepared.issues and not (append and append.conflicts)
        self.import_button.setEnabled(can_import and not replacements)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(summary)
        layout.addWidget(status)
        layout.addWidget(tabs, 1)
        if replacements:
            confirm = QtWidgets.QCheckBox(
                "Replace the listed activities and their outgoing exchanges"
            )
            confirm.setEnabled(can_import)
            confirm.toggled.connect(
                lambda checked: self.import_button.setEnabled(can_import and checked)
            )
            layout.addWidget(confirm)
        layout.addWidget(buttons)


def _table(headers, rows):
    table = QtWidgets.QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.verticalHeader().hide()
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
    table.horizontalHeader().setDefaultSectionSize(170)
    table.horizontalHeader().setStretchLastSection(True)
    return table
