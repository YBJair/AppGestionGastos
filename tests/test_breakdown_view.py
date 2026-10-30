import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from app_gestion_gastos.breakdown_view import ExpenseBreakdownDialog
from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService


def test_breakdown_view_groups_month_category_and_subcategory(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "breakdown.sqlite3")
    database.initialize()
    database.add(
        Expense(
            "Hogar", "Renta", Decimal("160.17"), date(2026, 2, 1), subcategory="Renta"
        )
    )
    database.add(
        Expense("Hogar", "Luz", Decimal("69.03"), date(2026, 2, 15), subcategory="Luz")
    )
    database.add(
        Expense(
            "Mascotas", "Comida", Decimal("37.45"), date(2026, 2, 28), subcategory="Comida"
        )
    )
    dialog = ExpenseBreakdownDialog(ExpenseService(database))

    dialog.year_input.setValue(2026)
    dialog._generate()

    assert dialog.results_tree.topLevelItemCount() == 1
    month_item = dialog.results_tree.topLevelItem(0)
    assert month_item.text(0) == "feb 2026"
    assert month_item.text(1) == "266,65 €"
    assert month_item.childCount() == 2
    assert dialog.total_label.text() == "Total: 266,65 €"

    dialog.period_tabs.setCurrentIndex(1)
    dialog.start_date_input.setDate(QDate(2026, 2, 1))
    dialog.end_date_input.setDate(QDate(2026, 2, 15))
    dialog._generate()

    assert dialog.total_label.text() == "Total: 229,20 €"
    application.processEvents()