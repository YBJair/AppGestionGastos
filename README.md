# Gestion de gastos

Aplicacion de escritorio AppGestionGastos, construida con PySide6 y SQLite.

## Requisitos

- Python 3.11 o posterior

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Ejecucion

```powershell
python -m app_gestion_gastos
```

La base de datos se crea automaticamente en `~/.app_gestion_gastos/gastos.sqlite3`.
Incluye las tablas `categories`, `subcategories`, `expenses`, `import_jobs` e
`import_items`. Los importes se guardan como centavos enteros para evitar errores
de precision.

## Pruebas

```powershell
pytest
```

## Estructura

```text
src/app_gestion_gastos/
|-- main.py       # Inicio y composicion de la aplicacion
|-- models.py     # Entidad de gasto y validacion
|-- database.py   # Persistencia SQLite
|-- services.py   # Casos de uso
|-- ui.py         # Ventana y formulario PySide6
tests/            # Pruebas de servicio y persistencia
```