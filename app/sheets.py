"""Wrapper de acceso al Google Sheet que hace de catálogo (todas las filas).

El catálogo puede tener una o varias referencias: este módulo siempre lee
TODAS las filas de datos de la primera hoja del spreadsheet y las devuelve
como una lista de diccionarios (una entrada por fila). La consulta se hace
en tiempo real (sin caché de datos) para que precio y unidades disponibles
reflejen siempre lo que hay en el Sheet en el momento de la pregunta.
"""

from __future__ import annotations

import logging

import gspread  # Librería que permite leer/escribir Google Sheets como si fueran objetos de Python.
from google.oauth2.service_account import Credentials  # Para autenticar usando el JSON de la Service Account.

from app.config import settings

logger = logging.getLogger(__name__)

# Alcance (scope) mínimo necesario: solo permiso de LECTURA sobre Sheets.
# Pedir el permiso mínimo indispensable es buena práctica de seguridad (por si la key se filtrara).
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetsError(RuntimeError):
    """Error al conectar con Google Sheets o al leer el catálogo."""


# Cliente autenticado de gspread, cacheado a nivel de módulo: autenticar de nuevo en cada mensaje
# de WhatsApp sería lento e innecesario, así que se hace una sola vez y se reutiliza.
_client: gspread.Client | None = None


def _get_client() -> gspread.Client:
    """Crea (una sola vez) y reutiliza el cliente autenticado de gspread."""

    global _client
    if _client is None:  # Solo se autentica la primera vez que se llama a esta función.
        logger.info("Autenticando contra Google Sheets con la Service Account…")
        # Lee el archivo JSON descargado de Google Cloud y construye las credenciales con el
        # alcance (scope) definido arriba.
        credentials = Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=_SCOPES
        )
        _client = gspread.authorize(credentials)  # Crea el cliente de gspread ya autenticado y listo para usar.
    return _client  # En llamadas siguientes, devuelve el cliente ya creado (sin volver a autenticar).


def get_catalog() -> list[dict]:
    """Devuelve TODAS las referencias del catálogo, una por fila del Sheet.

    Ejemplo de retorno:
        [
            {"Repuesto": "Bujía NGK CR8E", "Precio": 25000, "Unidades disponibles": 12},
            {"Repuesto": "Rin delantero", "Precio": 20000, "Unidades disponibles": 2},
            ...
        ]

    Lanza `SheetsError` si no se puede conectar, el Sheet no está
    compartido con la Service Account, o no tiene filas de datos.
    """

    try:
        client = _get_client()
        spreadsheet = client.open_by_key(settings.google_sheet_id)  # Abre el spreadsheet por su ID (evita depender del nombre, que podría cambiar).
        worksheet = spreadsheet.sheet1  # Toma la primera hoja/pestaña del spreadsheet.
        # get_all_records() lee todas las filas de datos y las convierte en una lista de diccionarios,
        # usando la primera fila (encabezados) como las claves: "Repuesto", "Precio", "Unidades disponibles".
        # Con un catálogo de varias referencias, esta lista trae una entrada por cada fila del Sheet.
        records = worksheet.get_all_records()
    except gspread.exceptions.APIError as exc:
        # Errores propios de la API de Google (permisos insuficientes, ID incorrecto, cuota excedida, etc.).
        logger.exception("Error de la API de Google Sheets")
        raise SheetsError(
            "No se pudo consultar el Google Sheet. Verifica que el ID en "
            "GOOGLE_SHEET_ID sea correcto y que el Sheet esté compartido con "
            "el correo de la Service Account."
        ) from exc
    except Exception as exc:  # credenciales inválidas, archivo corrupto, etc.
        # Cualquier otro error no anticipado (por ejemplo, el JSON de credenciales está mal formado).
        logger.exception("Error inesperado al conectar con Google Sheets")
        raise SheetsError("No se pudo conectar con Google Sheets.") from exc

    if not records:  # Una lista vacía significa que el Sheet solo tiene encabezados, sin filas de datos.
        logger.error("El Google Sheet no tiene filas de datos.")
        raise SheetsError(
            "El catálogo en Google Sheets está vacío. Agrega al menos una fila "
            "de ejemplo (ver seed_sheet_data.md)."
        )

    logger.info("Catálogo leído desde Sheets: %d referencia(s)", len(records))
    return records


def get_synonyms() -> list[dict]:
    """Devuelve la tabla de sinónimos/jerga regional para los repuestos, si existe.

    Se espera una SEGUNDA pestaña en el mismo Google Sheet, llamada
    "Sinonimos", con dos columnas:
        - "Repuesto": el nombre EXACTO tal como aparece en la pestaña principal del catálogo.
        - "Sinonimos": otras formas en que los clientes se refieren a esa pieza,
          separadas por coma (ej. "cojinetes, cunas, balineras").

    Esta pestaña es completamente opcional y pensada para que el dueño del
    negocio la mantenga él mismo (sin tocar código) a medida que note que
    los clientes usan palabras que el bot no reconoce todavía. Por eso, si
    la pestaña aún no existe, esta función NO falla: devuelve una lista
    vacía y el bot sigue funcionando normalmente (apoyándose solo en el
    conocimiento general del modelo para reconocer sinónimos).
    """

    try:
        client = _get_client()
        spreadsheet = client.open_by_key(settings.google_sheet_id)
        worksheet = spreadsheet.worksheet("Sinonimos")  # A diferencia de get_catalog(), busca la pestaña POR NOMBRE.
        records = worksheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        # Es normal que esta pestaña no exista todavía (es opcional): no es un error real.
        logger.info("No existe la pestaña 'Sinonimos' en el Sheet; se continúa sin ella.")
        return []
    except Exception:
        # Cualquier otro problema (permisos, formato raro, etc.) tampoco debe tumbar el bot: el
        # glosario de sinónimos es un "plus", no algo de lo que dependa el flujo principal.
        logger.exception("Error leyendo la pestaña 'Sinonimos'; se continúa sin ella.")
        return []

    logger.info("Glosario de sinónimos leído desde Sheets: %d fila(s)", len(records))
    return records
