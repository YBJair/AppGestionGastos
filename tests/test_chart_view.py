import os
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from matplotlib.backend_bases import MouseEvent

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from app_gestion_gastos.chart_view import ExpenseChartView
from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.ui import MainWindow


def test_chart_view_supports_year_month_and_date_range(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "chart.sqlite3")
    database.initialize()
    expenses = (
        Expense(
            "Supermercado", "Compra", Decimal("10.00"), date(2026, 1, 1), subcategory="General"
        ),
        Expense(
            "Hogar", "Luz", Decimal("20.00"), date(2026, 1, 15), subcategory="Electricidad"
        ),
        Expense(
            "Supermercado", "Compra", Decimal("5.00"), date(2026, 2, 2), subcategory="General"
        ),
    )
    for expense in expenses:
        database.add(expense)

    view = ExpenseChartView(ExpenseService(database))
    assert [tick.get_text() for tick in view.axes.get_xticklabels()] == ["ene 2026", "feb 2026"]

    view.year_input.setValue(2025)
    assert view.axes.containers == []
    view.year_input.setValue(2026)
    assert [tick.get_text() for tick in view.axes.get_xticklabels()] == ["ene 2026", "feb 2026"]
    assert len(view.axes.containers) == 1

    view.categories_check.setChecked(True)
    assert not view.totals_check.isChecked()
    assert len(view.axes.containers) == 2

    view.scope_tabs.setCurrentIndex(1)
    view.month_input.setCurrentIndex(0)
    assert view._selected_period()[2] == "week"

    view.scope_tabs.setCurrentIndex(2)
    view.start_date_input.setDate(QDate(2026, 1, 1))
    view.end_date_input.setDate(QDate(2026, 2, 1))
    assert view.week_precision.isChecked()
    assert view._selected_period()[2] == "week"
    view.end_date_input.setDate(QDate(2026, 2, 2))
    assert view.month_precision.isChecked()
    assert view._selected_period()[2] == "month"
    view.week_precision.click()
    assert view._selected_period()[2] == "week"
    view.start_date_input.setDate(QDate(2026, 1, 2))
    assert view.week_precision.isChecked()
    application.processEvents()


def test_hover_highlights_bar_and_shows_amount(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "hover.sqlite3")
    database.initialize()
    database.add(
        Expense("Hogar", "Factura", Decimal("42.75"), date(2026, 3, 10), subcategory="Luz")
    )
    view = ExpenseChartView(ExpenseService(database))
    view.canvas.draw()
    bar = view.axes.containers[0].patches[0]
    original_linewidth = bar.get_linewidth()
    x_pixel, y_pixel = view.axes.transData.transform(
        (bar.get_x() + bar.get_width() / 2, bar.get_height() / 2)
    )
    hover_event = MouseEvent("motion_notify_event", view.canvas, x_pixel, y_pixel)

    view.canvas.callbacks.process("motion_notify_event", hover_event)

    assert view._hover_bar is bar
    assert view._hover_annotation.get_text() == "42,75 €"
    assert view._hover_annotation.get_visible()
    assert bar.get_linewidth() > original_linewidth

    second_hover_event = MouseEvent(
        "motion_notify_event",
        view.canvas,
        x_pixel,
        view.axes.transData.transform(
            (bar.get_x() + bar.get_width() / 2, bar.get_height() * 0.8)
        )[1],
    )
    view.canvas.callbacks.process("motion_notify_event", second_hover_event)
    assert view._hover_annotation.xy == (second_hover_event.xdata, second_hover_event.ydata)

    leave_event = MouseEvent("motion_notify_event", view.canvas, 0, 0)
    view.canvas.callbacks.process("motion_notify_event", leave_event)

    assert view._hover_bar is None
    assert not view._hover_annotation.get_visible()
    application.processEvents()


def test_short_bar_has_hover_area_above_its_top(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "short-bar.sqlite3")
    database.initialize()
    database.add(
        Expense("Hogar", "Factura grande", Decimal("1000.00"), date(2026, 1, 10), subcategory="Luz")
    )
    database.add(
        Expense("Hogar", "Gasto pequeño", Decimal("1.00"), date(2026, 2, 10), subcategory="Luz")
    )
    view = ExpenseChartView(ExpenseService(database))
    view.canvas.draw()
    short_bar = view.axes.containers[0].patches[1]
    bar_bounds = short_bar.get_window_extent(view.canvas.get_renderer())
    hover_event = MouseEvent(
        "motion_notify_event",
        view.canvas,
        bar_bounds.x0 + bar_bounds.width / 2,
        bar_bounds.y1 + 8,
    )

    assert hover_event.inaxes is view.axes
    view.canvas.callbacks.process("motion_notify_event", hover_event)

    assert view._hover_bar is short_bar
    assert view._hover_annotation.get_text() == "1,00 €"
    application.processEvents()


def test_switching_back_to_main_chart_tab_refreshes_it(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "main-tabs.sqlite3")
    database.initialize()
    window = MainWindow(ExpenseService(database))
    refresh = Mock(wraps=window.chart_view.refresh)
    window.chart_view.refresh = refresh

    window.tabs.setCurrentIndex(1)
    window.tabs.setCurrentIndex(0)

    refresh.assert_called_once()
    application.processEvents()