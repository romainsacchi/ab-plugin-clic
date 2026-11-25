"""Sortable and filterable columns for the CLIC catalog results."""

from qtpy import QtCore, QtWidgets

COLUMNS = (
    ("", "Select", 65),
    ("name", "Inventory", 320),
    ("location", "Location", 100),
    ("semantic_version", "Version", 85),
    ("id", "CLIC ID", 85),
)


class CatalogCell(QtWidgets.QTableWidgetItem):
    def __init__(self, field, value):
        text = str(value)
        super().__init__(text)
        if field == "id":
            self.sort_key = int(value)
        elif field == "semantic_version":
            parts = text.split(".")
            self.sort_key = (
                (0, tuple(map(int, parts)))
                if all(part.isdecimal() for part in parts)
                else (1, text.casefold())
            )
        else:
            self.sort_key = text.casefold()

    def __lt__(self, other):
        return self.sort_key < other.sort_key


class CatalogTable(QtWidgets.QTableWidget):
    column_filters_requested = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.column_filters = {}
        self.sort_column = None
        self.sort_order = QtCore.Qt.AscendingOrder
        self.setHorizontalHeaderLabels([title for _, title, _ in COLUMNS])
        header = self.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header.sectionClicked.connect(self._on_header_click)
        header.customContextMenuRequested.connect(self._show_filter_menu)
        for index, (_, _, width) in enumerate(COLUMNS):
            self.setColumnWidth(index, width)
        self.set_column_filters({})

    def _on_header_click(self, column):
        if column == 0:
            return
        descending = (
            self.sort_column == column and self.sort_order == QtCore.Qt.AscendingOrder
        )
        self.sort_column = column
        self.sort_order = (
            QtCore.Qt.DescendingOrder if descending else QtCore.Qt.AscendingOrder
        )
        current = self.currentItem()
        self.apply_sort()
        if current is not None:
            self.setCurrentItem(current)
            self.scrollToItem(current)
        header = self.horizontalHeader()
        header.setSortIndicator(column, self.sort_order)
        header.setSortIndicatorShown(True)

    def apply_sort(self):
        if self.sort_column is not None:
            self.sortItems(self.sort_column, self.sort_order)

    def set_column_filters(self, filters):
        self.column_filters = filters
        for column, (field, title, _) in enumerate(COLUMNS[1:], start=1):
            item = self.horizontalHeaderItem(column)
            hint = "Click to sort this page. Right-click to filter."
            if field in filters:
                term, exclude = filters[field]
                item.setText(f"{title} •")
                hint += f" Filter {'hides' if exclude else 'shows'} ‘{term}’."
            else:
                item.setText(title)
            item.setToolTip(hint)

    def _show_filter_menu(self, position):
        header = self.horizontalHeader()
        column = header.logicalIndexAt(position)
        if column < 1:
            return
        field, title, _ = COLUMNS[column]
        menu = QtWidgets.QMenu(header)
        include = menu.addAction(
            "Show names containing…" if field == "name" else "Show matching value…"
        )
        exclude = menu.addAction(
            "Hide names containing…" if field == "name" else "Hide matching value…"
        )
        menu.addSeparator()
        clear = menu.addAction(f"Clear {title} filter")
        clear.setEnabled(field in self.column_filters)
        clear_all = menu.addAction("Clear all column filters")
        clear_all.setEnabled(bool(self.column_filters))
        action = menu.exec(header.viewport().mapToGlobal(position))
        filters = self.column_filters.copy()
        if action in (include, exclude):
            current, _ = filters.get(field, ("", False))
            term, accepted = QtWidgets.QInputDialog.getText(
                self,
                f"Filter {title}",
                "Text to match" if field == "name" else "Exact value",
                text=current,
            )
            if not accepted:
                return
            if term := term.strip():
                filters[field] = (term, action == exclude)
            else:
                filters.pop(field, None)
        elif action == clear:
            filters.pop(field)
        elif action == clear_all:
            filters.clear()
        else:
            return
        if filters != self.column_filters:
            self.column_filters_requested.emit(filters)
