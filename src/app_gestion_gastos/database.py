import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process

from app_gestion_gastos.models import (
    ChartData,
    Expense,
    ExpenseBreakdown,
    ExpenseSuggestion,
    ImportClassification,
    ImportJobSummary,
    ImportProcessingResult,
    PendingImportItemSummary,
)
from app_gestion_gastos.text_utils import normalize_text

IMPORT_MATCH_THRESHOLD = 90

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS subcategories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        UNIQUE (category_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL CHECK (length(trim(description)) > 0),
        import_description TEXT,
        expense_date TEXT NOT NULL,
        amount INTEGER NOT NULL CHECK (amount > 0),
        category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
        source TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        import_job_id INTEGER REFERENCES import_jobs(id) ON DELETE SET NULL,
        import_item_id INTEGER REFERENCES import_items(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL,
        filename TEXT,
        imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        status TEXT NOT NULL DEFAULT 'pending'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_job_id INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
        raw_description TEXT NOT NULL,
            user_description TEXT,
        normalized_description TEXT,
        amount INTEGER NOT NULL CHECK (amount > 0),
        expense_date TEXT NOT NULL,
        category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
        classification TEXT NOT NULL DEFAULT 'unknown'
            CHECK (classification IN ('identical', 'similar', 'unknown')),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'accepted', 'rejected'))
    )
    """,
)

INDEX_SCHEMA = (
    "CREATE INDEX IF NOT EXISTS idx_subcategories_category ON subcategories(category_id)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category_id)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_import_job ON expenses(import_job_id)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_import_item ON expenses(import_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_import_items_job ON import_items(import_job_id)",
)


class SQLiteDatabase:
    def __init__(self, path: Path) -> None:
        self._path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            for statement in SCHEMA:
                connection.execute(statement)
            self._migrate(connection)
            for statement in INDEX_SCHEMA:
                connection.execute(statement)

    def list_categories(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT name FROM categories ORDER BY name COLLATE NOCASE")
            return [row["name"] for row in rows]

    def list_import_jobs(self) -> list[ImportJobSummary]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT filename, source_type, imported_at, status "
                "FROM import_jobs ORDER BY imported_at DESC, id DESC"
            )
            return [
                ImportJobSummary(
                    filename=row["filename"],
                    source_type=row["source_type"],
                    imported_at=row["imported_at"],
                    status=row["status"],
                )
                for row in rows
            ]

    def list_pending_import_items(
        self, classification: Literal["similar", "unknown"]
    ) -> list[PendingImportItemSummary]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    import_items.raw_description,
                    import_items.user_description,
                    import_items.amount,
                    categories.name AS category,
                    subcategories.name AS subcategory,
                    import_items.expense_date
                FROM import_items
                LEFT JOIN categories ON categories.id = import_items.category_id
                LEFT JOIN subcategories ON subcategories.id = import_items.subcategory_id
                WHERE import_items.classification = ? AND import_items.status = 'pending'
                ORDER BY import_items.id DESC
                """,
                (classification,),
            )
            return [
                PendingImportItemSummary(
                    raw_description=row["raw_description"],
                    user_description=row["user_description"],
                    amount=Decimal(row["amount"]) / 100,
                    category=row["category"],
                    subcategory=row["subcategory"],
                    expense_date=date.fromisoformat(row["expense_date"]),
                )
                for row in rows
            ]

    def list_subcategories(self, category: str) -> list[str]:
        if not category.strip():
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT subcategories.name
                FROM subcategories
                JOIN categories ON categories.id = subcategories.category_id
                WHERE categories.name = ?
                ORDER BY subcategories.name COLLATE NOCASE
                """,
                (category.strip(),),
            )
            return [row["name"] for row in rows]

    def list_expense_descriptions(self) -> list[str]:
        return sorted(
            {suggestion.description for suggestion in self.list_expense_suggestions()},
            key=str.casefold,
        )

    def list_expense_suggestions(self) -> list[ExpenseSuggestion]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT expenses.description, categories.name AS category, "
                "subcategories.name AS subcategory "
                "FROM expenses "
                "LEFT JOIN categories ON categories.id = expenses.category_id "
                "LEFT JOIN subcategories ON subcategories.id = expenses.subcategory_id "
                "WHERE description IS NOT NULL AND length(trim(description)) > 0 "
                "ORDER BY expenses.id DESC"
            )
            return [
                ExpenseSuggestion(
                    description=row["description"],
                    category=row["category"],
                    subcategory=row["subcategory"],
                )
                for row in rows
            ]

    def classify_import_description(
        self, normalized_description: str
    ) -> ImportClassification:
        normalized = normalize_text(normalized_description)
        with self.connect() as connection:
            return self._classify_import_description(connection, normalized)

    def add_import_item(
        self,
        import_job_id: int,
        raw_description: str,
        amount: Decimal,
        expense_date: date,
    ) -> ImportProcessingResult:
        if not raw_description.strip():
            raise ValueError("La descripcion importada es obligatoria.")
        if not amount.is_finite() or amount <= 0:
            raise ValueError("El importe debe ser mayor que cero.")
        amount_cents = amount * 100
        if amount_cents != amount_cents.to_integral_value():
            raise ValueError("El importe no puede tener mas de dos decimales.")

        normalized = normalize_text(raw_description)
        with self.connect() as connection:
            classification = self._classify_import_description(connection, normalized)
            cursor = connection.execute(
                """
                INSERT INTO import_items (
                    import_job_id, raw_description, user_description,
                    normalized_description, amount, expense_date, category_id,
                    subcategory_id, classification, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_job_id,
                    raw_description,
                    classification.user_description,
                    normalized,
                    int(amount_cents),
                    expense_date.isoformat(),
                    classification.category_id,
                    classification.subcategory_id,
                    classification.classification,
                    classification.status,
                ),
            )
            import_item_id = cursor.lastrowid
            expense_id = None
            if classification.create_expense:
                expense_cursor = connection.execute(
                    """
                    INSERT INTO expenses (
                        description, import_description, expense_date, amount,
                        category_id, subcategory_id, source, import_job_id, import_item_id
                    ) VALUES (?, ?, ?, ?, ?, ?, 'import', ?, ?)
                    """,
                    (
                        classification.user_description,
                        normalized,
                        expense_date.isoformat(),
                        int(amount_cents),
                        classification.category_id,
                        classification.subcategory_id,
                        import_job_id,
                        import_item_id,
                    ),
                )
                expense_id = expense_cursor.lastrowid
        return ImportProcessingResult(import_item_id, classification, expense_id)

    def _classify_import_description(
        self, connection: sqlite3.Connection, normalized: str
    ) -> ImportClassification:
        unknown = ImportClassification("unknown", "pending", None, None, None, False)
        if not normalized:
            return unknown

        exact = connection.execute(
            """
            SELECT description, category_id, subcategory_id
            FROM expenses
            WHERE import_description = ?
                AND category_id IS NOT NULL
                AND subcategory_id IS NOT NULL
            ORDER BY expense_date DESC, id DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if exact is not None:
            return ImportClassification(
                classification="identical",
                status="accepted",
                user_description=exact["description"],
                category_id=exact["category_id"],
                subcategory_id=exact["subcategory_id"],
                create_expense=True,
                similarity=100.0,
            )

        candidates = connection.execute(
            """
            SELECT import_description, description, category_id, subcategory_id
            FROM expenses
            WHERE import_description IS NOT NULL
                AND length(trim(import_description)) > 0
                AND category_id IS NOT NULL
                AND subcategory_id IS NOT NULL
            ORDER BY expense_date DESC, id DESC
            """
        ).fetchall()

        candidate_descriptions = [
            normalize_text(row["import_description"]) for row in candidates
        ]
        match = process.extractOne(
            normalized,
            candidate_descriptions,
            scorer=fuzz.ratio,
            score_cutoff=IMPORT_MATCH_THRESHOLD,
        )
        if match is None:
            return unknown

        matched_row = candidates[match[2]]
        return ImportClassification(
            classification="similar",
            status="pending",
            user_description=matched_row["description"],
            category_id=matched_row["category_id"],
            subcategory_id=matched_row["subcategory_id"],
            create_expense=False,
            similarity=match[1],
        )

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        expense_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expenses)")
        }
        if "status" in expense_columns:
            connection.execute("ALTER TABLE expenses DROP COLUMN status")
        if "import_job_id" not in expense_columns:
            connection.execute(
                "ALTER TABLE expenses ADD COLUMN import_job_id INTEGER "
                "REFERENCES import_jobs(id) ON DELETE SET NULL"
            )
        if "import_item_id" not in expense_columns:
            connection.execute(
                "ALTER TABLE expenses ADD COLUMN import_item_id INTEGER "
                "REFERENCES import_items(id) ON DELETE SET NULL"
            )

        import_items_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'import_items'"
        ).fetchone()
        import_items_schema = import_items_row["sql"]
        import_item_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(import_items)")
        }
        has_user_description = "user_description" in import_item_columns
        has_classification_check = "check (classification in" in import_items_schema.lower()
        if not has_user_description or not has_classification_check:
            user_description_source = "user_description" if has_user_description else "NULL"
            connection.execute(
                """
                CREATE TABLE import_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_job_id INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
                    raw_description TEXT NOT NULL,
                    user_description TEXT,
                    normalized_description TEXT,
                    amount INTEGER NOT NULL CHECK (amount > 0),
                    expense_date TEXT NOT NULL,
                    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                    subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
                    classification TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (classification IN ('identical', 'similar', 'unknown')),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'rejected'))
                )
                """
            )
            connection.execute(
                f"""
                INSERT INTO import_items_new (
                    id, import_job_id, raw_description, user_description, normalized_description,
                    amount, expense_date, category_id, subcategory_id,
                    classification, status
                )
                SELECT
                    id, import_job_id, raw_description, {user_description_source},
                    normalized_description,
                    amount, expense_date, category_id, subcategory_id,
                    CASE WHEN classification IN ('identical', 'similar', 'unknown')
                        THEN classification ELSE 'unknown' END,
                    CASE WHEN status IN ('pending', 'accepted', 'rejected')
                        THEN status ELSE 'pending' END
                FROM import_items
                """
            )
            connection.execute("DROP TABLE import_items")
            connection.execute("ALTER TABLE import_items_new RENAME TO import_items")

    def add(self, expense: Expense) -> Expense:
        if not expense.subcategory or not expense.subcategory.strip():
            raise ValueError("La subcategoria es obligatoria.")
        amount_cents = expense.amount * 100
        if amount_cents != amount_cents.to_integral_value():
            raise ValueError("El importe no puede tener mas de dos decimales.")

        with self.connect() as connection:
            connection.execute(
                "INSERT INTO categories (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                (expense.category,),
            )
            category_id = connection.execute(
                "SELECT id FROM categories WHERE name = ?", (expense.category,)
            ).fetchone()["id"]
            subcategory_id = None
            if expense.subcategory:
                connection.execute(
                    """
                    INSERT INTO subcategories (category_id, name) VALUES (?, ?)
                    ON CONFLICT(category_id, name) DO NOTHING
                    """,
                    (category_id, expense.subcategory),
                )
                subcategory_id = connection.execute(
                    """
                    SELECT id FROM subcategories
                    WHERE category_id = ? AND name = ?
                    """,
                    (category_id, expense.subcategory),
                ).fetchone()["id"]
            cursor = connection.execute(
                """
                INSERT INTO expenses (
                    description, expense_date, amount, category_id, subcategory_id, source
                )
                VALUES (?, ?, ?, ?, ?, 'manual')
                """,
                (
                    expense.description,
                    expense.spent_on.isoformat(),
                    int(amount_cents),
                    category_id,
                    subcategory_id,
                ),
            )
            expense_id = cursor.lastrowid
        return Expense(
            id=expense_id,
            category=expense.category,
            description=expense.description,
            amount=expense.amount,
            spent_on=expense.spent_on,
            subcategory=expense.subcategory,
        )

    def list_all(self) -> list[Expense]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT expenses.id, categories.name AS category, "
                "subcategories.name AS subcategory, "
                "expenses.description, expenses.amount, expenses.expense_date, "
                "expenses.import_job_id, expenses.import_item_id "
                "FROM expenses LEFT JOIN categories ON categories.id = expenses.category_id "
                "LEFT JOIN subcategories ON subcategories.id = expenses.subcategory_id "
                "ORDER BY expenses.expense_date DESC, expenses.id DESC"
            ).fetchall()
        return [
            Expense(
                id=row["id"],
                category=row["category"],
                description=row["description"],
                amount=Decimal(row["amount"]) / 100,
                spent_on=date.fromisoformat(row["expense_date"]),
                subcategory=row["subcategory"],
                import_job_id=row["import_job_id"],
                import_item_id=row["import_item_id"],
            )
            for row in rows
        ]

    def get_expenses_for_month(self, year: int, month: int) -> list[Expense]:
        start, end = self._month_bounds(year, month)
        return self._get_expenses(
            "expenses.expense_date >= ? AND expenses.expense_date < ?", (start, end)
        )

    def get_expenses_for_month_and_category(
        self, year: int, month: int, category_id: int
    ) -> list[Expense]:
        start, end = self._month_bounds(year, month)
        return self._get_expenses(
            "expenses.expense_date >= ? AND expenses.expense_date < ? "
            "AND expenses.category_id = ?",
            (start, end, category_id),
        )

    def get_expenses_for_month_and_subcategory(
        self, year: int, month: int, subcategory_id: int
    ) -> list[Expense]:
        start, end = self._month_bounds(year, month)
        return self._get_expenses(
            "expenses.expense_date >= ? AND expenses.expense_date < ? "
            "AND expenses.subcategory_id = ?",
            (start, end, subcategory_id),
        )

    def get_expenses_for_week(self, year: int, week: int) -> list[Expense]:
        start, end = self._week_bounds(year, week)
        return self._get_expenses(
            "expenses.expense_date >= ? AND expenses.expense_date < ?", (start, end)
        )

    def get_expenses_for_week_and_category(
        self, year: int, week: int, category_id: int
    ) -> list[Expense]:
        start, end = self._week_bounds(year, week)
        return self._get_expenses(
            "expenses.expense_date >= ? AND expenses.expense_date < ? "
            "AND expenses.category_id = ?",
            (start, end, category_id),
        )

    def get_total_between_dates(self, start_date: date, end_date: date) -> Decimal:
        if end_date < start_date:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total "
                "FROM expenses WHERE expense_date BETWEEN ? AND ?",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchone()
        return Decimal(row["total"]) / 100

    def get_breakdown_between_dates(
        self, start_date: date, end_date: date
    ) -> list[ExpenseBreakdown]:
        if end_date < start_date:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    strftime('%Y-%m', expenses.expense_date) AS month,
                    COALESCE(categories.name, 'Sin categoria') AS category,
                    COALESCE(subcategories.name, 'Sin subcategoria') AS subcategory,
                    SUM(expenses.amount) AS amount
                FROM expenses
                LEFT JOIN categories ON categories.id = expenses.category_id
                LEFT JOIN subcategories ON subcategories.id = expenses.subcategory_id
                WHERE expenses.expense_date BETWEEN ? AND ?
                GROUP BY month, category, subcategory
                ORDER BY month, category COLLATE NOCASE, subcategory COLLATE NOCASE
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [
            ExpenseBreakdown(
                month=row["month"],
                category=row["category"],
                subcategory=row["subcategory"],
                amount=Decimal(row["amount"]) / 100,
            )
            for row in rows
        ]

    def get_chart_data(
        self,
        start_date: date,
        end_date: date,
        period_unit: Literal["month", "week"],
        by_category: bool,
    ) -> list[ChartData]:
        if end_date < start_date:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        if period_unit == "month":
            period_expression = "strftime('%Y-%m', expenses.expense_date)"
        elif period_unit == "week":
            period_expression = (
                "date(expenses.expense_date, '-' || "
                "((CAST(strftime('%w', expenses.expense_date) AS INTEGER) + 6) % 7) "
                "|| ' days')"
            )
        else:
            raise ValueError("El periodo debe ser 'month' o 'week'.")

        category_expression = "COALESCE(categories.name, 'Sin categoria')"
        category_select = f", {category_expression} AS category" if by_category else ""
        category_group = ", category" if by_category else ""
        category_join = (
            "LEFT JOIN categories ON categories.id = expenses.category_id "
            if by_category
            else ""
        )
        category_order = ", category COLLATE NOCASE" if by_category else ""
        query = (
            f"SELECT {period_expression} AS period{category_select}, "
            "SUM(expenses.amount) AS amount "
            "FROM expenses "
            f"{category_join}"
            "WHERE expenses.expense_date BETWEEN ? AND ? "
            f"GROUP BY period{category_group} "
            f"ORDER BY period{category_order}"
        )
        with self.connect() as connection:
            rows = connection.execute(
                query, (start_date.isoformat(), end_date.isoformat())
            ).fetchall()
        return [
            ChartData(
                period=row["period"],
                category=row["category"] if by_category else None,
                amount=Decimal(row["amount"]) / 100,
            )
            for row in rows
        ]

    def _get_expenses(self, where_clause: str, parameters: tuple[object, ...]) -> list[Expense]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT expenses.id, COALESCE(categories.name, 'Sin categoria') AS category, "
                "COALESCE(subcategories.name, 'Sin subcategoria') AS subcategory, "
                "expenses.description, expenses.amount, expenses.expense_date, "
                "expenses.import_job_id, expenses.import_item_id "
                "FROM expenses "
                "LEFT JOIN categories ON categories.id = expenses.category_id "
                "LEFT JOIN subcategories ON subcategories.id = expenses.subcategory_id "
                f"WHERE {where_clause} "
                "ORDER BY expenses.expense_date DESC, expenses.id DESC",
                parameters,
            ).fetchall()
        return [
            Expense(
                id=row["id"],
                category=row["category"],
                description=row["description"],
                amount=Decimal(row["amount"]) / 100,
                spent_on=date.fromisoformat(row["expense_date"]),
                subcategory=row["subcategory"],
                import_job_id=row["import_job_id"],
                import_item_id=row["import_item_id"],
            )
            for row in rows
        ]

    @staticmethod
    def _month_bounds(year: int, month: int) -> tuple[str, str]:
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        return start.isoformat(), end.isoformat()

    @staticmethod
    def _week_bounds(year: int, week: int) -> tuple[str, str]:
        start = date.fromisocalendar(year, week, 1)
        end = start + timedelta(days=7)
        return start.isoformat(), end.isoformat()