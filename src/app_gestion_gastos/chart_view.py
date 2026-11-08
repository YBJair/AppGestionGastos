from calendar import monthrange
from datetime import date
from decimal import Decimal

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_gestion_gastos.services import ExpenseService

MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
HOVER_PADDING_PIXELS = 18


class ExpenseChartView(QWidget):
    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.scope_tabs = QTabWidget()

        year_tab = QWidget()
        self.year_input = QSpinBox()
        self.year_input.setRange(1900, 9999)
        self.year_input.setValue(date.today().year)
        year_layout = QHBoxLayout(year_tab)
        year_layout.addWidget(QLabel("Año"))
        year_layout.addWidget(self.year_input)
        year_layout.addStretch()
        self.scope_tabs.addTab(year_tab, "Por año")

        month_tab = QWidget()
        self.month_year_input = QSpinBox()
        self.month_year_input.setRange(1900, 9999)
        self.month_year_input.setValue(date.today().year)
        self.month_input = QComboBox()
        self.month_input.addItems(MONTH_NAMES)
        self.month_input.setCurrentIndex(date.today().month - 1)
        month_layout = QHBoxLayout(month_tab)
        month_layout.addWidget(QLabel("Mes"))
        month_layout.addWidget(self.month_input)
        month_layout.addWidget(QLabel("Año"))
        month_layout.addWidget(self.month_year_input)
        self.month_weekly_check = QCheckBox("Por semanas")
        self.month_weekly_check.setChecked(True)
        month_layout.addWidget(self.month_weekly_check)
        month_layout.addStretch()
        self.scope_tabs.addTab(month_tab, "Por mes")

        date_tab = QWidget()
        self.start_date_input = QDateEdit(QDate.currentDate().addDays(-30))
        self.end_date_input = QDateEdit(QDate.currentDate())
        for date_input in (self.start_date_input, self.end_date_input):
            date_input.setCalendarPopup(True)
            date_input.setDisplayFormat("yyyy-MM-dd")
        date_layout = QHBoxLayout(date_tab)
        date_layout.addWidget(QLabel("Desde"))
        date_layout.addWidget(self.start_date_input)
        date_layout.addWidget(QLabel("Hasta"))
        date_layout.addWidget(self.end_date_input)
        date_layout.addWidget(QLabel("Precisión"))
        self.week_precision = QRadioButton("Por semana")
        self.month_precision = QRadioButton("Por mes")
        self.precision_group = QButtonGroup(self)
        self.precision_group.setExclusive(True)
        self.precision_group.addButton(self.week_precision)
        self.precision_group.addButton(self.month_precision)
        date_layout.addWidget(self.week_precision)
        date_layout.addWidget(self.month_precision)
        date_layout.addStretch()
        self.scope_tabs.addTab(date_tab, "Entre fechas")
        self._updating_precision = False
        self._set_default_precision()

        self.categories_check = QCheckBox("Por categorías")
        self.totals_check = QCheckBox("Totales por período")
        self.chart_mode_group = QButtonGroup(self)
        self.chart_mode_group.setExclusive(True)
        self.chart_mode_group.addButton(self.categories_check)
        self.chart_mode_group.addButton(self.totals_check)
        self.totals_check.setChecked(True)

        self.generate_button = QPushButton("Generar gráfico")
        self.generate_button.clicked.connect(self._generate)
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(9, 5), tight_layout=True))
        self.axes = self.canvas.figure.add_subplot(111)
        self._bar_artists = []
        self._hover_bar = None
        self._hover_style = None
        self._hover_annotation = None
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        self.scope_tabs.currentChanged.connect(self._scope_changed)
        self.year_input.valueChanged.connect(self._generate)
        self.month_year_input.valueChanged.connect(self._generate)
        self.month_input.currentIndexChanged.connect(self._generate)
        self.month_weekly_check.toggled.connect(self._generate)
        self.start_date_input.dateChanged.connect(self._range_dates_changed)
        self.end_date_input.dateChanged.connect(self._range_dates_changed)
        self.week_precision.toggled.connect(self._precision_toggled)
        self.month_precision.toggled.connect(self._precision_toggled)
        self.categories_check.toggled.connect(self._chart_mode_toggled)
        self.totals_check.toggled.connect(self._chart_mode_toggled)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self.categories_check)
        options_layout.addWidget(self.totals_check)
        options_layout.addStretch()
        options_layout.addWidget(self.generate_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.scope_tabs)
        layout.addLayout(options_layout)
        layout.addWidget(self.canvas, 1)
        self._generate()

    def refresh(self) -> None:
        self._generate()

    def _generate(self) -> None:
        selection = self._selected_period()
        if selection is None:
            return
        start_date, end_date, period_unit = selection
        chart_data = self._service.get_chart_data(
            start_date,
            end_date,
            period_unit,
            self.categories_check.isChecked(),
        )
        self._draw_chart(chart_data, period_unit)

    def _selected_period(self) -> tuple[date, date, str] | None:
        selected_tab = self.scope_tabs.currentIndex()
        if selected_tab == 0:
            year = self.year_input.value()
            return date(year, 1, 1), date(year, 12, 31), "month"
        if selected_tab == 1:
            year = self.month_year_input.value()
            month = self.month_input.currentIndex() + 1
            start_date = date(year, month, 1)
            end_date = date(year, month, monthrange(year, month)[1])
            period_unit = "week" if self.month_weekly_check.isChecked() else "month"
            return start_date, end_date, period_unit

        start_date = self.start_date_input.date().toPython()
        end_date = self.end_date_input.date().toPython()
        if end_date < start_date:
            QMessageBox.warning(self, "Rango no válido", "La fecha final debe ser posterior.")
            return None
        period_unit = "week" if self.week_precision.isChecked() else "month"
        return start_date, end_date, period_unit

    def _scope_changed(self, index: int) -> None:
        if index == 2:
            self._set_default_precision()
        self._generate()

    def _range_dates_changed(self) -> None:
        self._set_default_precision()
        if self.scope_tabs.currentIndex() == 2:
            self._generate()

    def _set_default_precision(self) -> None:
        start_date = self.start_date_input.date().toPython()
        end_date = self.end_date_input.date().toPython()
        use_weeks = end_date <= self._one_month_after(start_date)
        target = self.week_precision if use_weeks else self.month_precision
        self._updating_precision = True
        target.setChecked(True)
        self._updating_precision = False

    def _precision_toggled(self, checked: bool) -> None:
        if checked and not self._updating_precision and self.scope_tabs.currentIndex() == 2:
            self._generate()

    def _chart_mode_toggled(self, checked: bool) -> None:
        if checked:
            self._generate()

    def _draw_chart(self, chart_data, period_unit: str) -> None:
        self.axes.clear()
        self._bar_artists.clear()
        self._hover_bar = None
        self._hover_style = None
        self._hover_annotation = self.axes.annotate(
            "",
            xy=(0, 0),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            va="bottom",
            bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#52616b"},
            zorder=10,
        )
        self._hover_annotation.set_visible(False)
        if not chart_data:
            self.axes.text(
                0.5,
                0.5,
                "No hay gastos para el período seleccionado",
                ha="center",
                va="center",
                transform=self.axes.transAxes,
            )
            self.axes.set_xticks([])
            self.axes.set_yticks([])
            self.canvas.draw_idle()
            return

        periods = list(dict.fromkeys(item.period for item in chart_data))
        labels = [self._period_label(period, period_unit) for period in periods]
        positions = list(range(len(periods)))
        if self.categories_check.isChecked():
            categories = sorted({item.category for item in chart_data if item.category is not None})
            values = {(item.period, item.category): float(item.amount) for item in chart_data}
            bar_width = 0.8 / len(categories)
            for category_index, category in enumerate(categories):
                offset = (category_index - (len(categories) - 1) / 2) * bar_width
                heights = [values.get((period, category), 0.0) for period in periods]
                bars = self.axes.bar(
                    [position + offset for position in positions],
                    heights,
                    width=bar_width,
                    label=category,
                )
                self._bar_artists.extend(bars.patches)
                for bar in bars.patches:
                    bar._hover_category = category
            self.axes.legend(title="Categoría", loc="upper left", bbox_to_anchor=(1.01, 1))
        else:
            values = {item.period: float(item.amount) for item in chart_data}
            bars = self.axes.bar(
                positions, [values.get(period, 0.0) for period in periods], width=0.7
            )
            self._bar_artists.extend(bars.patches)

        self.axes.set_xticks(positions, labels)
        self.axes.tick_params(axis="x", labelrotation=35)
        self.axes.set_ylabel("Importe (€)")
        self.axes.grid(axis="y", alpha=0.25)
        self.axes.set_axisbelow(True)
        self.canvas.figure.tight_layout()
        self.canvas.draw_idle()

    def _on_hover(self, event) -> None:
        if event.inaxes is not self.axes or event.xdata is None or event.ydata is None:
            self._clear_hover()
            return

        hovered_bar = next(
            (bar for bar in self._bar_artists if self._is_bar_hovered(bar, event)),
            None,
        )
        if hovered_bar is self._hover_bar:
            if hovered_bar is not None:
                self._hover_annotation.xy = (event.xdata, event.ydata)
                self.canvas.draw_idle()
            return

        self._clear_hover()
        if hovered_bar is None:
            return

        self._hover_bar = hovered_bar
        self._hover_style = (
            hovered_bar.get_edgecolor(),
            hovered_bar.get_linewidth(),
            hovered_bar.get_alpha(),
        )
        hovered_bar.set_edgecolor("#263238")
        hovered_bar.set_linewidth(1.8)
        hovered_bar.set_alpha(0.82)
        self._hover_annotation.xy = (event.xdata, event.ydata)
        category = getattr(self._hover_bar, "_hover_category", None)
        amount_text = self._format_amount(Decimal(str(self._hover_bar.get_height())))
        if category is not None:
            self._hover_annotation.set_text(f"{category}\n{amount_text}")
        else:
            self._hover_annotation.set_text(amount_text)
        self._hover_annotation.set_visible(True)
        self.canvas.draw_idle()

    def _is_bar_hovered(self, bar, event) -> bool:
        if bar.contains(event)[0]:
            return True
        bounds = bar.get_window_extent(self.canvas.get_renderer())
        return (
            bounds.x0 <= event.x <= bounds.x1
            and bounds.y1 <= event.y <= bounds.y1 + HOVER_PADDING_PIXELS
        )

    def _clear_hover(self) -> None:
        if self._hover_bar is None:
            return
        edgecolor, linewidth, alpha = self._hover_style
        self._hover_bar.set_edgecolor(edgecolor)
        self._hover_bar.set_linewidth(linewidth)
        self._hover_bar.set_alpha(alpha)
        self._hover_bar = None
        self._hover_style = None
        self._hover_annotation.set_visible(False)
        self.canvas.draw_idle()

    @staticmethod
    def _period_label(period: str, period_unit: str) -> str:
        if period_unit == "week":
            return date.fromisoformat(period).strftime("%d/%m")
        month = int(period[5:7])
        return f"{MONTH_NAMES[month - 1][:3]} {period[:4]}"

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        formatted = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{formatted} €"

    @staticmethod
    def _one_month_after(value: date) -> date:
        if value.month == 12:
            next_year, next_month = value.year + 1, 1
        else:
            next_year, next_month = value.year, value.month + 1
        next_day = min(value.day, monthrange(next_year, next_month)[1])
        return date(next_year, next_month, next_day)
