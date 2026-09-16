"""Utilidades de integración con Twilio: descarga de audio y respuesta TwiML."""

from __future__ import annotations

import logging  # Para registrar mensajes en consola.
import mimetypes  # Para deducir la extensión de archivo (.ogg, .mp3...) a partir del tipo MIME que manda Twilio.
import tempfile  # Para crear archivos temporales de forma segura en el disco.

import requests  # Librería HTTP usada para descargar el audio desde la URL que da Twilio.
from fastapi import Response  # Para poder devolver una respuesta HTTP con contenido XML "a mano".
from requests.auth import HTTPBasicAuth  # Para autenticar la descarga con usuario/contraseña (Account SID / Auth Token).
from twilio.rest import Client as TwilioRestClient  # Cliente de la API REST de Twilio, para mensajes que el bot inicia por su cuenta.
from twilio.twiml.messaging_response import MessagingResponse  # Helper oficial de Twilio para generar el XML (TwiML) de respuesta.

from app.config import settings  # Trae las credenciales de Twilio ya validadas.

logger = logging.getLogger(__name__)

# Cliente REST de Twilio, creado una sola vez (igual que el cliente de Anthropic en app/llm.py).
# Solo se usa para mensajes PROACTIVOS (ej. el reenganche tras 5 min de silencio); las respuestas
# normales del webhook van por TwiML (`build_twiml_response`), no por este cliente.
_rest_client = TwilioRestClient(settings.twilio_account_sid, settings.twilio_auth_token)


class WhatsAppDownloadError(RuntimeError):
    """Error al descargar un archivo de audio enviado por WhatsApp/Twilio."""


def download_audio(media_url: str, content_type: str) -> str:
    """Descarga el audio de una URL de Twilio a un archivo temporal.

    Twilio protege las URLs de media con autenticación básica usando el
    Account SID y el Auth Token. Devuelve la ruta local del archivo
    descargado; el llamador es responsable de borrarlo cuando termine.
    """

    # Traduce el tipo MIME (ej. "audio/ogg") a una extensión de archivo (ej. ".ogg").
    # Si no reconoce el tipo, usa ".ogg" como valor por defecto, que es el formato típico de WhatsApp.
    extension = mimetypes.guess_extension(content_type) or ".ogg"

    try:
        logger.info("Descargando audio desde Twilio: %s", media_url)
        response = requests.get(
            media_url,
            # Las URLs de media de Twilio no son públicas: piden autenticación básica con las mismas
            # credenciales que usamos para hablar con su API (así nadie más puede descargar el audio).
            auth=HTTPBasicAuth(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=30,  # Corta la espera a los 30s para no dejar el webhook colgado si Twilio no responde.
        )
        response.raise_for_status()  # Lanza una excepción si el status HTTP indica error (4xx o 5xx).
    except requests.RequestException as exc:
        logger.exception("Error descargando el audio desde Twilio")
        # "from exc" conserva la excepción original encadenada, para ver la causa real en el traceback.
        raise WhatsAppDownloadError("No se pudo descargar el audio enviado.") from exc

    # Crea un archivo temporal en disco. delete=False evita que se borre solo al cerrar el "with";
    # lo borra explícitamente quien llama a esta función (ver app/main.py, en el bloque finally).
    with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp_file:
        tmp_file.write(response.content)  # Escribe en disco los bytes de audio descargados.
        logger.info("Audio guardado temporalmente en: %s", tmp_file.name)
        return tmp_file.name  # Devuelve la ruta del archivo, para que transcription.py pueda abrirlo.


def send_message(to: str, body: str) -> None:
    """Envía un mensaje de WhatsApp por iniciativa del bot (fuera de la respuesta a un webhook).

    A diferencia de `build_twiml_response`, esto SÍ hace una llamada de red a la API de Twilio
    (Twilio no permite "empujar" un mensaje devolviendo TwiML fuera de la petición original).
    Se usa para el mensaje de reenganche tras varios minutos sin respuesta del cliente.
    """
    try:
        _rest_client.messages.create(from_=settings.twilio_whatsapp_number, to=to, body=body)
        logger.info("Mensaje proactivo enviado a %s", to)
    except Exception:
        # No relanzamos: si falla, se registra y sigue el chequeo del próximo cliente (ver
        # app/main.py:_reengagement_loop), en vez de tumbar la tarea de fondo completa.
        logger.exception("Error enviando mensaje proactivo a %s", to)


def build_twiml_response(message: str) -> Response:
    """Construye la respuesta TwiML (<Response><Message>...) para el webhook."""

    twiml = MessagingResponse()  # Objeto que arma el XML "<Response>...</Response>" que Twilio espera recibir.
    twiml.message(message)  # Agrega un "<Message>texto</Message>" dentro de ese <Response>.
    # FastAPI necesita que le digamos explícitamente media_type="application/xml"; si no, respondería
    # como JSON o texto plano y Twilio no lo interpretaría como un mensaje válido para reenviar.
    return Response(content=str(twiml), media_type="application/xml")
