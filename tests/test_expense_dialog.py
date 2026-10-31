import os
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.text_utils import normalize_text
from app_gestion_gastos.ui import DescriptionLineEdit, ExpenseEntryView


def test_manual_expense_tab_filters_and_saves_subcategory(tmp_path) -> None:
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
    view = ExpenseEntryView(ExpenseService(database))

    assert isinstance(view.category_input, QComboBox)
    assert view.category_input.isEditable()
    assert view.category_input.count() == 2
    assert not view.subcategory_input.isEnabled()

    view.category_input.setEditText("Hogar")
    subcategories = [
        view.subcategory_input.itemText(index)
        for index in range(view.subcategory_input.count())
    ]
    assert subcategories == ["Electricidad"]
    view.category_input.setEditText("")
    assert view.subcategory_input.count() == 0
    assert not view.subcategory_input.isEnabled()

    view.category_input.setEditText("Hogar")
    view.description_input.setText("Compra de bombilla")
    view.amount_input.setValue(12.5)
    view.date_input.setDate(QDate(2026, 10, 30))
    view._set_today()
    assert view.date_input.date() == QDate.currentDate()
    view.date_input.setDate(QDate(2026, 10, 30))
    view.subcategory_input.setEditText("Electricidad")
    view._save()

    saved = database.list_all()[0]
    assert saved.description == "Compra de bombilla"
    assert saved.amount == Decimal("12.50")
    assert saved.subcategory == "Electricidad"
    assert view.status_label.text() == "Gasto guardado"
    assert view.description_input.text() == ""
    assert view.description_input.completer().model().rowCount() == 3
    application.processEvents()


@pytest.mark.parametrize("key", [Qt.Key.Key_Tab, Qt.Key.Key_Return])
def test_description_completion_accepts_with_tab_or_enter(tmp_path, key) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "completion.sqlite3")
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
    view = ExpenseEntryView(ExpenseService(database))
    focus_amount = Mock()
    view.amount_input.setFocus = focus_amount
    view.show()
    view.activateWindow()
    view.description_input.setFocus()
    QTest.keyClicks(view.description_input, "Fac")
    application.processEvents()

    assert view.description_input.completer().popup().isVisible()
    QTest.keyClick(view.description_input, key)
    QTest.qWait(20)

    assert view.description_input.text() == "Factura de luz"
    focus_amount.assert_called()


def test_description_completion_can_be_ignored_by_continuing_to_type(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "ignore-completion.sqlite3")
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
    view = ExpenseEntryView(ExpenseService(database))
    view.show()
    view.activateWindow()
    view.description_input.setFocus()
    QTest.keyClicks(view.description_input, "Facturas")
    application.processEvents()

    assert view.description_input.text() == "Facturas"
    assert view.description_input.hasFocus()


def test_exact_normalized_description_autofills_latest_category_and_subcategory(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "classification-match.sqlite3")
    database.initialize()
    previous_expenses = (
        Expense(
            "Hogar",
            "Factura eléctrica",
            Decimal("50.00"),
            date(2026, 10, 1),
            subcategory="Electricidad",
        ),
        Expense(
            "Servicios",
            "Factura electrica",
            Decimal("60.00"),
            date(2026, 10, 2),
            subcategory="Internet",
        ),
    )
    for expense in previous_expenses:
        database.add(expense)

    view = ExpenseEntryView(ExpenseService(database))
    view.show()
    view.activateWindow()
    view.description_input.setText("FACTURA   eléctrica")
    QTest.keyClick(view.description_input, Qt.Key.Key_Tab)
    QTest.qWait(20)

    assert view.description_input.text() == "FACTURA   eléctrica"
    assert view.category_input.currentText() == "Servicios"
    assert view.subcategory_input.currentText() == "Internet"
    application.processEvents()


