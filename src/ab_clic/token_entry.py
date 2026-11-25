"""Masked token input and its connection to the system credential store."""

from keyring.errors import KeyringError
from qtpy import QtCore, QtWidgets

from .credentials import delete_token, load_token, save_token


class TokenEntry(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loaded = False
        self.saved_token = ""
        self.entry = QtWidgets.QLineEdit()
        self.entry.setEchoMode(QtWidgets.QLineEdit.Password)
        self.entry.setAccessibleName("CLIC API token")
        self.entry.editingFinished.connect(self.remember)

        link = QtWidgets.QLabel(
            '<a href="https://clic.psi.ch/accounts/profile/">Get your token</a>'
        )
        link.setTextFormat(QtCore.Qt.RichText)
        link.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        link.setOpenExternalLinks(True)
        self.forget_button = QtWidgets.QPushButton("Forget token")
        self.forget_button.setEnabled(False)
        self.forget_button.clicked.connect(self.forget)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.entry, 1)
        row.addWidget(link)
        row.addWidget(self.forget_button)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.status)
        self.setFocusProxy(self.entry)

    def showEvent(self, event):
        self.load()
        super().showEvent(event)

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        try:
            self.saved_token = load_token()
        except (KeyringError, OSError):
            self._status(
                "Could not open the system credential store. You can enter a token for this session."
            )
            return
        self.entry.setText(self.saved_token)
        self.forget_button.setEnabled(bool(self.saved_token))

    def text(self):
        return self.entry.text().strip()

    def remember(self):
        token = self.text()
        if not token or token == self.saved_token:
            return
        try:
            save_token(token)
        except (KeyringError, OSError):
            self._status(
                "The system credential store could not save the token. You can still use it in this session."
            )
            return
        self.saved_token = token
        self.forget_button.setEnabled(True)
        self._status("")

    def forget(self):
        try:
            delete_token()
        except (KeyringError, OSError):
            self._status("Could not remove the token from the system credential store.")
            return
        self.saved_token = ""
        self.entry.setText("")
        self.forget_button.setEnabled(False)
        self._status("")

    def _status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))
