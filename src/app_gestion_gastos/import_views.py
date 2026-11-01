from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_gestion_gastos.services import ExpenseService


class ImportJobsView(QWidget):
    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        self.import_csv_button = QPushButton("Importar CSV")
        self.import_pdf_button = QPushButton("Importar PDF")
        for button in (self.import_csv_button, self.import_pdf_button):
            button.setEnabled(False)
            button.setToolTip("Disponible en una próxima etapa")

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
