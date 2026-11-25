"""Show preparation steps while the CLIC import worker runs."""

from threading import Event

from qtpy import QtCore, QtWidgets

from .client import ExportDeferred
from .progress import PreparationStep


class _PreparationWorker(QtCore.QThread):
    progressed = QtCore.Signal(int, str)

    def __init__(self, operation, stop, parent):
        super().__init__(parent)
        self.operation = operation
        self.stop = stop
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation(self.progressed.emit, self.stop)
        except Exception as exc:
            self.error = exc


class _PreparationDialog(QtWidgets.QDialog):
    def __init__(self, parent, stop):
        super().__init__(parent)
        self.setWindowTitle("Prepare CLIC import")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
        self.setMinimumWidth(420)
        self.stop = stop

        self.step_label = QtWidgets.QLabel()
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        self.bar = QtWidgets.QProgressBar()
        self.total_steps = len(PreparationStep)
        self.bar.setRange(0, self.total_steps)
        self.bar.setTextVisible(False)
        self.defer = QtWidgets.QPushButton("Continue later")
        self.defer.clicked.connect(self._defer)
        self.update_step(
            PreparationStep.REQUEST_EXPORT, "Requesting a Brightway export from CLIC…"
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.step_label)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addWidget(self.defer, 0, QtCore.Qt.AlignRight)

    @QtCore.Slot(int, str)
    def update_step(self, step, message):
        if self.stop.is_set():
            return
        self.step_label.setText(f"Step {step} of {self.total_steps}")
        self.status.setText(message)
        self.bar.setValue(step)
        self.defer.setVisible(step == PreparationStep.WAIT_FOR_EXPORT)

    def _defer(self):
        self.stop.set()
        self.defer.setEnabled(False)
        self.status.setText("Leaving the saved export running on CLIC…")

    def reject(self):
        if self.defer.isVisible() and self.defer.isEnabled():
            self._defer()


def run_preparation(parent, operation):
    stop = Event()
    dialog = _PreparationDialog(parent, stop)
    worker = _PreparationWorker(operation, stop, dialog)
    worker.progressed.connect(dialog.update_step)
    worker.finished.connect(dialog.accept)
    QtCore.QTimer.singleShot(0, worker.start)
    dialog.exec()
    worker.wait()
    dialog.deleteLater()
    if stop.is_set():
        raise ExportDeferred
    if worker.error is not None:
        raise worker.error
    return worker.result
