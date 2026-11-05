import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_gestion_gastos.csv_importer import CsvImportError
from app_gestion_gastos.pdf_importer import PdfImportError
from app_gestion_gastos.services import ExpenseService


class ImportJobsView(QWidget):
    import_completed = Signal()

    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        self.import_csv_button = QPushButton("Importar CSV")
        self.import_pdf_button = QPushButton("Importar PDF")
        self.import_csv_button.clicked.connect(self._select_csv_file)
        self.import_pdf_button.clicked.connect(self._select_pdf_file)

        buttons = QHBoxLayout()
        buttons.addWidget(self.import_csv_button)
        buttons.addWidget(self.import_pdf_button)
        buttons.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Fichero", "Tipo", "Fecha", "Estado"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        jobs = self._service.list_import_jobs()
        self.table.setRowCount(len(jobs))
        for row_index, job in enumerate(jobs):
            values = (
                job.filename or "",
                job.source_type.upper(),
                job.imported_at.replace("T", " ").removesuffix("Z"),
                job.status,
            )
            for column_index, value in enumerate(values):
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))

    def _select_csv_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importar gastos desde CSV",
            "",
            "Archivos CSV (*.csv)",
        )
        if not filename:
            return
        try:
            _, imported_count = self._service.import_csv_file(filename)
        except (CsvImportError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo importar el CSV", str(error))
            return
        self.import_completed.emit()
        QMessageBox.information(
            self,
            "Importación completada",
            f"Se importaron {imported_count} gastos.",
        )

    def _select_pdf_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importar movimientos desde PDF",
            "",
            "Archivos PDF (*.pdf)",
        )
        if not filename:
            return
        try:
            _, imported_count = self._service.import_pdf_file(filename)
        except (PdfImportError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo importar el PDF", str(error))
            return
        self.import_completed.emit()
        QMessageBox.information(
            self,
            "Importación completada",
            f"Se procesaron {imported_count} salidas de dinero.",
        )


class AliasDelegate(QStyledItemDelegate):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        completer = QCompleter(self._service.list_expense_descriptions(), editor)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        editor.setCompleter(completer)
        return editor

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        editor.setText(value if value is not None else "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.ItemDataRole.DisplayRole)


class CategoryDelegate(QStyledItemDelegate):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.setEditable(True)
        editor.addItems(self._service.list_categories())
        return editor

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        editor.setCurrentText(value if value is not None else "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.DisplayRole)


class SubcategoryDelegate(QStyledItemDelegate):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def createEditor(self, parent, option, index):
        category_index = index.sibling(index.row(), 3)
        category = ""
        if category_index.isValid():
            value = index.model().data(category_index, Qt.ItemDataRole.DisplayRole)
            category = value if value is not None else ""
        editor = QComboBox(parent)
        editor.setEditable(True)
        editor.addItems(self._service.list_subcategories(category))
        return editor

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        editor.setCurrentText(value if value is not None else "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.DisplayRole)


class PendingImportItemsView(QWidget):
    import_completed = Signal()

    def __init__(
        self,
        service: ExpenseService,
        classification: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._classification = classification

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Descripción", "Alias", "Cantidad", "Categoría", "Subcategoría", "Fecha", "Genérico", "OK"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setItemDelegateForColumn(1, AliasDelegate(service))
        self.table.setItemDelegateForColumn(3, CategoryDelegate(service))
        self.table.setItemDelegateForColumn(4, SubcategoryDelegate(service))
        self._loading = False
        self.table.itemChanged.connect(self._item_changed)
        self.delete_button = QPushButton("Borrar")
        self.delete_button.clicked.connect(self._delete_selected)
        buttons = QHBoxLayout()
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        items = self._service.list_pending_import_items(self._classification)
        self.table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            values = (
                item.raw_description,
                item.user_description or "",
                f"{item.amount:.2f}",
                item.category or "",
                item.subcategory or "",
                item.expense_date.isoformat(),
            )
            for column_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable
                )
                self.table.setItem(row_index, column_index, cell)

            generic_item = QTableWidgetItem()
            generic_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            generic_item.setCheckState(
                Qt.CheckState.Checked if item.generic else Qt.CheckState.Unchecked
            )
            self.table.setItem(row_index, 6, generic_item)

            ok_item = QTableWidgetItem()
            ok_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            ok_item.setCheckState(Qt.CheckState.Unchecked)
            ok_item.setData(Qt.ItemDataRole.UserRole, item.id)
            self.table.setItem(row_index, 7, ok_item)
        self._loading = False

    def _item_changed(self, item):
        from PySide6.QtWidgets import QMessageBox
        if self._loading or item.column() != 7:
            return
        if item.checkState() != Qt.CheckState.Checked:
            return
        row = item.row()
        try:
            alias = self.table.item(row, 1).text().strip()
            if not alias:
                alias = self.table.item(row, 0).text().strip()
            category = self.table.item(row, 3).text().strip()
            subcategory = self.table.item(row, 4).text().strip()
            generic = self.table.item(row, 6).checkState() == Qt.CheckState.Checked
            import_item_id = self.table.item(row, 7).data(Qt.ItemDataRole.UserRole)
            self._service.accept_import_item_with_data(
                import_item_id, alias, category, subcategory, generic
            )
        except Exception as error:
            self.table.blockSignals(True)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.table.blockSignals(False)
            QMessageBox.warning(self, 'No se pudo aceptar', str(error))
            return
        self.refresh()
        self.import_completed.emit()
    def _delete_selected(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected_rows and self.table.currentRow() >= 0:
            selected_rows = [self.table.currentRow()]
        if not selected_rows:
            return

        item_ids = [self.table.item(row, 7).data(Qt.ItemDataRole.UserRole) for row in selected_rows]
        item_ids = [item_id for item_id in item_ids if item_id is not None]
        if not item_ids:
            return

        answer = QMessageBox.question(
            self,
            "Confirmar borrado",
            f"¿Estás seguro de querer borrar {len(item_ids)} líneas?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._service.delete_import_items(item_ids)
        except Exception as error:
            QMessageBox.warning(self, "No se pudo borrar", str(error))
            return

        self.refresh()
        self.import_completed.emit()

