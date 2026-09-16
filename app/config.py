"""Carga y validación de configuración desde variables de entorno.

Este módulo se encarga de leer el archivo `.env` (si existe) y exponer una
única instancia de `Settings` con todos los valores que el resto de la app
necesita. Si falta alguna variable obligatoria, se lanza `ConfigError` con un
mensaje claro y accionable en vez de dejar que el programa falle más
adelante con un stacktrace críptico (por ejemplo, un `KeyError` al intentar
leer `os.environ["ALGO"]` en medio de una petición del webhook).
"""

from __future__ import annotations

import os  # Para leer variables de entorno (os.getenv/os.environ) y comprobar si un archivo existe.
from dataclasses import dataclass  # Para crear la clase Settings como un simple "contenedor de datos".

from dotenv import load_dotenv  # Librería que lee un archivo .env y carga sus variables al entorno del proceso Python.

# Carga las variables definidas en el archivo .env (si existe) al entorno del
# proceso. No sobreescribe variables que ya estén definidas en el sistema.
load_dotenv()  # Se ejecuta apenas se importa este módulo, antes de que se lea ninguna variable más abajo.

# Variables de entorno obligatorias para que el bot pueda funcionar.
_REQUIRED_VARS = [
    "TWILIO_ACCOUNT_SID",            # Identificador de tu cuenta de Twilio.
    "TWILIO_AUTH_TOKEN",             # Token secreto para autenticar las llamadas a la API de Twilio.
    "TWILIO_WHATSAPP_NUMBER",        # Número de WhatsApp del sandbox (el remitente de los mensajes del bot).
    "ANTHROPIC_API_KEY",             # API key para llamar al modelo de Claude.
    "GOOGLE_SERVICE_ACCOUNT_FILE",   # Ruta al archivo JSON de credenciales de la Service Account de Google.
    "GOOGLE_SHEET_ID",               # ID del Google Sheet que funciona como catálogo.
]

# Valores por defecto para las variables opcionales (si no están en .env, se usan estos).
_DEFAULT_WHISPER_MODEL_SIZE = "base"
_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
# Modelo de moto al que pertenece el catálogo actual (ver seed_sheet_data.md / CLAUDE.md: la muestra
# está acotada a una sola referencia de moto). El Sheet no tiene una columna de modelo por fila, así
# que esto le dice al LLM a qué moto aplica TODO el catálogo, para que no confirme un repuesto que
# coincide de nombre pero es para una moto distinta a la que el cliente menciona.
_DEFAULT_CATALOG_MOTO_MODEL = "Suzuki GN 125"


class ConfigError(RuntimeError):
    """Se lanza cuando falta configuración obligatoria en el entorno.

    El mensaje está pensado para ser leído directamente por una persona
    (el mismo usuario del bot durante la demo), no solo para debugging.
    """
    # Al heredar de RuntimeError, cualquier "except Exception" en el resto del código también la captura.


@dataclass(frozen=True)
# @dataclass genera automáticamente el __init__ (constructor) a partir de los campos de abajo.
# frozen=True hace que, una vez creado un Settings, no se pueda modificar ninguno de sus valores.
class Settings:
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_number: str
    anthropic_api_key: str
    google_service_account_file: str
    google_sheet_id: str
    whisper_model_size: str
    anthropic_model: str
    catalog_moto_model: str


def load_settings() -> Settings:
    """Lee y valida las variables de entorno requeridas.

    Lanza `ConfigError` listando TODAS las variables faltantes de una vez
    (no solo la primera que encuentre), para que quien está configurando el
    bot pueda arreglarlas todas en una sola pasada.
    """

    # Recorre la lista de variables obligatorias y se queda solo con los nombres cuyo valor es
    # None o cadena vacía (os.getenv devuelve None si la variable no existe).
    missing = [name for name in _REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise ConfigError(
            "Faltan variables de entorno obligatorias: "
            f"{', '.join(missing)}.\n"  # Une los nombres faltantes separados por coma para el mensaje de error.
            "Copia '.env.example' a '.env' y completa esos valores antes de "
            "arrancar el servidor. Revisa el README.md para saber cómo "
            "obtener cada credencial."
        )

    service_account_path = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    # Usamos os.environ[...] (no os.getenv) porque en este punto ya validamos que la variable existe.
    if not os.path.isfile(service_account_path):
        # Comprobación extra: que la variable exista no significa que el archivo al que apunta exista.
        raise ConfigError(
            f"GOOGLE_SERVICE_ACCOUNT_FILE apunta a '{service_account_path}', "
            "pero ese archivo no existe. Descarga el JSON de la Service "
            "Account de Google Cloud y ajusta la ruta en '.env' "
            "(ver README.md, sección de credenciales de Google)."
        )

    # Con todo validado, construimos y devolvemos la instancia inmutable de Settings.
    return Settings(
        twilio_account_sid=os.environ["TWILIO_ACCOUNT_SID"],
        twilio_auth_token=os.environ["TWILIO_AUTH_TOKEN"],
        twilio_whatsapp_number=os.environ["TWILIO_WHATSAPP_NUMBER"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        google_service_account_file=service_account_path,
        google_sheet_id=os.environ["GOOGLE_SHEET_ID"],
        # Para las variables opcionales sí usamos os.getenv con un valor por defecto,
        # porque no es obligatorio que estén presentes en .env.
        whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", _DEFAULT_WHISPER_MODEL_SIZE),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL),
        catalog_moto_model=os.getenv("CATALOG_MOTO_MODEL", _DEFAULT_CATALOG_MOTO_MODEL),
    )


# Instancia única reutilizada por el resto de los módulos. Se calcula al
# importar este módulo por primera vez, de modo que un `.env` incompleto
# haga fallar la aplicación de inmediato al arrancar, en vez de fallar a
# mitad de una conversación de WhatsApp durante la demo.
settings = load_settings()  # Se ejecuta una única vez: la primera vez que algo hace "import app.config".
