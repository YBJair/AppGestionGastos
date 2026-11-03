import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_gestion_gastos.csv_importer import parse_expense_csv
from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.import_views import ImportJobsView, PendingImportItemsView
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.ui import MainWindow


def _insert_job(database: SQLiteDatabase, filename: str, source_type: str, imported_at: str) -> int:
    with database.connect() as connection:
        return connection.execute(
            """
            INSERT INTO import_jobs (filename, source_type, imported_at, status)
            VALUES (?, ?, ?, 'processed')
            """,
            (filename, source_type, imported_at),
        ).lastrowid


def _insert_item(
    database: SQLiteDatabase,
    job_id: int,
    raw_description: str,
    classification: str,
    status: str,
    category_id: int | None = None,
    subcategory_id: int | None = None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO import_items (
                import_job_id, raw_description, user_description, normalized_description,
                amount, expense_date, category_id, subcategory_id, classification, status
            ) VALUES (?, ?, 'Compra familiar', 'compra familiar', 2599, '2026-10-20', ?, ?, ?, ?)
            """,
            (
                job_id,
                raw_description,
                category_id,
                subcategory_id,
                classification,
                status,
            ),
        )


def test_import_queries_sort_jobs_and_filter_pending_items(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "import-views.sqlite3")
    database.initialize()
    older_job = _insert_job(database, "enero.csv", "csv", "2026-01-15T10:00:00Z")
    newer_job = _insert_job(database, "extracto.pdf", "pdf", "2026-02-20T12:00:00Z")

    _insert_item(database, newer_job, "Cargo parecido", "similar", "pending")
    _insert_item(database, newer_job, "Similar aceptado", "similar", "accepted")
    _insert_item(database, older_job, "Cargo nuevo", "unknown", "pending")

    jobs = database.list_import_jobs()
    similar_items = database.list_pending_import_items("similar")
    unknown_items = database.list_pending_import_items("unknown")

    assert [job.filename for job in jobs] == ["extracto.pdf", "enero.csv"]
    assert [item.raw_description for item in similar_items] == ["Cargo parecido"]
    assert [item.raw_description for item in unknown_items] == ["Cargo nuevo"]


def test_import_views_show_requested_columns_and_enabled_import_buttons(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "import-view-columns.sqlite3")
    database.initialize()
    _insert_job(database, "extracto.csv", "csv", "2026-10-31T12:30:00Z")

    jobs_view = ImportJobsView(ExpenseService(database))
    assert [jobs_view.table.horizontalHeaderItem(i).text() for i in range(4)] == [
        "Fichero",
        "Tipo",
        "Fecha",
        "Estado",
    ]
    assert jobs_view.import_csv_button.isEnabled()
    assert jobs_view.import_pdf_button.isEnabled()

    similar_view = PendingImportItemsView(ExpenseService(database), "similar")
    new_view = PendingImportItemsView(ExpenseService(database), "unknown")
    expected_headers = ["Descripción", "Alias", "Cantidad", "Categoría", "Subcategoría", "Fecha", "Genérico", "OK"]
    assert [similar_view.table.horizontalHeaderItem(i).text() for i in range(8)] == expected_headers
    assert [new_view.table.horizontalHeaderItem(i).text() for i in range(8)] == expected_headers
    assert similar_view.table.horizontalHeaderItem(similar_view.table.columnCount() - 1).text() == "OK"
    assert new_view.table.horizontalHeaderItem(new_view.table.columnCount() - 1).text() == "OK"

    window = MainWindow(ExpenseService(database))
    assert window.table.horizontalHeaderItem(window.table.columnCount() - 1).text() == "Seleccionar"
    tab_names = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert tab_names[-3:] == ["Importaciones", "Similares", "Nuevas"]
    application.processEvents()


def test_csv_button_imports_all_rows_and_creates_categories_and_expenses(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "csv-button.sqlite3")
    database.initialize()
    csv_path = tmp_path / "inicial.csv"
    csv_path.write_bytes(
        (
            "fecha;categoría;subcategoría;importe;nota\r\n"
            "03/02/2026;Hogar;Cocina;1.234,56 €;Compra de café\r\n"
            "04/02/2026;Hogar;Cocina;160,17 €;Compra de despensa\r\n"
            "\r\n"
        ).encode("cp1252")
    )
    service = ExpenseService(database)
    view = ImportJobsView(service)

    with (
        patch(
            "app_gestion_gastos.import_views.QFileDialog.getOpenFileName",
            return_value=(str(csv_path), "Archivos CSV (*.csv)"),
        ),
        patch("app_gestion_gastos.import_views.QMessageBox.information") as information,
    ):
        view.import_csv_button.click()

    jobs = database.list_import_jobs()
    expenses = database.list_all()
    with database.connect() as connection:
        items = connection.execute(
            "SELECT * FROM import_items ORDER BY id"
        ).fetchall()
        expense_links = connection.execute(
            "SELECT import_job_id, import_item_id, source, import_description "
            "FROM expenses ORDER BY id"
        ).fetchall()

    assert len(jobs) == 1
    assert jobs[0].filename == "inicial.csv"
    assert jobs[0].source_type == "CSV"
    assert jobs[0].status == "completed"
    assert len(items) == 2
    assert len(expenses) == 2
    assert [expense.description for expense in expenses] == [
        "Compra de despensa",
        "Compra de café",
    ]
    assert [item["classification"] for item in items] == ["identical", "identical"]
    assert [item["status"] for item in items] == ["accepted", "accepted"]
    assert items[0]["raw_description"] == "Compra de café"
    assert items[0]["user_description"] == "Compra de café"
    assert items[0]["normalized_description"] == "compra de cafe"
    assert all(link["source"] == "import" for link in expense_links)
    assert all(
        link["import_job_id"] == items[0]["import_job_id"] and link["import_item_id"]
        for link in expense_links
    )
    assert database.list_categories() == ["Hogar"]
    assert database.list_subcategories("Hogar") == ["Cocina"]
    information.assert_called_once()
    application.processEvents()


def test_csv_parser_error_does_not_create_import_job(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "csv-atomic.sqlite3")
    database.initialize()
    csv_path = tmp_path / "invalid.csv"
    csv_path.write_bytes(
        (
            "fecha;categoría;subcategoría;importe;nota\r\n"
            "03/02/2026;Hogar;Cocina;15,00 €;Fila válida\r\n"
            "fecha mala;Hogar;Cocina;16,00 €;Fila inválida\r\n"
        ).encode("cp1252")
    )

    with pytest.raises(ValueError, match="Fila 3"):
        parse_expense_csv(csv_path)
    assert database.list_import_jobs() == []
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM import_items").fetchone()[0] == 0