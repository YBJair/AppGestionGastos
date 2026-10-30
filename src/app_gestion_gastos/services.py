from datetime import date
from decimal import Decimal
from typing import Protocol

from app_gestion_gastos.models import Expense


class ExpenseRepository(Protocol):
    def add(self, expense: Expense) -> Expense: ...

    def list_all(self) -> list[Expense]: ...

    def list_categories(self) -> list[str]: ...

    def list_subcategories(self, category: str) -> list[str]: ...


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