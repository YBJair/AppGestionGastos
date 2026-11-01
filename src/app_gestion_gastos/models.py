from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class Expense:
    category: str
    description: str
    amount: Decimal
    spent_on: date
    id: int | None = None
    subcategory: str | None = None
    import_job_id: int | None = None
    import_item_id: int | None = None

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("La categoria es obligatoria.")
        if self.subcategory is not None and not self.subcategory.strip():
            raise ValueError("La subcategoria no puede estar vacia.")
        if not self.description.strip():
            raise ValueError("La descripcion es obligatoria.")
        if not self.amount.is_finite() or self.amount <= 0:
            raise ValueError("El importe debe ser mayor que cero.")
        amount_cents = self.amount * 100
        if amount_cents != amount_cents.to_integral_value():
            raise ValueError("El importe no puede tener mas de dos decimales.")


@dataclass(frozen=True, slots=True)
class ExpenseBreakdown:
    month: str
    category: str
    subcategory: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ChartData:
    period: str
    category: str | None
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ExpenseSuggestion:
    description: str
    category: str | None
    subcategory: str | None


@dataclass(frozen=True, slots=True)
class ImportClassification:
    classification: Literal["identical", "similar", "unknown"]
    status: Literal["pending", "accepted"]
    user_description: str | None
    category_id: int | None
    subcategory_id: int | None
    create_expense: bool
    similarity: float | None = None


@dataclass(frozen=True, slots=True)
class ImportProcessingResult:
    import_item_id: int
    classification: ImportClassification
    expense_id: int | None


@dataclass(frozen=True, slots=True)
class ImportJobSummary:
    filename: str | None
    source_type: str
    imported_at: str
    status: str


@dataclass(frozen=True, slots=True)
class PendingImportItemSummary:
    raw_description: str
    user_description: str | None
    amount: Decimal
    category: str | None
    subcategory: str | None
    expense_date: date