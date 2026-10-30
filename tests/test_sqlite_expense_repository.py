import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService


def test_repository_persists_and_reads_expenses(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "test.sqlite3")
    database.initialize()
    service = ExpenseService(database)
    expense = Expense(
        category="Hogar",
        description="Luz",
        amount=Decimal("39.90"),
        spent_on=date(2026, 10, 1),
        subcategory="Electricidad",
    )

    saved = database.add(expense)

    assert saved.id is not None
    assert service.list_expenses() == [saved]
    assert database.list_categories() == ["Hogar"]
    assert database.list_subcategories("Hogar") == ["Electricidad"]
    assert database.list_subcategories("") == []

    with database.connect() as connection:
        row = connection.execute(
            "SELECT amount, source, subcategory_id, expense_date "
            "FROM expenses WHERE id = ?",
            (saved.id,),
        ).fetchone()
    assert row["amount"] == 3990
    assert row["source"] == "manual"
    assert row["subcategory_id"] is not None
    assert row["expense_date"] == "2026-10-01"


def test_initialize_creates_all_requested_tables(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "schema.sqlite3")
    database.initialize()
    expected_columns = {
        "categories": {"id", "name"},
        "subcategories": {"id", "category_id", "name"},
        "expenses": {
            "id",
            "description",
            "import_description",
            "expense_date",
            "amount",
            "category_id",
            "subcategory_id",
            "source",
            "created_at",
        },
        "import_jobs": {"id", "source_type", "filename", "imported_at", "status"},
        "import_items": {
            "id",
            "import_job_id",
            "raw_description",
            "normalized_description",
            "amount",
            "expense_date",
            "category_id",
            "subcategory_id",
            "classification",
            "status",
        },
    }

    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = {
            table: {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for table in expected_columns
        }
        foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert set(expected_columns).issubset(tables)
    assert columns == expected_columns
    assert foreign_keys_enabled == 1


def test_import_items_checks_classification_and_status(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "checks.sqlite3")
    database.initialize()
    with database.connect() as connection:
        job_id = connection.execute(
            "INSERT INTO import_jobs (source_type) VALUES ('csv')"
        ).lastrowid

    def insert_item(classification: str, status: str) -> None:
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO import_items (
                    import_job_id, raw_description, amount, expense_date,
                    classification, status
                ) VALUES (?, 'Compra', 1250, '2026-10-30', ?, ?)
                """,
                (job_id, classification, status),
            )

    for classification in ("identical", "similar", "unknown"):
        insert_item(classification, "pending")
    for status in ("pending", "accepted", "rejected"):
        insert_item("unknown", status)

    with pytest.raises(sqlite3.IntegrityError):
        insert_item("unclassified", "pending")
    with pytest.raises(sqlite3.IntegrityError):
        insert_item("unknown", "ignored")


def test_initialize_migrates_existing_schema(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "existing.sqlite3")
    database.initialize()
    with database.connect() as connection:
        job_id = connection.execute(
            "INSERT INTO import_jobs (source_type) VALUES ('csv')"
        ).lastrowid
        connection.execute(
            """
            INSERT INTO import_items (
                import_job_id, raw_description, amount, expense_date
            ) VALUES (?, 'Compra previa', 2500, '2026-10-29')
            """,
            (job_id,),
        )
        connection.execute("ALTER TABLE expenses ADD COLUMN status TEXT DEFAULT 'confirmed'")

    database.initialize()

    with database.connect() as connection:
        expense_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expenses)")
        }
        item = connection.execute("SELECT * FROM import_items").fetchone()

    assert "status" not in expense_columns
    assert item["raw_description"] == "Compra previa"
    assert item["classification"] == "unknown"
    assert item["status"] == "pending"