import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from app_gestion_gastos.models import ParsedPdfTransaction
from app_gestion_gastos.text_utils import normalize_text

MONTHS = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}
AMOUNT_PATTERN = re.compile(r"\d[\d.]*,\d{2}")
DAY_PATTERN = re.compile(r"\d{1,2}")
YEAR_PATTERN = re.compile(r"20\d{2}")


class PdfImportError(ValueError):
    pass


def parse_bank_statement_pdf(path: str | Path) -> list[ParsedPdfTransaction]:
    pdf_path = Path(path)
    transactions = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                transactions.extend(_parse_page(page, page_number))
    except (OSError, ValueError) as error:
        if isinstance(error, PdfImportError):
            raise
        raise PdfImportError(f"No se pudo leer el PDF {pdf_path.name}: {error}") from error
    if not transactions:
        raise PdfImportError("El PDF no contiene salidas de dinero en Transacciones de cuenta.")
    return transactions


def _parse_page(page, page_number: int) -> list[ParsedPdfTransaction]:
    words = page.extract_words(x_tolerance=1, y_tolerance=2)
    date_headers = [
        word
        for word in words
        if normalize_text(word["text"]) == "fecha" and word["x0"] < 120
    ]
    if not date_headers:
        return []
    date_header = date_headers[-1]
    header_top = date_header["top"]

    entry_header = _nearest_header(words, "entrada", header_top)
    outgoing_header = _nearest_header(words, "salida", header_top)
    balance_header = _nearest_header(words, "balance", header_top, min_x=450)
    description_header = _nearest_header(words, "descripcion", header_top)
    if not all((entry_header, outgoing_header, balance_header, description_header)):
        raise PdfImportError(f"Página {page_number}: no se reconocieron las columnas.")

    section_end = min(
        [
            word["top"]
            for word in words
            if normalize_text(word["text"]) == "resumen" and word["top"] > header_top + 10
        ]
        + [
            word["top"]
            for word in words
            if word["text"].casefold() == "trade"
            and word["x0"] < 110
            and word["top"] > header_top + 10
        ]
        + [page.height]
    )
    date_x_max = date_header["x1"] + 10
    anchors = [
        word
        for word in words
        if word["x0"] <= date_x_max
        and word["top"] > header_top + 10
        and word["top"] < section_end
        and DAY_PATTERN.fullmatch(word["text"])
    ]
    anchors.sort(key=lambda word: word["top"])

    parsed = []
    for row_index, anchor in enumerate(anchors):
        row_start = anchor["top"] - 1
        later_anchors = [word["top"] for word in anchors[row_index + 1 :]]
        row_end = min(later_anchors or [section_end])
        row_words = [word for word in words if row_start <= word["top"] < row_end]

        amount_words = [
            word
            for word in row_words
            if outgoing_header["x0"] - 20 <= word["x0"] < balance_header["x0"] - 20
            and AMOUNT_PATTERN.fullmatch(word["text"])
        ]
        if not amount_words:
            continue
        if len(amount_words) != 1:
            raise PdfImportError(
                f"Página {page_number}, fila {row_index + 1}: hay más de una salida de dinero."
            )

        expense_date = _parse_row_date(row_words, anchor, date_x_max, page_number, row_index)
        description_words = [
            word
            for word in row_words
            if description_header["x0"] - 4 <= word["x0"] < entry_header["x0"] - 4
        ]
        description = " ".join(
            word["text"]
            for word in sorted(description_words, key=lambda word: (word["top"], word["x0"]))
        ).strip()
        if not description:
            raise PdfImportError(
                f"Página {page_number}, fila {row_index + 1}: falta la descripción del cargo."
            )
        amount_cents = _parse_amount(amount_words[0]["text"], page_number, row_index)
        parsed.append(
            ParsedPdfTransaction(
                expense_date=expense_date,
                description=description,
                amount_cents=amount_cents,
            )
        )
    return parsed


def _nearest_header(words, label: str, top: float, min_x: float = 0):
    candidates = [
        word
        for word in words
        if normalize_text(word["text"]) == label
        and word["x0"] >= min_x
        and abs(word["top"] - top) <= 12
    ]
    return min(candidates, key=lambda word: abs(word["top"] - top), default=None)


def _parse_row_date(words, anchor, date_x_max: float, page_number: int, row_index: int) -> date:
    row_date_words = [
        word
        for word in words
        if word["x0"] <= date_x_max and anchor["top"] - 1 <= word["top"] <= anchor["top"] + 25
    ]
    month = next(
        (
            MONTHS[normalize_text(word["text"])]
            for word in row_date_words
            if normalize_text(word["text"]) in MONTHS
        ),
        None,
    )
    year = next(
        (int(word["text"]) for word in row_date_words if YEAR_PATTERN.fullmatch(word["text"])),
        None,
    )
    if month is None or year is None:
        raise PdfImportError(
            f"Página {page_number}, fila {row_index + 1}: no se pudo leer la fecha."
        )
    try:
        return date(year, month, int(anchor["text"]))
    except ValueError as error:
        raise PdfImportError(
            f"Página {page_number}, fila {row_index + 1}: fecha no válida."
        ) from error


def _parse_amount(value: str, page_number: int, row_index: int) -> int:
    try:
        amount = Decimal(value.replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise PdfImportError(
            f"Página {page_number}, fila {row_index + 1}: importe no válido."
        ) from error
    if not amount.is_finite() or amount <= 0:
        raise PdfImportError(f"Página {page_number}, fila {row_index + 1}: importe no válido.")
    return int(amount * 100)