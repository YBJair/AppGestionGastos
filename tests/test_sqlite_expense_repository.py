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
            "SELECT amount, source, subcategory_id, expense_date, import_job_id, import_item_id "
            "FROM expenses WHERE id = ?",
            (saved.id,),
        ).fetchone()
    assert row["amount"] == 3990
    assert row["source"] == "manual"
    assert row["subcategory_id"] is not None
    assert row["expense_date"] == "2026-10-01"
    assert row["import_job_id"] is None
    assert row["import_item_id"] is None

def test_update_expense_changes_fields_and_preserves_import_metadata(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "update-expense.sqlite3")
    database.initialize()
    saved = database.add(
        Expense(
            "Hogar",
            "Compra inicial",
            Decimal("12.50"),
            date(2026, 1, 1),
            subcategory="General",
        )
    )
    with database.connect() as connection:
        job_id = connection.execute(
            "INSERT INTO import_jobs (source_type, filename) VALUES ('CSV', 'cargas.csv')"
        ).lastrowid
        item_id = connection.execute(
            """
            INSERT INTO import_items (
                import_job_id, raw_description, amount, expense_date
            ) VALUES (?, 'Cargo banco', 1250, '2026-01-01')
            """,
            (job_id,),
        ).lastrowid
        connection.execute(
            "UPDATE expenses SET source = 'import', import_description = ?, "
            "import_job_id = ?, import_item_id = ? WHERE id = ?",
            ("cargo banco", job_id, item_id, saved.id),
        )

    database.update_expenses(
        [
            Expense(
                "Alimentación",
                "Compra semanal",
                Decimal("34.75"),
                date(2026, 2, 3),
                id=saved.id,
                subcategory="Supermercado",
            )
        ]
    )

    updated = database.list_all()[0]
    with database.connect() as connection:
        metadata = connection.execute(
            "SELECT source, import_description, import_job_id, import_item_id "
            "FROM expenses WHERE id = ?",
            (saved.id,),
        ).fetchone()
    assert updated.description == "Compra semanal"
    assert updated.amount == Decimal("34.75")
    assert updated.spent_on == date(2026, 2, 3)
    assert updated.category == "Alimentación"
    assert updated.subcategory == "Supermercado"
    assert metadata["source"] == "import"
    assert metadata["import_description"] == "cargo banco"
    assert metadata["import_job_id"] == job_id
    assert metadata["import_item_id"] == item_id


def test_delete_expenses_removes_only_selected_ids(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "delete-expense.sqlite3")
    database.initialize()
    expenses = [
        database.add(
            Expense(
                "Hogar",
                description,
                Decimal("5.00"),
                date(2026, 1, index),
                subcategory="General",
            )
        )
        for index, description in enumerate(("Primero", "Segundo"), start=1)
    ]

    database.delete_expenses([expenses[0].id])

    assert [expense.description for expense in database.list_all()] == ["Segundo"]


def test_list_expense_descriptions_returns_distinct_non_empty_values(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "descriptions.sqlite3")
    database.initialize()
    for description in ("Compra mensual", "Compra mensual", "Factura de agua"):
        database.add(
            Expense(
                category="Hogar",
                description=description,
                amount=Decimal("10.00"),
                spent_on=date(2026, 10, 1),
                subcategory="General",
            )
        )

    assert database.list_expense_descriptions() == ["Compra mensual", "Factura de agua"]


def test_month_queries_and_date_range_total(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "queries.sqlite3")
    database.initialize()
    expenses = (
        Expense("Hogar", "Renta", Decimal("160.17"), date(2026, 2, 1), subcategory="Renta"),
        Expense("Hogar", "Luz", Decimal("69.03"), date(2026, 2, 15), subcategory="Luz"),
        Expense(
            "Mascotas", "Comida", Decimal("37.45"), date(2026, 2, 28), subcategory="Comida"
        ),
        Expense("Hogar", "Renta", Decimal("10.00"), date(2026, 3, 1), subcategory="Renta"),
    )
    for expense in expenses:
        database.add(expense)

    with database.connect() as connection:
        category_id = connection.execute(
            "SELECT id FROM categories WHERE name = 'Hogar'"
        ).fetchone()["id"]
        subcategory_id = connection.execute(
            "SELECT id FROM subcategories WHERE name = 'Luz'"
        ).fetchone()["id"]

    february = database.get_expenses_for_month(2026, 2)
    category_expenses = database.get_expenses_for_month_and_category(2026, 2, category_id)
    subcategory_expenses = database.get_expenses_for_month_and_subcategory(
        2026, 2, subcategory_id
    )

    assert {expense.description for expense in february} == {"Renta", "Luz", "Comida"}
    assert {expense.description for expense in category_expenses} == {"Renta", "Luz"}
    assert [expense.description for expense in subcategory_expenses] == ["Luz"]
    assert database.get_total_between_dates(date(2026, 2, 1), date(2026, 2, 28)) == Decimal(
        "266.65"
    )
    assert database.get_total_between_dates(date(2026, 2, 15), date(2026, 3, 1)) == Decimal(
        "116.48"
    )
    breakdown = database.get_breakdown_between_dates(date(2026, 2, 1), date(2026, 2, 28))
    assert sum((entry.amount for entry in breakdown), Decimal("0")) == Decimal("266.65")


