import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from app_gestion_gastos.models import Expense, ExpenseBreakdown

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
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        expense_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expenses)")
        }
        if "status" in expense_columns:
            connection.execute("ALTER TABLE expenses DROP COLUMN status")

        import_items_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'import_items'"
        ).fetchone()["sql"]
        if "check (classification in" not in import_items_schema.lower():
            connection.execute(
                """
                CREATE TABLE import_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_job_id INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
                    raw_description TEXT NOT NULL,
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
                """
                INSERT INTO import_items_new (
                    id, import_job_id, raw_description, normalized_description,
                    amount, expense_date, category_id, subcategory_id,
                    classification, status
                )
                SELECT
                    id, import_job_id, raw_description, normalized_description,
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
                "expenses.description, expenses.amount, expenses.expense_date "
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

    def _get_expenses(self, where_clause: str, parameters: tuple[object, ...]) -> list[Expense]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT expenses.id, COALESCE(categories.name, 'Sin categoria') AS category, "
                "COALESCE(subcategories.name, 'Sin subcategoria') AS subcategory, "
                "expenses.description, expenses.amount, expenses.expense_date "
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