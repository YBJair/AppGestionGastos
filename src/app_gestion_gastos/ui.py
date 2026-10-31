from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, QEvent, QObject, QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from rapidfuzz import fuzz, process

from app_gestion_gastos.breakdown_view import ExpenseBreakdownView
from app_gestion_gastos.chart_view import ExpenseChartView
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.text_utils import normalize_text

FUZZY_MATCH_THRESHOLD = 90


class DescriptionLineEdit(QLineEdit):
    committed = Signal(str)

    def __init__(self, descriptions: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._focus_target: QWidget | None = None
        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.setModelSorting(
            QCompleter.ModelSorting.CaseInsensitivelySortedModel
        )
        self.update_completions(descriptions)
        self.setCompleter(self._completer)
        self._completer.activated.connect(self._accept_completion)
        self.installEventFilter(self)

    def set_focus_target(self, widget: QWidget) -> None:
        self._focus_target = widget

    def update_completions(self, descriptions: list[str]) -> None:
        sorted_descriptions = sorted(set(descriptions), key=str.casefold)
        self._completer.setModel(QStringListModel(sorted_descriptions, self._completer))

    def eventFilter(self, watched, event) -> bool:
        if watched is self and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                popup = self._completer.popup()
                if popup.isVisible():
                    completion = self._completer.currentCompletion()
                    if completion:
                        self._accept_completion(completion)
                    else:
                        self.committed.emit(self.text())
                        self._move_focus_to_amount()
                    return True
                self.committed.emit(self.text())
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._move_focus_to_amount()
                    return True
                self._move_focus_to_amount()
                return True
        return super().eventFilter(watched, event)

    def _accept_completion(self, completion: str) -> None:
        self.setText(completion)
        self.committed.emit(completion)
        self._completer.popup().hide()
        self._move_focus_to_amount()

    def _move_focus_to_amount(self) -> None:
        if self._focus_target is not None:
            QTimer.singleShot(0, self._focus_target.setFocus)


class EnterToNextFieldFilter(QObject):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._next_by_widget: dict[int, QWidget] = {}

    def add(self, widget: QWidget, next_widget: QWidget) -> None:
        self._next_by_widget[id(widget)] = next_widget
        widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.KeyPress or event.key() not in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            return False
        next_widget = self._next_by_widget.get(id(watched))
        if next_widget is None:
            return False
        parent = watched.parent()
        if isinstance(parent, QComboBox) and parent.view().isVisible():
            return False
        QTimer.singleShot(0, next_widget.setFocus)
        return True


class AmountSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 1_000_000_000)
        self.setDecimals(2)
        self._zero_placeholder = self.locale().toString(0.0, "f", self.decimals())
        self.setSpecialValueText(self._zero_placeholder)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self.value() == self.minimum():
            self.setSpecialValueText(" ")

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self.value() == self.minimum():
            self.setSpecialValueText(self._zero_placeholder)


