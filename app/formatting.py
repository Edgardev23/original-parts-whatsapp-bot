"""Utilidades de formato compartidas entre módulos (precios, campos del catálogo).

Se separaron a su propio archivo porque tanto `app/main.py` (para armar las
respuestas de error/saludo) como `app/llm.py` (para armar el catálogo que se
le manda al modelo) necesitan leer y formatear las mismas columnas del
Sheet de la misma manera. Tenerlo en un solo lugar evita que los dos
módulos terminen formateando los precios de forma distinta sin querer.
"""

from __future__ import annotations


def field(item: dict, key: str, default: str = "N/D") -> object:
    """Lee una columna de una fila del catálogo, tratando vacío igual que faltante.

    `item.get(key, default)` NO alcanza para esto: si la celda existe en el
    Sheet pero está vacía, gspread la trae como cadena vacía "" (no como
    ausente), así que `.get()` no aplicaría el default y mostraríamos un
    hueco en blanco. Con `or default` cubrimos ambos casos: columna
    faltante Y columna presente pero vacía.
    """
    return item.get(key) or default


def format_price(value: object) -> str:
    """Formatea un precio con separador de miles estilo colombiano (ej. $20.000).

    Si el valor no es un número (por ejemplo, ya es "N/D" porque la celda
    estaba vacía), se devuelve tal cual, sin intentar formatearlo.
    """
    if not value or value == "N/D":
        return "N/D"
    try:
        # Convertimos a float primero porque gspread puede traer el precio como
        # int, float, o incluso string (si la celda en Sheets no era numérica).
        numero = float(value)
    except (TypeError, ValueError):
        return str(value)
    # ":,.0f" formatea con coma como separador de miles y sin decimales (ej. "20,000");
    # el .replace cambia esa coma por un punto, que es la convención en Colombia (ej. "20.000").
    return f"${numero:,.0f}".replace(",", ".")
