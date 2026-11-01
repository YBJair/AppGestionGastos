import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_gestion_gastos.csv_importer import CsvImportError
from app_gestion_gastos.services import ExpenseService


class ImportJobsView(QWidget):
    import_completed = Signal()

    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        self.import_csv_button = QPushButton("Importar CSV")
        self.import_pdf_button = QPushButton("Importar PDF")
        self.import_csv_button.clicked.connect(self._select_csv_file)
        self.import_pdf_button.setEnabled(False)
        self.import_pdf_button.setToolTip("Disponible en una próxima etapa")

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


class PendingImportItemsView(QWidget):
    def __init__(
        self,
        service: ExpenseService,
        classification: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._classification = classification

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Descripción", "Alias", "Cantidad", "Categoría", "Subcategoría", "Fecha"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
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
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))
