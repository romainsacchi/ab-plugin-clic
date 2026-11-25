"""Show preparation steps while the CLIC import worker runs."""

from qtpy import QtCore, QtWidgets

from .progress import PreparationStep


class _PreparationWorker(QtCore.QThread):
    progressed = QtCore.Signal(int, str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation(self.progressed.emit)
        except Exception as exc:
            self.error = exc


class _PreparationDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Prepare CLIC import")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
        self.setMinimumWidth(420)

        self.step_label = QtWidgets.QLabel()
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        self.bar = QtWidgets.QProgressBar()
        self.total_steps = len(PreparationStep)
        self.bar.setRange(0, self.total_steps)
        self.bar.setTextVisible(False)
        self.update_step(
            PreparationStep.REQUEST_EXPORT, "Requesting a Brightway export from CLIC…"
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.step_label)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)

    @QtCore.Slot(int, str)
    def update_step(self, step, message):
        self.step_label.setText(f"Step {step} of {self.total_steps}")
        self.status.setText(message)
        self.bar.setValue(step)

    def reject(self):
        # Keep the dialog open until the worker and its Brightway cleanup finish.
        pass


def run_preparation(parent, operation):
    dialog = _PreparationDialog(parent)
    worker = _PreparationWorker(operation, dialog)
    worker.progressed.connect(dialog.update_step)
    worker.finished.connect(dialog.accept)
    QtCore.QTimer.singleShot(0, worker.start)
    dialog.exec()
    worker.wait()
    dialog.deleteLater()
    if worker.error is not None:
        raise worker.error
    return worker.result
