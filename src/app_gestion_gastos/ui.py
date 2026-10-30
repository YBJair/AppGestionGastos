from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_gestion_gastos.services import ExpenseService


class ExpenseDialog(QDialog):
    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("Nuevo gasto manual")

        self.description_input = QLineEdit()
        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.category_input.lineEdit().setPlaceholderText("Escribe o selecciona una categoria")
        self.category_input.addItems(self._service.list_categories())
        self.category_input.setCurrentIndex(-1)
        self.category_input.lineEdit().clear()

        self.subcategory_input = QComboBox()
        self.subcategory_input.setEditable(True)
        self.subcategory_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.subcategory_input.lineEdit().setPlaceholderText(
            "Escribe o selecciona una subcategoria"
        )
        self.subcategory_input.setEnabled(False)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, 1_000_000_000)
        self.amount_input.setDecimals(2)
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        today_button = QPushButton("Hoy")
        today_button.clicked.connect(self._set_today)

        date_row = QHBoxLayout()
        date_row.addWidget(self.date_input, 1)
        date_row.addWidget(today_button)

        form = QFormLayout(self)
        form.addRow("Descripcion", self.description_input)
        form.addRow("Importe", self.amount_input)
        form.addRow("Fecha", date_row)
        form.addRow("Categoria", self.category_input)
        form.addRow("Subcategoria", self.subcategory_input)

        self.category_input.currentTextChanged.connect(self._category_changed)
        self._category_changed(self.category_input.currentText())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        try:
            self._service.register_expense(
                category=self.category_input.currentText(),
                description=self.description_input.text(),
                amount=Decimal(str(self.amount_input.value())),
                spent_on=date.fromisoformat(self.date_input.date().toString("yyyy-MM-dd")),
                subcategory=self.subcategory_input.currentText(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Datos no validos", str(error))
            return
        self.accept()

    def _set_today(self) -> None:
        self.date_input.setDate(QDate.currentDate())

    def _category_changed(self, category: str) -> None:
        self.subcategory_input.clear()
        subcategories = self._service.list_subcategories(category)
        self.subcategory_input.addItems(subcategories)
        self.subcategory_input.setCurrentIndex(-1)
        self.subcategory_input.lineEdit().clear()
        self.subcategory_input.setEnabled(bool(category.strip()))


class MainWindow(QMainWindow):
    def __init__(self, service: ExpenseService) -> None:
        super().__init__()
        self._service = service
        self.setWindowTitle("AppGestionGastos")
        self.resize(820, 480)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Descripcion", "Importe", "Categoria", "Subcategoria"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        add_button = QPushButton("Añadir gasto")
        add_button.clicked.connect(self._open_expense_dialog)

        toolbar = QHBoxLayout()
        toolbar.addStretch()
        toolbar.addWidget(add_button)
        layout = QVBoxLayout()
        layout.addLayout(toolbar)
        layout.addWidget(self.table)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.refresh()

    def refresh(self) -> None:
        expenses = self._service.list_expenses()
        self.table.setRowCount(len(expenses))
        for row_index, expense in enumerate(expenses):
            values = (
                expense.spent_on.isoformat(),
                expense.description,
                f"{expense.amount:.2f}",
                expense.category,
                expense.subcategory or "",
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 2:
                    alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    item.setTextAlignment(alignment)
                self.table.setItem(row_index, column_index, item)

    def _open_expense_dialog(self) -> None:
        dialog = ExpenseDialog(self._service, self)
        if dialog.exec() == ExpenseDialog.DialogCode.Accepted:
            self.refresh()