def test_fuzzy_match_can_accept_a_missing_space_at_ninety(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "classification-separators.sqlite3")
    database.initialize()
    database.add(
        Expense(
            "Hogar",
            "Agua mineral",
            Decimal("2.00"),
            date(2026, 10, 1),
            subcategory="Bebidas",
        )
    )
    view = ExpenseEntryView(ExpenseService(database))
    assert normalize_text("Agua mineral") != normalize_text("Aguamineral")
    view.description_input.setText("aguamineral")
    QTest.keyClick(view.description_input, Qt.Key.Key_Tab)
    QTest.qWait(20)

    assert view.category_input.currentText() == "Hogar"
    assert view.subcategory_input.currentText() == "Bebidas"
    application.processEvents()


def test_fuzzy_description_match_at_ninety_autofills_classification(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "fuzzy-classification.sqlite3")
    database.initialize()
    database.add(
        Expense(
            "Hogar",
            "abcdefghij",
            Decimal("2.00"),
            date(2026, 10, 1),
            subcategory="General",
        )
    )
    view = ExpenseEntryView(ExpenseService(database))
    view.description_input.committed.emit("abcdefghiX")

    assert view.category_input.currentText() == "Hogar"
    assert view.subcategory_input.currentText() == "General"
    application.processEvents()


def test_fuzzy_description_match_below_ninety_does_not_autofill(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "fuzzy-below-threshold.sqlite3")
    database.initialize()
    database.add(
        Expense(
            "Hogar",
            "abcdefghij",
            Decimal("2.00"),
            date(2026, 10, 1),
            subcategory="General",
        )
    )
    view = ExpenseEntryView(ExpenseService(database))
    view.description_input.committed.emit("abcdeXXXXX")

    assert view.category_input.currentText() == ""
    assert view.subcategory_input.currentText() == ""
    application.processEvents()


def test_description_completer_scales_to_ten_thousand_sorted_values() -> None:
    QApplication.instance() or QApplication([])
    descriptions = [f"Compra del hogar {index:05d}" for index in range(10_000)]
    description_input = DescriptionLineEdit(descriptions)
    completer = description_input.completer()
    completer.setCompletionPrefix("compra del hogar 099")

    assert (
        completer.modelSorting()
        == completer.ModelSorting.CaseInsensitivelySortedModel
    )
    assert completer.completionCount() == 100


def test_enter_moves_through_fields_and_saves_back_to_description(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "focus-order.sqlite3")
    database.initialize()
    view = ExpenseEntryView(ExpenseService(database))
    view.show()
    view.activateWindow()
    view.description_input.setText("Compra del hogar")
    view.amount_input.setValue(25.50)
    view.category_input.setEditText("Hogar")
    view.subcategory_input.setEditText("General")
    view.description_input.setFocus()

    QTest.keyClick(view.description_input, Qt.Key.Key_Return)
    QTest.qWait(10)
    assert view.amount_input.hasFocus()
    QTest.keyClick(view.amount_input, Qt.Key.Key_Return)
    QTest.qWait(10)
    assert view.date_input.hasFocus()
    QTest.keyClick(view.date_input, Qt.Key.Key_Return)
    QTest.qWait(10)
    assert view.category_input.lineEdit().hasFocus()
    QTest.keyClick(view.category_input.lineEdit(), Qt.Key.Key_Return)
    QTest.qWait(10)
    assert view.subcategory_input.lineEdit().hasFocus()
    QTest.keyClick(view.subcategory_input.lineEdit(), Qt.Key.Key_Return)
    QTest.qWait(10)
    assert view.save_button.hasFocus()
    QTest.keyClick(view.save_button, Qt.Key.Key_Return)
    QTest.qWait(10)

    assert database.list_all()[0].description == "Compra del hogar"
    assert view.description_input.hasFocus()
    application.processEvents()


def test_amount_zero_placeholder_clears_on_focus_and_returns_on_blur(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "amount-focus.sqlite3")
    database.initialize()
    view = ExpenseEntryView(ExpenseService(database))
    view.show()
    view.activateWindow()

    assert view.amount_input.text() == view.amount_input._zero_placeholder
    view.amount_input.setFocus()
    QTest.qWait(10)
    assert view.amount_input.text().strip() == ""
    assert view.amount_input.value() == 0

    view.date_input.setFocus()
    QTest.qWait(10)
    assert view.amount_input.text() == view.amount_input._zero_placeholder
    application.processEvents()