def test_iso_week_queries_and_chart_aggregates(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "weeks.sqlite3")
    database.initialize()
    expenses = (
        Expense("Hogar", "Factura", Decimal("12.50"), date(2025, 12, 29), subcategory="Luz"),
        Expense("Hogar", "Compra", Decimal("5.00"), date(2026, 1, 4), subcategory="Cocina"),
        Expense(
            "Transporte", "Abono", Decimal("20.00"), date(2026, 1, 5), subcategory="Público"
        ),
    )
    for expense in expenses:
        database.add(expense)

    with database.connect() as connection:
        household_id = connection.execute(
            "SELECT id FROM categories WHERE name = 'Hogar'"
        ).fetchone()["id"]

    first_iso_week = database.get_expenses_for_week(2026, 1)
    household_week = database.get_expenses_for_week_and_category(2026, 1, household_id)
    weekly_totals = database.get_chart_data(
        date(2025, 12, 29), date(2026, 1, 11), "week", False
    )
    weekly_categories = database.get_chart_data(
        date(2025, 12, 29), date(2026, 1, 11), "week", True
    )

    assert {expense.description for expense in first_iso_week} == {"Factura", "Compra"}
    assert {expense.description for expense in household_week} == {"Factura", "Compra"}
    assert [(item.period, item.amount) for item in weekly_totals] == [
        ("2025-12-29", Decimal("17.50")),
        ("2026-01-05", Decimal("20.00")),
    ]
    assert {item.category for item in weekly_categories} == {"Hogar", "Transporte"}


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
            "import_job_id",
            "import_item_id",
        },
        "import_jobs": {"id", "source_type", "filename", "imported_at", "status"},
        "import_items": {
            "id",
            "import_job_id",
            "raw_description",
               "user_description",
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
        connection.execute("ALTER TABLE import_items DROP COLUMN user_description")
        connection.execute("ALTER TABLE expenses ADD COLUMN status TEXT DEFAULT 'confirmed'")

    database.initialize()

    with database.connect() as connection:
        expense_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expenses)")
        }
        item = connection.execute("SELECT * FROM import_items").fetchone()

    assert "status" not in expense_columns
    assert item["raw_description"] == "Compra previa"
    assert item["user_description"] is None
    assert item["classification"] == "unknown"
    assert item["status"] == "pending"


