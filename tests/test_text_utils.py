import pytest

from app_gestion_gastos.text_utils import normalize_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  CAFÉ\t- SUPERmercado,  24/7! ", "cafe supermercado 24 7"),
        ("Niño & Año 2026", "nino ano 2026"),
        ("", ""),
    ],
)
def test_normalize_text(value: str, expected: str) -> None:
    assert normalize_text(value) == expected


def test_normalize_text_is_idempotent() -> None:
    normalized = normalize_text(" Café   del Hogar! ")

    assert normalize_text(normalized) == normalized