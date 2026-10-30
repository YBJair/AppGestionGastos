from datetime import date
from decimal import Decimal
from typing import Protocol

from app_gestion_gastos.models import Expense, ExpenseBreakdown


class ExpenseRepository(Protocol):
    def add(self, expense: Expense) -> Expense: ...

    def list_all(self) -> list[Expense]: ...

    def list_categories(self) -> list[str]: ...

    def list_subcategories(self, category: str) -> list[str]: ...

    def get_expenses_for_month(self, year: int, month: int) -> list[Expense]: ...

    def get_expenses_for_month_and_category(
        self, year: int, month: int, category_id: int
    ) -> list[Expense]: ...

    def get_expenses_for_month_and_subcategory(
        self, year: int, month: int, subcategory_id: int
    ) -> list[Expense]: ...

    def get_total_between_dates(self, start_date: date, end_date: date) -> Decimal: ...

    def get_breakdown_between_dates(
        self, start_date: date, end_date: date
    ) -> list[ExpenseBreakdown]: ...


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

    def list_categories(self) -> list[str]:
        return self._repository.list_categories()

    def list_subcategories(self, category: str) -> list[str]:
        if not category.strip():
            return []
        return self._repository.list_subcategories(category.strip())

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

    def get_total_between_dates(self, start_date: date, end_date: date) -> Decimal:
        return self._repository.get_total_between_dates(start_date, end_date)

    def get_breakdown_between_dates(
        self, start_date: date, end_date: date
    ) -> list[ExpenseBreakdown]:
        return self._repository.get_breakdown_between_dates(start_date, end_date)