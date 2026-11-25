"""Preview the description and metadata from a CLIC catalog result."""

from qtpy import QtCore, QtWidgets

from .metadata import catalog_metadata


class CandidateDetails(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setMinimumWidth(230)

        self.heading = QtWidgets.QLabel()
        self.heading.setTextFormat(QtCore.Qt.PlainText)
        self.heading.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.heading.setWordWrap(True)
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)

        self.form = QtWidgets.QFormLayout()
        self.form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.fields = {}
        for title in (
            "CLIC version",
            "Reference product",
            "Location",
            "Unit",
            "Classification",
            "License",
            "Published on CLIC",
            "Source background",
            "Source publication",
            "Publication authors",
            "Publication year",
            "Inventory authors",
            "Projects",
            "Technology readiness level (TRL)",
            "Source citation",
        ):
            value = QtWidgets.QLabel()
            value.setTextFormat(QtCore.Qt.PlainText)
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.form.addRow(title, value)
            self.fields[title] = value

        self.description = QtWidgets.QLabel()
        self.description.setTextFormat(QtCore.Qt.PlainText)
        self.description.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.description.setWordWrap(True)
        description_label = QtWidgets.QLabel("Description")
        font = description_label.font()
        font.setBold(True)
        description_label.setFont(font)

        content = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(content)
        body.addWidget(self.heading)
        body.addWidget(description_label)
        body.addWidget(self.description)
        body.addLayout(self.form)
        body.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        self.select_button = QtWidgets.QPushButton("Add to selection")
        self.imported = QtWidgets.QLabel()
        self.imported.setTextFormat(QtCore.Qt.PlainText)
        self.imported.setWordWrap(True)
        self.imported.hide()
        hide = QtWidgets.QPushButton("Hide preview")
        hide.clicked.connect(self.hide)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.select_button)
        buttons.addStretch(1)
        buttons.addWidget(hide)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.imported)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)

    def set_version(self, version):
        values = catalog_metadata(version)
        self.heading.setText(version["name"])
        self.description.setText(
            version.get("description")
            or "CLIC has no published description for this version."
        )
        for key, label in self.fields.items():
            text = values.get(key) or ""
            label.setText(text)
            self.form.setRowVisible(label, bool(text))

    def set_imported(self, databases):
        self.imported.setText(
            f"Already imported in {', '.join(databases)}" if databases else ""
        )
        self.imported.setVisible(bool(databases))
