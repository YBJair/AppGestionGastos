from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Expense:
    category: str
    description: str
    amount: Decimal
    spent_on: date
    id: int | None = None
    subcategory: str | None = None

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