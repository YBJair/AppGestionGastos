import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app_gestion_gastos.database import SQLiteDatabase
from app_gestion_gastos.services import ExpenseService
from app_gestion_gastos.ui import MainWindow


def main() -> None:
    database_path = Path.home() / ".app_gestion_gastos" / "gastos.sqlite3"
    database = SQLiteDatabase(database_path)
    database.initialize()
    service = ExpenseService(database)

    application = QApplication(sys.argv)
    window = MainWindow(service)
    window.show()
    sys.exit(application.exec())