import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QComboBox, QDialog

from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.ui import ExpenseDialog


def test_manual_expense_dialog_filters_and_saves_subcategory(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "dialog.sqlite3")
    database.initialize()
    database.add(
        Expense(
            category="Hogar",
            description="Factura de luz",
            amount=Decimal("50.00"),
            spent_on=date(2026, 10, 1),
            subcategory="Electricidad",
        )
    )
    database.add(
        Expense(
            category="Transporte",
            description="Abono",
            amount=Decimal("20.00"),
            spent_on=date(2026, 10, 2),
            subcategory="Publico",
        )
    )
    dialog = ExpenseDialog(ExpenseService(database))

    assert isinstance(dialog.category_input, QComboBox)
    assert dialog.category_input.isEditable()
    assert dialog.category_input.count() == 2
    assert not dialog.subcategory_input.isEnabled()

    dialog.category_input.setEditText("Hogar")
    subcategories = [
        dialog.subcategory_input.itemText(index)
        for index in range(dialog.subcategory_input.count())
    ]
    assert subcategories == ["Electricidad"]
    dialog.category_input.setEditText("")
    assert dialog.subcategory_input.count() == 0
    assert not dialog.subcategory_input.isEnabled()

    dialog.category_input.setEditText("Hogar")
    dialog.description_input.setText("Compra de bombilla")
    dialog.amount_input.setValue(12.5)
    dialog.date_input.setDate(QDate(2026, 10, 30))
    dialog._set_today()
    assert dialog.date_input.date() == QDate.currentDate()
    dialog.date_input.setDate(QDate(2026, 10, 30))
    dialog.subcategory_input.setEditText("Electricidad")
    dialog._save()

    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = database.list_all()[0]
    assert saved.description == "Compra de bombilla"
    assert saved.amount == Decimal("12.50")
    assert saved.subcategory == "Electricidad"
    application.processEvents()