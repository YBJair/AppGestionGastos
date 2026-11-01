import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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


def test_import_views_show_requested_columns_and_placeholder_buttons(tmp_path) -> None:
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
    assert not jobs_view.import_csv_button.isEnabled()
    assert not jobs_view.import_pdf_button.isEnabled()

    similar_view = PendingImportItemsView(ExpenseService(database), "similar")
    new_view = PendingImportItemsView(ExpenseService(database), "unknown")
    expected_headers = ["Descripción", "Alias", "Cantidad", "Categoría", "Subcategoría", "Fecha"]
    assert [similar_view.table.horizontalHeaderItem(i).text() for i in range(6)] == expected_headers
    assert [new_view.table.horizontalHeaderItem(i).text() for i in range(6)] == expected_headers

    window = MainWindow(ExpenseService(database))
    tab_names = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert tab_names[-3:] == ["Importaciones", "Similares", "Nuevas"]
    application.processEvents()