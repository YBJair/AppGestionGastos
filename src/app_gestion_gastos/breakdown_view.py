from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_gestion_gastos.models import ExpenseBreakdown
from app_gestion_gastos.services import ExpenseService

MONTH_NAMES = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


class ExpenseBreakdownView(QWidget):
    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.period_tabs = QTabWidget()
        year_tab = QWidget()
        self.year_input = QSpinBox()
        self.year_input.setRange(1900, 9999)
        self.year_input.setValue(date.today().year)
        year_layout = QHBoxLayout(year_tab)
        year_layout.addWidget(QLabel("Año"))
        year_layout.addWidget(self.year_input)
        year_layout.addStretch()
        self.period_tabs.addTab(year_tab, "Por año")

        range_tab = QWidget()
        self.start_date_input = QDateEdit(QDate.currentDate().addDays(-30))
        self.end_date_input = QDateEdit(QDate.currentDate())
        for date_input in (self.start_date_input, self.end_date_input):
            date_input.setCalendarPopup(True)
            date_input.setDisplayFormat("yyyy-MM-dd")
        range_layout = QHBoxLayout(range_tab)
        range_layout.addWidget(QLabel("Desde"))
        range_layout.addWidget(self.start_date_input)
        range_layout.addWidget(QLabel("Hasta"))
        range_layout.addWidget(self.end_date_input)
        range_layout.addStretch()
        self.period_tabs.addTab(range_tab, "Entre fechas")

        self.generate_button = QPushButton("Generar desglose")
        self.generate_button.clicked.connect(self._generate)
        self.period_tabs.currentChanged.connect(self._generate)
        self.year_input.valueChanged.connect(self._generate)
        self.start_date_input.dateChanged.connect(self._generate)
        self.end_date_input.dateChanged.connect(self._generate)
        self.results_tree = QTreeWidget()
        self.results_tree.setColumnCount(2)
        self.results_tree.setHeaderLabels(["Mes / categoría / subcategoría", "Suma de importe"])
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.header().setStretchLastSection(False)
        self.results_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.total_label = QLabel("Total: 0,00 €")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(self.period_tabs)
        layout.addWidget(self.generate_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.results_tree, 1)
        layout.addWidget(self.total_label)
        self._generate()

    def _generate(self) -> None:
        if self.period_tabs.currentIndex() == 0:
            year = self.year_input.value()
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
        else:
            start_date = self.start_date_input.date().toPython()
            end_date = self.end_date_input.date().toPython()
            if end_date < start_date:
                QMessageBox.warning(self, "Rango no valido", "La fecha final debe ser posterior.")
                return

        entries = self._service.get_breakdown_between_dates(start_date, end_date)
        self._render_entries(entries)
        total = self._service.get_total_between_dates(start_date, end_date)
        self.total_label.setText(f"Total: {self._format_amount(total)}")

    def _render_entries(self, entries: list[ExpenseBreakdown]) -> None:
        self.results_tree.clear()
        month_items: dict[str, QTreeWidgetItem] = {}
        category_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        month_totals: dict[str, Decimal] = {}
        category_totals: dict[tuple[str, str], Decimal] = {}

        for entry in entries:
            month_name = MONTH_NAMES[int(entry.month[5:7]) - 1]
            month_label = f"{month_name} {entry.month[:4]}"
            if entry.month not in month_items:
                month_items[entry.month] = QTreeWidgetItem([month_label, ""])
                self.results_tree.addTopLevelItem(month_items[entry.month])

            category_key = (entry.month, entry.category)
            if category_key not in category_items:
                category_items[category_key] = QTreeWidgetItem([entry.category, ""])
                month_items[entry.month].addChild(category_items[category_key])

            category_items[category_key].addChild(
                QTreeWidgetItem([entry.subcategory, self._format_amount(entry.amount)])
            )
            month_totals[entry.month] = month_totals.get(entry.month, Decimal("0")) + entry.amount
            category_totals[category_key] = (
                category_totals.get(category_key, Decimal("0")) + entry.amount
            )

        for month, item in month_items.items():
            item.setText(1, self._format_amount(month_totals[month]))
            item.setExpanded(False)
        for key, item in category_items.items():
            item.setText(1, self._format_amount(category_totals[key]))
            item.setExpanded(True)

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        formatted = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{formatted} €"