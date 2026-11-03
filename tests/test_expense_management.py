import os
from datetime import date
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.ui import MainWindow


def _create_window(tmp_path, expenses: list[Expense]) -> tuple[SQLiteDatabase, MainWindow]:
    database = SQLiteDatabase(tmp_path / "expenses.sqlite3")
    database.initialize()
    for expense in expenses:
        database.add(expense)
    window = MainWindow(ExpenseService(database))
    return database, window


def _row_for_id(window: MainWindow, expense_id: int) -> int:
    for row in range(window.table.rowCount()):
        if window.table.item(row, 5).data(Qt.ItemDataRole.UserRole) == expense_id:
            return row
    raise AssertionError(f"Gasto {expense_id} no encontrado en la tabla")


def _expense(description: str, day: int) -> Expense:
    return Expense(
        category="Hogar",
        description=description,
        amount=Decimal("12.50"),
        spent_on=date(2026, 10, day),
        subcategory="General",
    )


def test_edit_marks_row_and_only_persists_after_confirmation(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database, window = _create_window(tmp_path, [_expense("Compra", 1)])
    saved = database.list_all()[0]
    row = _row_for_id(window, saved.id)

    window.table.item(row, 0).setText("2026-10-12")
    window.table.item(row, 1).setText("Compra mensual")
    window.table.item(row, 2).setText("34,75 €")
    window.table.item(row, 3).setText("Alimentación")
    window.table.item(row, 4).setText("Supermercado")

    check_item = window.table.item(row, 5)
    assert check_item.checkState() == Qt.CheckState.Checked
    assert database.list_all()[0].description == "Compra"

    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.No
    ) as confirm:
        window._apply_selected_changes()
    confirm.assert_called_once()
    assert confirm.call_args.args[2] == "¿Estás seguro de querer aplicar los cambios de 1 líneas?"
    assert database.list_all()[0].description == "Compra"
    assert check_item.checkState() == Qt.CheckState.Checked

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window._apply_selected_changes()

    updated = database.list_all()[0]
    assert updated.spent_on == date(2026, 10, 12)
    assert updated.description == "Compra mensual"
    assert updated.amount == Decimal("34.75")
    assert updated.category == "Alimentación"
    assert updated.subcategory == "Supermercado"
    assert window.table.item(0, 5).checkState() == Qt.CheckState.Unchecked
    application.processEvents()


def test_delete_cancel_preserves_checks_and_confirm_deletes_only_checked(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database, window = _create_window(
        tmp_path, [_expense("Primero", 1), _expense("Segundo", 2)]
    )
    expenses = database.list_all()
    first_row = _row_for_id(window, expenses[0].id)
    _row_for_id(window, expenses[1].id)
    window.table.item(first_row, 5).setCheckState(Qt.CheckState.Checked)

    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.No
    ) as confirm:
        window._delete_selected_expenses()
    assert confirm.call_args.args[2] == "¿Estás seguro de querer borrar 1 líneas?"
    assert window.table.item(first_row, 5).checkState() == Qt.CheckState.Checked
    assert len(database.list_all()) == 2

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window._delete_selected_expenses()

    remaining = database.list_all()
    assert len(remaining) == 1
    assert remaining[0].id == expenses[1].id
    assert window.table.rowCount() == 1
    application.processEvents()
