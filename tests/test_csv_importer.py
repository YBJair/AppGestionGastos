from datetime import date

import pytest

from app_gestion_gastos.csv_importer import CsvImportError, parse_expense_csv


def test_parse_cp1252_crlf_csv_with_european_amounts_and_blank_trailing_rows(tmp_path) -> None:
    path = tmp_path / "cargas.csv"
    content = (
        "fecha;categoría;subcategoría;importe;nota\r\n"
        "03/02/2026;Hogar;Cocina;1.234,56 €;Compra de café – reposición\r\n"
        '04/02/2026;Hogar;Cocina; 160,17 € ;"Compra; productos básicos"\r\n'
        ";;;;\r\n"
        "\r\n"
    )
    path.write_bytes(content.encode("cp1252"))

    rows = parse_expense_csv(path)

    assert len(rows) == 2
    assert rows[0].expense_date == date(2026, 2, 3)
    assert rows[0].amount_cents == 123456
    assert rows[0].note == "Compra de café – reposición"
    assert rows[0].normalized_note == "compra de cafe reposicion"
    assert rows[1].amount_cents == 16017
    assert rows[1].note == "Compra; productos básicos"
    assert rows[1].normalized_note == "compra productos basicos"


def test_parse_export_with_trailing_empty_columns_in_header_and_rows(tmp_path) -> None:
    path = tmp_path / "excel-export.csv"
    content = (
        "fecha;categoría;subcategoría;importe;nota;;;;;;;;;;;;;;;;;;;;;;\r\n"
        "01/01/2026;Impuestos;Renta; 160,17 € ;Ejercicio renta 2025;;;;;;;;;;;;;;;;;;;;;;\r\n"
        ";;;;;;;;;;;;;;;;;;;;;;;;;\r\n"
    )
    path.write_bytes(content.encode("cp1252"))

    rows = parse_expense_csv(path)

    assert len(rows) == 1
    assert rows[0].category == "Impuestos"
    assert rows[0].subcategory == "Renta"
    assert rows[0].amount_cents == 16017
    assert rows[0].note == "Ejercicio renta 2025"


def test_parse_utf8_bom_and_reject_invalid_row(tmp_path) -> None:
    path = tmp_path / "utf8.csv"
    path.write_bytes(
        "\ufefffecha;categoría;subcategoría;importe;nota\r\n"
        "31/12/2025;Hogar;Agua;12,00 €;Factura de agua\r\n".encode("utf-8-sig")
    )

    rows = parse_expense_csv(path)

    assert rows[0].expense_date == date(2025, 12, 31)
    assert rows[0].amount_cents == 1200

    path.write_bytes(
        "fecha;categoría;subcategoría;importe;nota\r\n"
        "31-12-2025;Hogar;Agua;12,00 €;Factura de agua\r\n".encode("cp1252")
    )
    with pytest.raises(CsvImportError, match="Fila 2: fecha no válida"):
        parse_expense_csv(path)


def test_reject_non_empty_extra_column(tmp_path) -> None:
    path = tmp_path / "extra-column.csv"
    path.write_bytes(
        (
            "fecha;categoría;subcategoría;importe;nota\r\n"
            "31/12/2025;Hogar;Agua;12,00 €;Factura;dato inesperado\r\n"
        ).encode("cp1252")
    )

    with pytest.raises(CsvImportError, match="Fila 2: número de columnas no válido"):
        parse_expense_csv(path)