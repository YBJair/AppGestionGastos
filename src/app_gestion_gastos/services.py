from datetime import date
from decimal import Decimal
from typing import Literal, Protocol

from app_gestion_gastos.csv_importer import parse_expense_csv
from app_gestion_gastos.models import (
    ChartData,
    Expense,
    ExpenseBreakdown,
    ExpenseSuggestion,
    ImportClassification,
    ImportJobSummary,
    ImportProcessingResult,
    ParsedCsvExpense,
    ParsedPdfTransaction,
    PendingImportItemSummary,
)


class ExpenseRepository(Protocol):
    def add(self, expense: Expense) -> Expense: ...

    def update_expenses(self, expenses: list[Expense]) -> None: ...

    def delete_expenses(self, expense_ids: list[int]) -> None: ...

    def list_all(self) -> list[Expense]: ...

    def list_categories(self) -> list[str]: ...

    def list_subcategories(self, category: str) -> list[str]: ...

    def list_expense_descriptions(self) -> list[str]: ...

    def list_expense_suggestions(self) -> list[ExpenseSuggestion]: ...

    def classify_import_description(
        self, normalized_description: str
    ) -> ImportClassification: ...

    def add_import_item(
        self,
        import_job_id: int,
        raw_description: str,
        amount: Decimal,
        expense_date: date,
    ) -> ImportProcessingResult: ...

    def import_csv_expenses(
        self, filename: str, rows: list[ParsedCsvExpense]
    ) -> tuple[int, int]: ...

    def import_pdf_expenses(
        self, filename: str, rows: list[ParsedPdfTransaction]
    ) -> tuple[int, int]: ...

    def accept_import_item(self, import_item_id: int) -> None: ...

    def accept_import_item_with_data(
        self,
        import_item_id: int,
        user_description: str,
        category: str,
        subcategory: str,
        generic: bool = False,
    ) -> None: ...

    def list_import_jobs(self) -> list[ImportJobSummary]: ...

    def list_pending_import_items(
        self, classification: Literal["similar", "unknown"]
    ) -> list[PendingImportItemSummary]: ...

    def get_expenses_for_month(self, year: int, month: int) -> list[Expense]: ...

    def get_expenses_for_month_and_category(
        self, year: int, month: int, category_id: int
    ) -> list[Expense]: ...

    def get_expenses_for_month_and_subcategory(
        self, year: int, month: int, subcategory_id: int
    ) -> list[Expense]: ...

    def get_expenses_for_week(self, year: int, week: int) -> list[Expense]: ...

    def get_expenses_for_week_and_category(
        self, year: int, week: int, category_id: int
    ) -> list[Expense]: ...

    def get_total_between_dates(self, start_date: date, end_date: date) -> Decimal: ...

    def get_breakdown_between_dates(
        self, start_date: date, end_date: date
    ) -> list[ExpenseBreakdown]: ...

    def get_chart_data(
        self,
        start_date: date,
        end_date: date,
        period_unit: Literal["month", "week"],
        by_category: bool,
    ) -> list[ChartData]: ...


class ExpenseService:
    def __init__(self, repository: ExpenseRepository) -> None:
        self._repository = repository

    def register_expense(
        self,
        *,
        category: str,
        description: str,
        amount: Decimal,
        spent_on: date,
        subcategory: str,
    ) -> Expense:
        subcategory = subcategory.strip()
        if not subcategory:
            raise ValueError("La subcategoria es obligatoria.")
        expense = Expense(
            category=category.strip(),
            description=description.strip(),
            amount=amount,
            spent_on=spent_on,
            subcategory=subcategory,
        )
        return self._repository.add(expense)

    def list_expenses(self) -> list[Expense]:
        return self._repository.list_all()

    def update_expenses(self, expenses: list[Expense]) -> None:
        self._repository.update_expenses(expenses)

    def delete_expenses(self, expense_ids: list[int]) -> None:
        self._repository.delete_expenses(expense_ids)

    def list_categories(self) -> list[str]:
        return self._repository.list_categories()

    def list_subcategories(self, category: str) -> list[str]:
        if not category.strip():
            return []
        return self._repository.list_subcategories(category.strip())

    def list_expense_descriptions(self) -> list[str]:
        return self._repository.list_expense_descriptions()

    def list_expense_suggestions(self) -> list[ExpenseSuggestion]:
        return self._repository.list_expense_suggestions()

    def classify_import_description(self, normalized_description: str) -> ImportClassification:
        return self._repository.classify_import_description(normalized_description)

    def add_import_item(
        self,
        import_job_id: int,
        raw_description: str,
        amount: Decimal,
        expense_date: date,
    ) -> ImportProcessingResult:
        return self._repository.add_import_item(
            import_job_id, raw_description, amount, expense_date
        )

    def import_csv_file(self, filename: str) -> tuple[int, int]:
        rows = parse_expense_csv(filename)
        if not rows:
            raise ValueError("El CSV no contiene filas de gastos.")
        return self._repository.import_csv_expenses(filename, rows)

    def import_pdf_file(self, filename: str) -> tuple[int, int]:
        from app_gestion_gastos.pdf_importer import parse_bank_statement_pdf

        rows = parse_bank_statement_pdf(filename)
        return self._repository.import_pdf_expenses(filename, rows)

    def accept_import_item(self, import_item_id: int) -> None:
        self._repository.accept_import_item(import_item_id)

    def accept_import_item_with_data(
        self,
        import_item_id: int,
        user_description: str,
        category: str,
        subcategory: str,
        generic: bool = False,
    ) -> None:
        self._repository.accept_import_item_with_data(
            import_item_id, user_description, category, subcategory, generic
        )

    def list_import_jobs(self) -> list[ImportJobSummary]:
        return self._repository.list_import_jobs()

    def list_pending_import_items(
        self, classification: Literal["similar", "unknown"]
    ) -> list[PendingImportItemSummary]:
        return self._repository.list_pending_import_items(classification)

    def get_expenses_for_month(self, year: int, month: int) -> list[Expense]:
        return self._repository.get_expenses_for_month(year, month)

    def get_expenses_for_month_and_category(
        self, year: int, month: int, category_id: int
    ) -> list[Expense]:
        return self._repository.get_expenses_for_month_and_category(year, month, category_id)

    def get_expenses_for_month_and_subcategory(
        self, year: int, month: int, subcategory_id: int
    ) -> list[Expense]:
        return self._repository.get_expenses_for_month_and_subcategory(
            year, month, subcategory_id
        )

    def get_expenses_for_week(self, year: int, week: int) -> list[Expense]:
        return self._repository.get_expenses_for_week(year, week)

    def get_expenses_for_week_and_category(
        self, year: int, week: int, category_id: int
    ) -> list[Expense]:
        return self._repository.get_expenses_for_week_and_category(year, week, category_id)

    def get_total_between_dates(self, start_date: date, end_date: date) -> Decimal:
        return self._repository.get_total_between_dates(start_date, end_date)

    def get_breakdown_between_dates(
        self, start_date: date, end_date: date
    ) -> list[ExpenseBreakdown]:
        return self._repository.get_breakdown_between_dates(start_date, end_date)

    def get_chart_data(
        self,
        start_date: date,
        end_date: date,
        period_unit: Literal["month", "week"],
        by_category: bool,
    ) -> list[ChartData]:
        return self._repository.get_chart_data(start_date, end_date, period_unit, by_category)