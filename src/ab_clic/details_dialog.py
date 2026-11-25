"""Preview the description and metadata from a CLIC catalog result."""

from qtpy import QtCore, QtWidgets


class CandidateDetails(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("CLIC inventory details")
        self.resize(580, 460)

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
        for key, title in (
            ("semantic_version", "Version"),
            ("reference_product", "Reference product"),
            ("location", "Location"),
            ("unit", "Unit"),
            ("classification_label", "Classification"),
            ("selected_license_label", "License"),
            ("published_at", "Published"),
            ("background", "Source background"),
            ("original_citation", "Citation"),
        ):
            value = QtWidgets.QLabel()
            value.setTextFormat(QtCore.Qt.PlainText)
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.form.addRow(title, value)
            self.fields[key] = value

        self.description = QtWidgets.QPlainTextEdit()
        self.description.setReadOnly(True)
        self.description.setPlaceholderText(
            "CLIC has no published description for this version."
        )
        description_label = QtWidgets.QLabel("Description")
        description_label.setBuddy(self.description)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addLayout(self.form)
        layout.addWidget(description_label)
        layout.addWidget(self.description, 1)
        layout.addWidget(buttons)

    def set_version(self, version):
        background = (version.get("background_context") or {}).get("technosphere") or {}
        values = {
            **version,
            "published_at": (version.get("published_at") or "")[:10],
            "background": " ".join(
                background[field]
                for field in ("family", "version", "system_model")
                if background.get(field)
            ),
        }
        self.heading.setText(version["name"])
        self.description.setPlainText(version.get("description") or "")
        for key, label in self.fields.items():
            text = values.get(key) or ""
            label.setText(text)
            self.form.setRowVisible(label, bool(text))