def test_import_description_classification_prefers_newest_exact_match(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "import-classification.sqlite3")
    database.initialize()
    older = database.add(
        Expense(
            "Hogar", "Factura antigua", Decimal("45.00"), date(2026, 1, 1), subcategory="Luz"
        )
    )
    newer = database.add(
        Expense(
            "Servicios",
            "Factura eléctrica",
            Decimal("50.00"),
            date(2026, 2, 1),
            subcategory="Electricidad",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE expenses SET import_description = ? WHERE id IN (?, ?)",
            ("cargo electricidad", older.id, newer.id),
        )
        newest_category = connection.execute(
            "SELECT id FROM categories WHERE name = 'Servicios'"
        ).fetchone()["id"]
        newest_subcategory = connection.execute(
            "SELECT id FROM subcategories WHERE name = 'Electricidad'"
        ).fetchone()["id"]

    result = database.classify_import_description("cargo electricidad")

    assert result.classification == "identical"
    assert result.status == "accepted"
    assert result.user_description == "Factura eléctrica"
    assert result.category_id == newest_category
    assert result.subcategory_id == newest_subcategory
    assert result.create_expense
    assert result.similarity == 100


def test_import_description_classification_returns_similar_and_unknown(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "import-similar.sqlite3")
    database.initialize()
    expense = database.add(
        Expense(
            "Supermercado",
            "Compra semanal",
            Decimal("70.00"),
            date(2026, 3, 1),
            subcategory="General",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE expenses SET import_description = ? WHERE id = ?",
            ("compra supermercado", expense.id),
        )
        category_id = connection.execute(
            "SELECT id FROM categories WHERE name = 'Supermercado'"
        ).fetchone()["id"]
        subcategory_id = connection.execute(
            "SELECT id FROM subcategories WHERE name = 'General'"
        ).fetchone()["id"]

    similar = database.classify_import_description("compra supermecado")
    unknown = database.classify_import_description("pago completamente distinto")

    assert similar.classification == "similar"
    assert similar.status == "pending"
    assert similar.user_description == "Compra semanal"
    assert similar.category_id == category_id
    assert similar.subcategory_id == subcategory_id
    assert not similar.create_expense
    assert similar.similarity is not None and similar.similarity >= 90
    assert unknown.classification == "unknown"
    assert unknown.status == "pending"
    assert unknown.user_description is None
    assert not unknown.create_expense


def test_add_import_item_accepts_exact_and_leaves_other_matches_pending(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "process-import-items.sqlite3")
    database.initialize()
    previous_expense = database.add(
        Expense(
            "Servicios",
            "Factura eléctrica",
            Decimal("50.00"),
            date(2026, 2, 1),
            subcategory="Electricidad",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE expenses SET import_description = ? WHERE id = ?",
            ("cargo electricidad", previous_expense.id),
        )
        import_job_id = connection.execute(
            "INSERT INTO import_jobs (source_type, filename) VALUES ('csv', 'extracto.csv')"
        ).lastrowid

    exact = database.add_import_item(
        import_job_id, "CARGO electricidad", Decimal("51.25"), date(2026, 3, 1)
    )
    similar = database.add_import_item(
        import_job_id, "cargo electricida", Decimal("7.50"), date(2026, 3, 2)
    )
    unknown = database.add_import_item(
        import_job_id, "pago completamente desconocido", Decimal("3.00"), date(2026, 3, 3)
    )

    with database.connect() as connection:
        exact_item = connection.execute(
            "SELECT * FROM import_items WHERE id = ?", (exact.import_item_id,)
        ).fetchone()
        exact_expense = connection.execute(
            "SELECT * FROM expenses WHERE id = ?", (exact.expense_id,)
        ).fetchone()
        similar_item = connection.execute(
            "SELECT * FROM import_items WHERE id = ?", (similar.import_item_id,)
        ).fetchone()
        unknown_item = connection.execute(
            "SELECT * FROM import_items WHERE id = ?", (unknown.import_item_id,)
        ).fetchone()
        imported_expense_count = connection.execute(
            "SELECT COUNT(*) FROM expenses WHERE source = 'import'"
        ).fetchone()[0]

    assert exact.classification.classification == "identical"
    assert exact.classification.status == "accepted"
    assert exact.expense_id is not None
    assert exact_item["raw_description"] == "CARGO electricidad"
    assert exact_item["normalized_description"] == "cargo electricidad"
    assert exact_item["user_description"] == "Factura eléctrica"
    assert exact_item["classification"] == "identical"
    assert exact_item["status"] == "accepted"
    assert exact_expense["description"] == "Factura eléctrica"
    assert exact_expense["import_description"] == "cargo electricidad"
    assert exact_expense["expense_date"] == "2026-03-01"
    assert exact_expense["amount"] == 5125
    assert exact_expense["category_id"] == exact_item["category_id"]
    assert exact_expense["subcategory_id"] == exact_item["subcategory_id"]
    assert exact_expense["source"] == "import"
    assert exact_expense["import_job_id"] == import_job_id
    assert exact_expense["import_item_id"] == exact.import_item_id

    assert similar.classification.classification == "similar"
    assert similar.expense_id is None
    assert similar_item["user_description"] == "Factura eléctrica"
    assert similar_item["category_id"] == exact_item["category_id"]
    assert similar_item["subcategory_id"] == exact_item["subcategory_id"]
    assert similar_item["status"] == "pending"
    assert unknown.classification.classification == "unknown"
    assert unknown_item["user_description"] is None
    assert unknown_item["category_id"] is None
    assert unknown_item["subcategory_id"] is None
    assert unknown_item["status"] == "pending"
    assert imported_expense_count == 1