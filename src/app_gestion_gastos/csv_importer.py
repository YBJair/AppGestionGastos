import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app_gestion_gastos.models import ParsedCsvExpense
from app_gestion_gastos.text_utils import normalize_text

EXPECTED_HEADERS = ("fecha", "categoría", "subcategoría", "importe", "nota")
EURO_AMOUNT_PATTERN = re.compile(r"(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,2})?")


class CsvImportError(ValueError):
    pass


def parse_expense_csv(path: str | Path) -> list[ParsedCsvExpense]:
    csv_path = Path(path)
    content = csv_path.read_bytes()
    decoded = _decode_content(content, csv_path)
    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=";")
    raw_headers = next(reader, None)
    if raw_headers is None:
        raise CsvImportError("El fichero CSV está vacío o no tiene cabecera.")

    headers = [header.strip().lstrip("\ufeff") for header in raw_headers]
    while headers and not headers[-1]:
        headers.pop()
    if tuple(headers) != EXPECTED_HEADERS:
        expected = ";".join(EXPECTED_HEADERS)
        raise CsvImportError(f"Cabecera no válida. Se esperaba: {expected}.")

    parsed_rows = []
    for row in reader:
        if not row or all(not value.strip() for value in row):
            continue
        line_number = reader.line_num
        if len(row) > len(EXPECTED_HEADERS):
            if any(value.strip() for value in row[len(EXPECTED_HEADERS) :]):
                raise CsvImportError(f"Fila {line_number}: número de columnas no válido.")
            row = row[: len(EXPECTED_HEADERS)]
        elif len(row) < len(EXPECTED_HEADERS):
            raise CsvImportError(f"Fila {line_number}: número de columnas no válido.")
        fields = dict(zip(EXPECTED_HEADERS, row, strict=True))

        raw_date = fields["fecha"].strip()
        try:
            expense_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
        except ValueError as error:
            raise CsvImportError(
                f"Fila {line_number}: fecha no válida '{raw_date}', se esperaba dd/mm/yyyy."
            ) from error
        if expense_date.strftime("%d/%m/%Y") != raw_date:
            raise CsvImportError(
                f"Fila {line_number}: fecha no válida '{raw_date}', se esperaba dd/mm/yyyy."
            )

        category = fields["categoría"].strip()
        subcategory = fields["subcategoría"].strip()
        note = fields["nota"]
        if not category or not subcategory:
            raise CsvImportError(f"Fila {line_number}: categoría y subcategoría son obligatorias.")
        if not note.strip():
            raise CsvImportError(f"Fila {line_number}: la nota no puede estar vacía.")

        amount_cents = _parse_amount(fields["importe"], line_number)
        normalized_note = normalize_text(note)
        if not normalized_note:
            raise CsvImportError(f"Fila {line_number}: la nota no produce una descripción válida.")
        parsed_rows.append(
            ParsedCsvExpense(
                expense_date=expense_date,
                category=category,
                subcategory=subcategory,
                amount_cents=amount_cents,
                note=note,
                normalized_note=normalized_note,
            )
        )
    return parsed_rows


def _decode_content(content: bytes, path: Path) -> str:
    encodings = ("utf-8-sig", "cp1252", "latin-1") if content.startswith(b"\xef\xbb\xbf") else (
        "cp1252",
        "utf-8-sig",
        "latin-1",
    )
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CsvImportError(f"No se pudo decodificar el fichero {path.name}.")


def _parse_amount(value: str, line_number: int) -> int:
    compact = "".join(character for character in value if not character.isspace())
    compact = compact.replace("€", "")
    if not EURO_AMOUNT_PATTERN.fullmatch(compact):
        raise CsvImportError(
            f"Fila {line_number}: importe no válido '{value}', se esperaba formato europeo."
        )
    try:
        amount = Decimal(compact.replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise CsvImportError(f"Fila {line_number}: importe no válido '{value}'.") from error
    if amount <= 0:
        raise CsvImportError(f"Fila {line_number}: el importe debe ser mayor que cero.")
    return int(amount * 100)