from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


class SortableTableWidget(QTableWidget):
    """QTableWidget que permite ordenar por cualquier columna haciendo clic en el encabezado.

    El orden por defecto es por la columna 0 (fecha) de más nuevo a más viejo.
    Las columnas pueden marcarse como no ordenables (por ejemplo, las de checkboxes).
    """

    def __init__(self, rows: int, columns: int, parent=None) -> None:
        super().__init__(rows, columns, parent)
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.DescendingOrder
        self._non_sortable_columns: set[int] = set()
        self.horizontalHeader().sectionClicked.connect(self._on_section_clicked)

    def set_non_sortable_columns(self, columns: set[int]) -> None:
        self._non_sortable_columns = set(columns)

    def _on_section_clicked(self, column: int) -> None:
        if column in self._non_sortable_columns:
            return
        if column == self._sort_column:
            self._sort_order = (
                Qt.SortOrder.AscendingOrder
                if self._sort_order == Qt.SortOrder.DescendingOrder
                else Qt.SortOrder.DescendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder
        self.sortItems(column, self._sort_order)

    def apply_saved_sort(self) -> None:
        if self.rowCount() == 0:
            return
        self.sortItems(self._sort_column, self._sort_order)

    def lessThan(self, item1: QTableWidgetItem, item2: QTableWidgetItem) -> bool:
        v1 = item1.data(Qt.ItemDataRole.UserRole)
        v2 = item2.data(Qt.ItemDataRole.UserRole)

        if v1 is not None and v2 is not None:
            if isinstance(v1, (Decimal, int, float, date, datetime)) and isinstance(
                v2, (Decimal, int, float, date, datetime)
            ):
                if self._sort_order == Qt.SortOrder.AscendingOrder:
                    return v1 < v2
                return v1 > v2

        text1 = item1.data(Qt.ItemDataRole.DisplayRole) or ""
        text2 = item2.data(Qt.ItemDataRole.DisplayRole) or ""
        if self._sort_order == Qt.SortOrder.AscendingOrder:
            return str(text1) < str(text2)
        return str(text1) > str(text2)
