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
    ImportItemSummary,
    ImportJobSummary,
    ImportProcessingResult,
    ParsedCsvExpense,
    ParsedPdfTransaction,
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
        import_item_id INTEGER REFERENCES import_items(id) ON DELETE SET NULL,
        generic INTEGER NOT NULL DEFAULT 0 CHECK (generic IN (0, 1))
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
        generic INTEGER NOT NULL DEFAULT 0 CHECK (generic IN (0, 1)),
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
                "SELECT id, filename, source_type, imported_at, status "
                "FROM import_jobs ORDER BY imported_at DESC, id DESC"
            )
            return [
                ImportJobSummary(
                    id=row["id"],
                    filename=row["filename"],
                    source_type=row["source_type"],
                    imported_at=row["imported_at"],
                    status=row["status"],
                )
                for row in rows
            ]

    def list_import_items_for_job(self, import_job_id: int) -> list[ImportItemSummary]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    import_items.id,
                    import_items.raw_description,
                    import_items.user_description,
                    import_items.amount,
                    categories.name AS category,
                    subcategories.name AS subcategory,
                    import_items.expense_date,
                    import_items.status
                FROM import_items
                LEFT JOIN categories ON categories.id = import_items.category_id
                LEFT JOIN subcategories ON subcategories.id = import_items.subcategory_id
                WHERE import_items.import_job_id = ?
                ORDER BY
                    CASE WHEN import_items.status = 'pending' THEN 0 ELSE 1 END,
                    import_items.expense_date ASC,
                    import_items.id ASC
                """,
                (import_job_id,),
            )
            return [
                ImportItemSummary(
                    id=row["id"],
                    raw_description=row["raw_description"],
                    user_description=row["user_description"],
                    amount=Decimal(row["amount"]) / 100,
                    category=row["category"],
                    subcategory=row["subcategory"],
                    expense_date=date.fromisoformat(row["expense_date"]),
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
                    import_items.id,
                    import_items.generic,
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
                    id=row["id"],
                    generic=bool(row["generic"]),
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

        with self.connect() as connection:
            result = self._insert_classified_import_item(
                connection,
                import_job_id,
                raw_description,
                normalize_text(raw_description),
                int(amount_cents),
                expense_date,
            )
            self._refresh_import_job_status(connection, import_job_id)
        return result

    def import_csv_expenses(
        self, filename: str, rows: list[ParsedCsvExpense]
    ) -> tuple[int, int]:
        with self.connect() as connection:
            job_cursor = connection.execute(
                """
                    INSERT INTO import_jobs (source_type, filename, status)
                    VALUES ('CSV', ?, 'pending')
                """,
                (Path(filename).name,),
            )
            import_job_id = job_cursor.lastrowid
            categories = {
                row["name"].strip().casefold(): (row["id"], row["name"])
                for row in connection.execute("SELECT id, name FROM categories")
            }
            subcategories = {
                (row["category_id"], row["name"].strip().casefold()): (
                    row["id"],
                    row["name"],
                )
                for row in connection.execute("SELECT id, category_id, name FROM subcategories")
            }

            for row in rows:
                category_key = row.category.casefold()
                category = categories.get(category_key)
                if category is None:
                    category_id = connection.execute(
                        "INSERT INTO categories (name) VALUES (?)", (row.category,)
                    ).lastrowid
                    categories[category_key] = (category_id, row.category)
                else:
                    category_id = category[0]

                subcategory_key = (category_id, row.subcategory.casefold())
                subcategory = subcategories.get(subcategory_key)
                if subcategory is None:
                    subcategory_id = connection.execute(
                        "INSERT INTO subcategories (category_id, name) VALUES (?, ?)",
                        (category_id, row.subcategory),
                    ).lastrowid
                    subcategories[subcategory_key] = (subcategory_id, row.subcategory)
                else:
                    subcategory_id = subcategory[0]

                item_id = connection.execute(
                    """
                    INSERT INTO import_items (
                        import_job_id, raw_description, user_description,
                        normalized_description, amount, expense_date, category_id,
                        subcategory_id, classification, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'identical', 'accepted')
                    """,
                    (
                        import_job_id,
                        row.note,
                        row.note,
                        row.normalized_note,
                        row.amount_cents,
                        row.expense_date.isoformat(),
                        category_id,
                        subcategory_id,
                    ),
                ).lastrowid
                connection.execute(
                    """
                    INSERT INTO expenses (
                        description, import_description, expense_date, amount,
                        category_id, subcategory_id, source, import_job_id, import_item_id
                    ) VALUES (?, ?, ?, ?, ?, ?, 'import', ?, ?)
                    """,
                    (
                        row.note,
                        row.normalized_note,
                        row.expense_date.isoformat(),
                        row.amount_cents,
                        category_id,
                        subcategory_id,
                        import_job_id,
                        item_id,
                    ),
                )
            self._refresh_import_job_status(connection, import_job_id)
        return import_job_id, len(rows)

    def import_pdf_expenses(
        self, filename: str, rows: list[ParsedPdfTransaction]
    ) -> tuple[int, int]:
        if not rows:
            raise ValueError("El PDF no contiene salidas de dinero para importar.")
        with self.connect() as connection:
            job_id = connection.execute(
                """
                INSERT INTO import_jobs (source_type, filename, status)
                VALUES ('PDF', ?, 'pending')
                """,
                (Path(filename).name,),
            ).lastrowid
            for row in rows:
                self._insert_classified_import_item(
                    connection,
                    job_id,
                    row.description,
                    normalize_text(row.description),
                    row.amount_cents,
                    row.expense_date,
                )
            self._refresh_import_job_status(connection, job_id)
        return job_id, len(rows)

    def accept_import_item(self, import_item_id: int) -> None:
        with self.connect() as connection:
            item = connection.execute(
                "SELECT * FROM import_items WHERE id = ?", (import_item_id,)
            ).fetchone()
            if item is None:
                raise ValueError("No existe la línea de importación.")
            if item["status"] != "accepted":
                if (
                    not item["user_description"]
                    or not item["category_id"]
                    or not item["subcategory_id"]
                ):
                    raise ValueError("Completa alias, categoría y subcategoría antes de aceptar.")
                existing_expense = connection.execute(
                    "SELECT id FROM expenses WHERE import_item_id = ? LIMIT 1",
                    (import_item_id,),
                ).fetchone()
                if existing_expense is None:
                    connection.execute(
                        """
                        INSERT INTO expenses (
                            description, import_description, expense_date, amount,
                            category_id, subcategory_id, source, import_job_id, import_item_id,
                            generic
                        ) VALUES (?, ?, ?, ?, ?, ?, 'import', ?, ?, ?)
                        """,
                        (
                            item["user_description"],
                            item["normalized_description"],
                            item["expense_date"],
                            item["amount"],
                            item["category_id"],
                            item["subcategory_id"],
                            item["import_job_id"],
                            import_item_id,
                            item["generic"],
                        ),
                    )
            connection.execute(
                "UPDATE import_items SET status = 'accepted' WHERE id = ?",
                (import_item_id,),
            )
            self._refresh_import_job_status(connection, item["import_job_id"])

    def accept_import_item_with_data(
        self,
        import_item_id: int,
        user_description: str,
        category: str,
        subcategory: str,
        generic: bool = False,
    ) -> None:
        with self.connect() as connection:
            item = connection.execute(
                "SELECT * FROM import_items WHERE id = ?", (import_item_id,)
            ).fetchone()
            if item is None:
                raise ValueError("No existe la línea de importación.")
            if item["status"] == "accepted":
                self._refresh_import_job_status(connection, item["import_job_id"])
                return

            user_description = user_description.strip()
            category = category.strip()
            subcategory = subcategory.strip()
            if not user_description or not category or not subcategory:
                raise ValueError("Completa alias, categoría y subcategoría antes de aceptar.")

            connection.execute(
                "INSERT INTO categories (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                (category,),
            )
            category_row = connection.execute(
                "SELECT id FROM categories WHERE name = ?", (category,)
            ).fetchone()
            category_id = category_row["id"]
            connection.execute(
                """
                INSERT INTO subcategories (category_id, name) VALUES (?, ?)
                ON CONFLICT(category_id, name) DO NOTHING
                """,
                (category_id, subcategory),
            )
            subcategory_row = connection.execute(
                """
                SELECT id FROM subcategories
                WHERE category_id = ? AND name = ?
                """,
                (category_id, subcategory),
            ).fetchone()
            subcategory_id = subcategory_row["id"]

            connection.execute(
                """
                UPDATE import_items
                SET user_description = ?, category_id = ?, subcategory_id = ?, generic = ?
                WHERE id = ?
                """,
                (user_description, category_id, subcategory_id, int(generic), import_item_id),
            )

            if item["classification"] == "unknown":
                connection.execute(
                    """
                    UPDATE import_items
                    SET user_description = ?, category_id = ?, subcategory_id = ?
                    WHERE import_job_id = ?
                      AND normalized_description = ?
                      AND status = 'pending'
                      AND classification = 'unknown'
                      AND id <> ?
                    """,
                    (
                        user_description,
                        category_id,
                        subcategory_id,
                        item["import_job_id"],
                        item["normalized_description"],
                        import_item_id,
                    ),
                )

            item = connection.execute(
                "SELECT * FROM import_items WHERE id = ?", (import_item_id,)
            ).fetchone()
            existing_expense = connection.execute(
                "SELECT id FROM expenses WHERE import_item_id = ? LIMIT 1",
                (import_item_id,),
            ).fetchone()
            if existing_expense is None:
                connection.execute(
                    """
                    INSERT INTO expenses (
                        description, import_description, expense_date, amount,
                        category_id, subcategory_id, source, import_job_id, import_item_id,
                        generic
                    ) VALUES (?, ?, ?, ?, ?, ?, 'import', ?, ?, ?)
                    """,
                    (
                        item["user_description"],
                        item["normalized_description"],
                        item["expense_date"],
                        item["amount"],
                        item["category_id"],
                        item["subcategory_id"],
                        item["import_job_id"],
                        import_item_id,
                        item["generic"],
                    ),
                )

            connection.execute(
                "UPDATE import_items SET status = 'accepted' WHERE id = ?",
                (import_item_id,),
            )
            self._refresh_import_job_status(connection, item["import_job_id"])
    def delete_import_items(self, import_item_ids: list[int]) -> None:
        if not import_item_ids:
            return
        with self.connect() as connection:
            placeholders = ", ".join("?" for _ in import_item_ids)
            job_rows = connection.execute(
                f"SELECT DISTINCT import_job_id FROM import_items WHERE id IN ({placeholders})",
                tuple(import_item_ids),
            ).fetchall()
            connection.execute(
                f"DELETE FROM import_items WHERE id IN ({placeholders})",
                tuple(import_item_ids),
            )
            for row in job_rows:
                self._refresh_import_job_status(connection, row["import_job_id"])

    def _insert_classified_import_item(
        self,
        connection: sqlite3.Connection,
        import_job_id: int,
        raw_description: str,
        normalized_description: str,
        amount_cents: int,
        expense_date: date,
    ) -> ImportProcessingResult:
        classification = self._classify_import_description(connection, normalized_description)
        item_id = connection.execute(
            """
            INSERT INTO import_items (
                import_job_id, raw_description, user_description,
                normalized_description, amount, expense_date, category_id,
                subcategory_id, classification, status, generic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_job_id,
                raw_description,
                classification.user_description,
                normalized_description,
                amount_cents,
                expense_date.isoformat(),
                classification.category_id,
                classification.subcategory_id,
                classification.classification,
                classification.status,
                int(classification.generic),
            ),
        ).lastrowid
        expense_id = None
        if classification.create_expense:
            expense_id = connection.execute(
                """
                INSERT INTO expenses (
                    description, import_description, expense_date, amount,
                    category_id, subcategory_id, source, import_job_id, import_item_id,
                    generic
                ) VALUES (?, ?, ?, ?, ?, ?, 'import', ?, ?, ?)
                """,
                (
                    classification.user_description,
                    normalized_description,
                    expense_date.isoformat(),
                    amount_cents,
                    classification.category_id,
                    classification.subcategory_id,
                    import_job_id,
                    item_id,
                    int(classification.generic),
                ),
            ).lastrowid
        return ImportProcessingResult(item_id, classification, expense_id)

    @staticmethod
    def _refresh_import_job_status(connection: sqlite3.Connection, import_job_id: int) -> None:
        counts = connection.execute(
            """
            SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'accepted' THEN 0 ELSE 1 END) AS awaiting_acceptance
            FROM import_items
            WHERE import_job_id = ?
            """,
            (import_job_id,),
        ).fetchone()
        status = (
            "completed"
            if counts["total"] == 0 or (counts["total"] > 0 and counts["awaiting_acceptance"] == 0)
            else "pending"
        )
        connection.execute(
            "UPDATE import_jobs SET status = ? WHERE id = ?", (status, import_job_id)
        )

    def _classify_import_description(
        self, connection: sqlite3.Connection, normalized: str
    ) -> ImportClassification:
        unknown = ImportClassification("unknown", "pending", None, None, None, False)
        if not normalized:
            return unknown

        candidates = connection.execute(
            """
            SELECT import_description, description, category_id, subcategory_id, generic
            FROM expenses
            WHERE category_id IS NOT NULL
                AND subcategory_id IS NOT NULL
                AND (
                    (import_description IS NOT NULL AND length(trim(import_description)) > 0)
                    OR generic = 1
                )
            ORDER BY expense_date DESC, id DESC
            """
        ).fetchall()
        candidate_descriptions = [
            normalize_text(row["import_description"] or row["description"])
            for row in candidates
        ]

        generic_exact_index = next(
            (
                index
                for index, row in enumerate(candidates)
                if row["generic"] and candidate_descriptions[index] == normalized
            ),
            None,
        )
        if generic_exact_index is not None:
            generic_exact = candidates[generic_exact_index]
            return ImportClassification(
                classification="similar",
                status="pending",
                user_description=generic_exact["description"],
                category_id=generic_exact["category_id"],
                subcategory_id=generic_exact["subcategory_id"],
                create_expense=False,
                similarity=100.0,
                generic=True,
            )

        exact_index = next(
            (
                index
                for index, row in enumerate(candidates)
                if row["import_description"]
                and not row["generic"]
                and candidate_descriptions[index] == normalized
            ),
            None,
        )
        if exact_index is not None:
            exact = candidates[exact_index]
            return ImportClassification(
                classification="identical",
                status="accepted",
                user_description=exact["description"],
                category_id=exact["category_id"],
                subcategory_id=exact["subcategory_id"],
                create_expense=True,
                similarity=100.0,
                generic=False,
            )
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
            generic=bool(matched_row["generic"]),
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
        if "generic" not in expense_columns:
            connection.execute(
                "ALTER TABLE expenses ADD COLUMN generic INTEGER NOT NULL DEFAULT 0 "
                "CHECK (generic IN (0, 1))"
            )

        import_items_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'import_items'"
        ).fetchone()
        import_items_schema = import_items_row["sql"]
        import_item_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(import_items)")
        }
        has_user_description = "user_description" in import_item_columns
        has_generic = "generic" in import_item_columns
        has_classification_check = "check (classification in" in import_items_schema.lower()
        if not has_user_description or not has_generic or not has_classification_check:
            user_description_source = "user_description" if has_user_description else "NULL"
            generic_source = "generic" if has_generic else "0"
            connection.execute(
                """
                CREATE TABLE import_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_job_id INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
                    raw_description TEXT NOT NULL,
                    user_description TEXT,
                    normalized_description TEXT,
                    generic INTEGER NOT NULL DEFAULT 0 CHECK (generic IN (0, 1)),
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
                    id, import_job_id, raw_description, user_description,
                    normalized_description, generic,
                    amount, expense_date, category_id, subcategory_id,
                    classification, status
                )
                SELECT
                    id, import_job_id, raw_description, {user_description_source},
                    normalized_description, {generic_source},
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
                    description, expense_date, amount, category_id, subcategory_id, source,
                    generic
                )
                VALUES (?, ?, ?, ?, ?, 'manual', ?)
                """,
                (
                    expense.description,
                    expense.spent_on.isoformat(),
                    int(amount_cents),
                    category_id,
                    subcategory_id,
                    int(expense.generic),
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
            generic=expense.generic,
        )

    def update_expenses(self, expenses: list[Expense]) -> None:
        if not expenses:
            return
        with self.connect() as connection:
            for expense in expenses:
                if expense.id is None:
                    raise ValueError("No se puede actualizar un gasto sin identificador.")
                if not expense.subcategory or not expense.subcategory.strip():
                    raise ValueError("La subcategoria es obligatoria.")
                amount_cents = expense.amount * 100
                if amount_cents != amount_cents.to_integral_value():
                    raise ValueError("El importe no puede tener mas de dos decimales.")

                category_row = connection.execute(
                    "SELECT id FROM categories WHERE name = ? COLLATE NOCASE",
                    (expense.category.strip(),),
                ).fetchone()
                category_id = (
                    category_row["id"]
                    if category_row
                    else connection.execute(
                        "INSERT INTO categories (name) VALUES (?)",
                        (expense.category.strip(),),
                    ).lastrowid
                )
                subcategory_row = connection.execute(
                    """
                    SELECT id FROM subcategories
                    WHERE category_id = ? AND name = ? COLLATE NOCASE
                    """,
                    (category_id, expense.subcategory.strip()),
                ).fetchone()
                subcategory_id = (
                    subcategory_row["id"]
                    if subcategory_row
                    else connection.execute(
                        "INSERT INTO subcategories (category_id, name) VALUES (?, ?)",
                        (category_id, expense.subcategory.strip()),
                    ).lastrowid
                )
                cursor = connection.execute(
                    """
                    UPDATE expenses
                    SET description = ?, expense_date = ?, amount = ?,
                        category_id = ?, subcategory_id = ?, generic = ?
                    WHERE id = ?
                    """,
                    (
                        expense.description.strip(),
                        expense.spent_on.isoformat(),
                        int(amount_cents),
                        category_id,
                        subcategory_id,
                        int(expense.generic),
                        expense.id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"No existe el gasto {expense.id}.")

    def delete_expenses(self, expense_ids: list[int]) -> None:
        unique_ids = list(dict.fromkeys(expense_ids))
        if not unique_ids:
            return
        placeholders = ", ".join("?" for _ in unique_ids)
        with self.connect() as connection:
            connection.execute(
                f"DELETE FROM expenses WHERE id IN ({placeholders})", unique_ids
            )

    def list_all(self) -> list[Expense]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT expenses.id, categories.name AS category, "
                "subcategories.name AS subcategory, "
                "expenses.description, expenses.amount, expenses.expense_date, "
                "expenses.import_job_id, expenses.import_item_id, expenses.generic "
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
                generic=bool(row["generic"]),
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

    def get_total_between_dates(
        self, start_date: date, end_date: date, exclude_investments: bool = False
    ) -> Decimal:
        if end_date < start_date:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        with self.connect() as connection:
            query = (
                "SELECT COALESCE(SUM(amount), 0) AS total "
                "FROM expenses WHERE expense_date BETWEEN ? AND ?"
            )
            params: tuple[object, ...] = (start_date.isoformat(), end_date.isoformat())
            if exclude_investments:
                query += (
                    " AND (categories.name IS NULL OR categories.name <> 'Inversiones')"
                )
                # join needed only when excluding; expenses LEFT JOIN categories already
                # not present, so add it
                query = (
                    "SELECT COALESCE(SUM(expenses.amount), 0) AS total "
                    "FROM expenses "
                    "LEFT JOIN categories ON categories.id = expenses.category_id "
                    "WHERE expenses.expense_date BETWEEN ? AND ? "
                    "AND (categories.name IS NULL OR categories.name <> 'Inversiones')"
                )
            row = connection.execute(query, params).fetchone()
        return Decimal(row["total"]) / 100

    def get_breakdown_between_dates(
        self, start_date: date, end_date: date, exclude_investments: bool = False
    ) -> list[ExpenseBreakdown]:
        if end_date < start_date:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        with self.connect() as connection:
            query = """
                SELECT
                    strftime('%Y-%m', expenses.expense_date) AS month,
                    COALESCE(categories.name, 'Sin categoria') AS category,
                    COALESCE(subcategories.name, 'Sin subcategoria') AS subcategory,
                    SUM(expenses.amount) AS amount
                FROM expenses
                LEFT JOIN categories ON categories.id = expenses.category_id
                LEFT JOIN subcategories ON subcategories.id = expenses.subcategory_id
                WHERE expenses.expense_date BETWEEN ? AND ?
            """
            params: tuple[object, ...] = (start_date.isoformat(), end_date.isoformat())
            if exclude_investments:
                query += (
                    " AND (categories.name IS NULL OR categories.name <> 'Inversiones')"
                )
            query += (
                " GROUP BY month, category, subcategory "
                "ORDER BY month, category COLLATE NOCASE, subcategory COLLATE NOCASE"
            )
            rows = connection.execute(query, params).fetchall()
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
        exclude_investments: bool = False,
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
            if by_category or exclude_investments
            else ""
        )
        category_order = ", category COLLATE NOCASE" if by_category else ""
        query = (
            f"SELECT {period_expression} AS period{category_select}, "
            "SUM(expenses.amount) AS amount "
            "FROM expenses "
            f"{category_join}"
            "WHERE expenses.expense_date BETWEEN ? AND ? "
        )
        params: tuple[object, ...] = (start_date.isoformat(), end_date.isoformat())
        if exclude_investments:
            query += (
                "AND (categories.name IS NULL OR categories.name <> 'Inversiones') "
            )
        query += f"GROUP BY period{category_group} "
        query += f"ORDER BY period{category_order}"
        with self.connect() as connection:
            rows = connection.execute(
                query, params
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
                "expenses.import_job_id, expenses.import_item_id, expenses.generic "
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
                generic=bool(row["generic"]),
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