import os
from datetime import date
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.import_views import ImportJobsView
from app_gestion_gastos.models import Expense, ParsedPdfTransaction
from app_gestion_gastos.pdf_importer import parse_bank_statement_pdf
from app_gestion_gastos.services import ExpenseService


def _word(text: str, x: float, top: float) -> dict[str, object]:
    return {"text": text, "x0": x, "x1": x + len(text) * 4, "top": top}


class FakePage:
    width = 595
    height = 842

    def extract_words(self, **kwargs) -> list[dict[str, object]]:
        return [
            _word("FECHA", 74, 100),
            _word("DESCRIPCIÓN", 144, 100),
            _word("ENTRADA", 419, 100),
            _word("SALIDA", 451, 100),
            _word("BALANCE", 494, 100),
            _word("01", 78, 125),
            _word("oct", 82, 132),
            _word("2026", 91, 139),
            _word("TIENDA", 144, 125),
            _word("CENTRAL", 178, 125),
            _word("COMPRA", 144, 137),
            _word("12,34", 451, 142),
            _word("02", 78, 170),
            _word("oct", 82, 177),
            _word("2026", 91, 184),
            _word("TRANSFERENCIA", 144, 170),
            _word("RECIBIDA", 215, 182),
            _word("200,00", 419, 188),
            _word("TRADE", 74, 800),
        ]


class FakePdf:
    pages = [FakePage()]

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


def test_pdf_parser_extracts_outgoing_and_skips_incoming(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app_gestion_gastos.pdf_importer.pdfplumber.open", lambda path: FakePdf())

    transactions = parse_bank_statement_pdf(tmp_path / "statement.pdf")

    assert transactions == [
        ParsedPdfTransaction(
            expense_date=date(2026, 10, 1),
            description="TIENDA CENTRAL COMPRA",
            amount_cents=1234,
        )
    ]


def test_pdf_job_stays_pending_until_all_lines_are_accepted(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "pdf-status.sqlite3")
    database.initialize()
    exact_reference = database.add(
        Expense(
            "Hogar",
            "Factura eléctrica",
            Decimal("40.00"),
            date(2026, 9, 1),
            subcategory="Electricidad",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE expenses SET import_description = ? WHERE id = ?",
            ("cargo electricidad", exact_reference.id),
        )

    job_id, count = database.import_pdf_expenses(
        "statement.pdf",
        [
            ParsedPdfTransaction(date(2026, 10, 1), "cargo electricidad", 1250),
            ParsedPdfTransaction(date(2026, 10, 2), "cargo electricida", 500),
            ParsedPdfTransaction(date(2026, 10, 3), "cargo desconocido", 300),
        ],
    )

    jobs = database.list_import_jobs()
    assert count == 3
    assert jobs[0].status == "pending"
    with database.connect() as connection:
        items = connection.execute(
            "SELECT id, classification, status, category_id, subcategory_id "
            "FROM import_items WHERE import_job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
        category_id = connection.execute(
            "SELECT id FROM categories WHERE name = 'Hogar'"
        ).fetchone()["id"]
        subcategory_id = connection.execute(
            "SELECT id FROM subcategories WHERE name = 'Electricidad'"
        ).fetchone()["id"]

    assert [(item["classification"], item["status"]) for item in items] == [
        ("identical", "accepted"),
        ("similar", "pending"),
        ("unknown", "pending"),
    ]
    assert items[2]["category_id"] is None
    assert items[2]["subcategory_id"] is None

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE import_items
            SET user_description = 'Cargo nuevo', category_id = ?, subcategory_id = ?
            WHERE id = ?
            """,
            (category_id, subcategory_id, items[2]["id"]),
        )
    database.accept_import_item(items[1]["id"])
    assert database.list_import_jobs()[0].status == "pending"
    database.accept_import_item(items[2]["id"])

    assert database.list_import_jobs()[0].status == "completed"
    assert len(database.list_all()) == 4


def test_pdf_button_opens_file_picker_and_imports(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    database = SQLiteDatabase(tmp_path / "pdf-button.sqlite3")
    database.initialize()
    service = ExpenseService(database)
    view = ImportJobsView(service)

    with (
        patch(
            "app_gestion_gastos.import_views.QFileDialog.getOpenFileName",
            return_value=("statement.pdf", "Archivos PDF (*.pdf)"),
        ),
        patch.object(service, "import_pdf_file", return_value=(1, 12)) as import_pdf,
        patch("app_gestion_gastos.import_views.QMessageBox.information"),
    ):
        view.import_pdf_button.click()

    import_pdf.assert_called_once_with("statement.pdf")
    application.processEvents()