class ExpenseEntryView(QWidget):
    expense_saved = Signal()

    def __init__(self, service: ExpenseService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        self.description_input = DescriptionLineEdit([])
        self._category_by_normalized_description: dict[str, tuple[str, str]] = {}
        self._load_expense_suggestions()
        self.description_input.committed.connect(self._apply_description_classification)
        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.category_input.lineEdit().setPlaceholderText("Escribe o selecciona una categoria")
        self.category_input.addItems(self._service.list_categories())
        self.category_input.setCurrentIndex(-1)
        self.category_input.lineEdit().clear()

        self.subcategory_input = QComboBox()
        self.subcategory_input.setEditable(True)
        self.subcategory_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.subcategory_input.lineEdit().setPlaceholderText(
            "Escribe o selecciona una subcategoria"
        )
        self.subcategory_input.setEnabled(False)

        self.amount_input = AmountSpinBox()
        self.description_input.set_focus_target(self.amount_input)
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        today_button = QPushButton("Hoy")
        today_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        today_button.clicked.connect(self._set_today)

        date_row = QHBoxLayout()
        date_row.addWidget(self.date_input, 1)
        date_row.addWidget(today_button)

        form = QFormLayout(self)
        form.addRow("Descripcion", self.description_input)
        form.addRow("Importe", self.amount_input)
        form.addRow("Fecha", date_row)
        form.addRow("Categoria", self.category_input)
        form.addRow("Subcategoria", self.subcategory_input)

        self.category_input.currentTextChanged.connect(self._category_changed)
        self._category_changed(self.category_input.currentText())

        self.save_button = QPushButton("Guardar")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save)
        self.status_label = QLabel()
        form.addRow(self.save_button)
        form.addRow(self.status_label)

        self._enter_filter = EnterToNextFieldFilter(self)
        self._enter_filter.add(self.amount_input, self.date_input)
        self._enter_filter.add(self.date_input, self.category_input.lineEdit())
        self._enter_filter.add(self.date_input.lineEdit(), self.category_input.lineEdit())
        self._enter_filter.add(self.category_input.lineEdit(), self.subcategory_input.lineEdit())
        self._enter_filter.add(self.subcategory_input.lineEdit(), self.save_button)

    def _save(self) -> None:
        try:
            self._service.register_expense(
                category=self.category_input.currentText(),
                description=self.description_input.text(),
                amount=Decimal(str(self.amount_input.value())),
                spent_on=date.fromisoformat(self.date_input.date().toString("yyyy-MM-dd")),
                subcategory=self.subcategory_input.currentText(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Datos no validos", str(error))
            self._focus_invalid_field(str(error))
            return
        self._reset_form()
        self.status_label.setText("Gasto guardado")
        self.expense_saved.emit()
        self.description_input.setFocus()

    def _focus_invalid_field(self, error: str) -> None:
        message = error.casefold()
        if "descripcion" in message:
            target = self.description_input
        elif "importe" in message:
            target = self.amount_input
        elif "categoria" in message:
            target = self.category_input.lineEdit()
        else:
            target = self.subcategory_input.lineEdit()
        target.setFocus()

    def _reset_form(self) -> None:
        self.description_input.clear()
        self.amount_input.setValue(0)
        self.date_input.setDate(QDate.currentDate())
        self.category_input.clear()
        self.category_input.addItems(self._service.list_categories())
        self.category_input.setCurrentIndex(-1)
        self.category_input.lineEdit().clear()
        self.subcategory_input.clear()
        self.subcategory_input.setEnabled(False)
        self._load_expense_suggestions()

    def _load_expense_suggestions(self) -> None:
        suggestions = self._service.list_expense_suggestions()
        self.description_input.update_completions(
            [suggestion.description for suggestion in suggestions]
        )
        self._category_by_normalized_description = {}
        for suggestion in suggestions:
            if not suggestion.category or not suggestion.subcategory:
                continue
            normalized = normalize_text(suggestion.description)
            if normalized:
                self._category_by_normalized_description.setdefault(
                    normalized, (suggestion.category, suggestion.subcategory)
                )

    def _apply_description_classification(self, description: str) -> None:
        normalized = normalize_text(description)
        classification = self._category_by_normalized_description.get(normalized)
        if classification is None and normalized:
            match = process.extractOne(
                normalized,
                list(self._category_by_normalized_description),
                scorer=fuzz.ratio,
                score_cutoff=FUZZY_MATCH_THRESHOLD,
            )
            if match is not None:
                classification = self._category_by_normalized_description[match[0]]
        if classification is None:
            return
        category, subcategory = classification
        self.category_input.setEditText(category)
        self.subcategory_input.setEditText(subcategory)

    def _set_today(self) -> None:
        self.date_input.setDate(QDate.currentDate())

    def _category_changed(self, category: str) -> None:
        self.subcategory_input.clear()
        subcategories = self._service.list_subcategories(category)
        self.subcategory_input.addItems(subcategories)
        self.subcategory_input.setCurrentIndex(-1)
        self.subcategory_input.lineEdit().clear()
        self.subcategory_input.setEnabled(bool(category.strip()))


class MainWindow(QMainWindow):
    def __init__(self, service: ExpenseService) -> None:
        super().__init__()
        self._service = service
        self.setWindowTitle("AppGestionGastos")
        self.resize(820, 480)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Descripcion", "Importe", "Categoria", "Subcategoria"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        container = QWidget()
        container.setLayout(layout)
        self.tabs = QTabWidget()
        self.chart_view = ExpenseChartView(service)
        self.tabs.addTab(self.chart_view, "Gráfico")
        self.breakdown_view = ExpenseBreakdownView(service)
        self.tabs.addTab(self.breakdown_view, "Desglose")
        self.tabs.addTab(container, "Gastos")
        self.expense_view = ExpenseEntryView(service)
        self.tabs.addTab(self.expense_view, "Nuevo gasto")
        self.expense_view.expense_saved.connect(self.refresh)
        self.tabs.setCurrentWidget(self.chart_view)
        self.tabs.currentChanged.connect(self._main_tab_changed)
        self.setCentralWidget(self.tabs)
        self.refresh()

    def refresh(self) -> None:
        expenses = self._service.list_expenses()
        self.table.setRowCount(len(expenses))
        for row_index, expense in enumerate(expenses):
            values = (
                expense.spent_on.isoformat(),
                expense.description,
                f"{expense.amount:.2f}",
                expense.category,
                expense.subcategory or "",
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 2:
                    alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    item.setTextAlignment(alignment)
                self.table.setItem(row_index, column_index, item)
        self.chart_view.refresh()

    def _main_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.chart_view:
            self.chart_view.refresh()
