import os
import unittest

from qtpy import QtCore, QtWidgets

from ab_clic.catalog_table import CatalogCell, CatalogTable


class CatalogTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_inventory_sort_keeps_the_current_candidate_and_checked_state(self):
        table = CatalogTable()
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setRowCount(3)
        for row, name in enumerate(("Zinc", "Aluminium", "Copper")):
            check = QtWidgets.QTableWidgetItem()
            check.setCheckState(QtCore.Qt.Checked if row == 0 else QtCore.Qt.Unchecked)
            table.setItem(row, 0, check)
            table.setItem(row, 1, CatalogCell("name", name))
        selected = table.item(0, 1)
        table.setCurrentItem(selected)

        for expected in (
            ("Aluminium", "Copper", "Zinc"),
            ("Zinc", "Copper", "Aluminium"),
        ):
            table.horizontalHeader().sectionClicked.emit(1)
            self.assertEqual(
                tuple(table.item(row, 1).text() for row in range(3)), expected
            )
            self.assertIs(table.currentItem(), selected)
            self.assertEqual(
                table.item(selected.row(), 0).checkState(), QtCore.Qt.Checked
            )
