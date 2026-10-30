from datetime import date
from decimal import Decimal

import pytest

from app_gestion_gastos.models import Expense
from app_gestion_gastos.services import ExpenseService


class InMemoryExpenseRepository:
    def __init__(self) -> None:
        self.expenses: list[Expense] = []

    def add(self, expense: Expense) -> Expense:
        saved = Expense(
            id=len(self.expenses) + 1,
            category=expense.category,
            description=expense.description,
            amount=expense.amount,
            spent_on=expense.spent_on,
            subcategory=expense.subcategory,
        )
        self.expenses.append(saved)
        return saved

    def list_all(self) -> list[Expense]:
        return list(self.expenses)

    def list_categories(self) -> list[str]:
        return sorted({expense.category for expense in self.expenses})

    def list_subcategories(self, category: str) -> list[str]:
        return sorted(
            {
                expense.subcategory
                for expense in self.expenses
                if expense.category == category and expense.subcategory is not None
            }
        )


def test_register_expense_normalizes_text_and_returns_saved_expense() -> None:
    service = ExpenseService(InMemoryExpenseRepository())

    expense = service.register_expense(
        category="  Alimentacion ",
        description=" Compra semanal  ",
        amount=Decimal("24.50"),
        spent_on=date(2026, 10, 30),
        subcategory="  Supermercado  ",
    )

    assert expense.id == 1
    assert expense.category == "Alimentacion"
    assert expense.description == "Compra semanal"
    assert expense.amount == Decimal("24.50")
    assert expense.subcategory == "Supermercado"


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
def test_register_expense_rejects_non_positive_amount(amount: Decimal) -> None:
    service = ExpenseService(InMemoryExpenseRepository())

    with pytest.raises(ValueError, match="mayor que cero"):
        service.register_expense(
            category="Transporte",
            description="Billete",
            amount=amount,
            spent_on=date(2026, 10, 30),
            subcategory="Bus",
        )


def test_register_expense_requires_subcategory() -> None:
    service = ExpenseService(InMemoryExpenseRepository())

    with pytest.raises(ValueError, match="subcategoria es obligatoria"):
        service.register_expense(
            category="Transporte",
            description="Billete",
            amount=Decimal("2.50"),
            spent_on=date(2026, 10, 30),
            subcategory=" ",
        )

    def get_expenses_for_month(self, year: int, month: int) -> list[Expense]:
        return []

    def get_expenses_for_month_and_category(
        self, year: int, month: int, category_id: int
    ) -> list[Expense]:
        return []

    def get_expenses_for_month_and_subcategory(
        self, year: int, month: int, subcategory_id: int
    ) -> list[Expense]:
        return []

    def get_total_between_dates(self, start_date: date, end_date: date) -> Decimal:
        return Decimal("0")

    def get_breakdown_between_dates(self, start_date: date, end_date: date) -> list:
        return []