"""FastAPI app: webhook de Twilio WhatsApp para el POC de Original Parts.

Flujo (ver README.md para el detalle completo):
1. Twilio manda un POST con el mensaje del cliente (texto y/o audio).
2. Si trae audio, se descarga y se transcribe localmente con faster-whisper.
3. El texto (escrito o transcrito) se agrega al historial de conversación
   de ese número de WhatsApp, y se le manda todo ese historial a Claude
   Haiku junto con el catálogo completo, para que responda en lenguaje
   natural (puede recordar mensajes anteriores, sumar precios, comparar
   referencias, etc. — no es solo un clasificador de una sola pregunta).
4. La respuesta del modelo se guarda también en el historial (para la
   siguiente pregunta) y se envía tal cual al cliente por WhatsApp.

Todas las respuestas usan un tono cálido (saludo + emojis) para que se
sienta como la atención de un negocio real, no como un bot de pruebas.
"""

from __future__ import annotations  # Permite usar anotaciones de tipo modernas (p. ej. "str | None") sin problemas de compatibilidad.

import asyncio  # Para correr en segundo plano el chequeo periódico de conversaciones inactivas (reenganche a los 5 min).
import logging  # Módulo estándar de Python para registrar mensajes (info, warning, error) en la consola.
import os  # Solo lo usamos para borrar el archivo temporal de audio una vez procesado.
import re  # Para el chequeo simple de "¿el mensaje es solo un saludo?".
import unicodedata  # Para quitar tildes al normalizar el texto de ese mismo chequeo.
from contextlib import asynccontextmanager  # Para registrar la tarea de reenganche al arrancar el servidor (lifespan de FastAPI).
from datetime import datetime, timedelta  # Para medir cuánto tiempo lleva un cliente sin responder.

from fastapi import FastAPI, Request, Response
# FastAPI: el framework que crea el servidor web.
# Request: nos deja leer los datos que Twilio manda en el POST.
# Response: nos deja construir a mano la respuesta HTTP (en este caso, XML en vez de JSON).

from app.config import settings  # noqa: F401  (valida el entorno al importar)
from app import llm, sheets, transcription, whatsapp
# Importamos nuestros propios módulos:
#   llm            -> conversa con Claude (catálogo completo + historial) y devuelve la respuesta.
#   sheets         -> lee el catálogo desde Google Sheets.
#   transcription  -> convierte audio a texto con faster-whisper.
#   whatsapp       -> descarga audios de Twilio y arma la respuesta TwiML.

# Configuración global de logging: nivel INFO (se muestran info/warning/error, no debug),
# con un formato que incluye fecha, nivel, nombre del módulo y el mensaje.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)  # Logger propio de este archivo; en consola aparecerá como "app.main".


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Arranca la tarea de reenganche (ver `_reengagement_loop`) en segundo plano junto con el
    # servidor, y la cancela limpiamente si el servidor se apaga.
    task = asyncio.create_task(_reengagement_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Original Parts WhatsApp Bot (POC)", lifespan=_lifespan)  # La instancia de la app: esto es lo que uvicorn arranca.

# Historial de conversación por número de WhatsApp, guardado EN MEMORIA (una simple variable de
# Python, no una base de datos): se pierde si el servidor se reinicia. Para este POC es un precio
# aceptable a cambio de simplicidad; en la versión de producción esto se guardaría en una base de
# datos o cache (ej. Redis) para que sobreviva a reinicios y funcione con varios servidores a la vez.
# Cada valor es una lista de mensajes en el formato que espera la API de Anthropic:
#   [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
_conversations: dict[str, list[dict]] = {}

# Cuántos mensajes (sumando los del cliente y los del bot) se conservan por conversación. Sin este
# límite, una charla larga iría agrandando cada llamada al LLM indefinidamente (más lento y más caro).
MAX_HISTORY_MESSAGES = 12

# Números de WhatsApp que ya recibieron el saludo de bienvenida en esta corrida del servidor.
_greeted_senders: set[str] = set()

# Última vez que se recibió un mensaje de cada número (para detectar inactividad y reenganchar).
_last_seen: dict[str, datetime] = {}
# Números a los que ya se les envió el mensaje de reenganche desde su último mensaje (para no
# reenviarlo en cada chequeo mientras sigan sin responder).
_reengaged_senders: set[str] = set()

REENGAGEMENT_DELAY = timedelta(minutes=5)  # Cuánto tiempo de silencio del cliente dispara el reenganche.
REENGAGEMENT_CHECK_INTERVAL_SECONDS = 30  # Cada cuánto se revisa si algún cliente ya cumplió esa espera.

GREETING = "¡Gracias por comunicarte con Original Parts! 🛵🔧\n¿En qué podemos servirte?"
REENGAGEMENT_MESSAGE = "¡Hola! 👋 ¿En qué podemos servirte?"

# Textos de respuesta reutilizables, para no repetir el string en varios lugares del archivo.
MSG_REFORMULATE = (
    "🤔 No logré entender bien tu consulta. ¿Puedes escribirla de nuevo o "
    "contarme qué repuesto necesitas? 🙏"
)
MSG_GENERIC_ERROR = (
    "😓 Tuvimos un problema consultando la información en este momento. "
    "Por favor intenta de nuevo en unos minutos."
)

# Palabras sueltas que consideramos "solo un saludo" (sin tildes, en minúscula). Se usa para no
# duplicar la pregunta "¿En qué podemos servirte?" cuando el saludo de bienvenida ya la incluye.
_GREETING_WORDS = {
    "hola", "hey", "ey", "buenas", "buenos", "dias", "tardes", "noches",
    "que", "tal", "alo", "aloh", "buen", "dia", "quiubo", "qubo",
}


def _is_pure_greeting(text: str) -> bool:
    """True si el mensaje son solo palabras de saludo, sin pedir nada en concreto.

    P. ej. "Hola", "Buenas tardes!" o "hola que tal" son saludos puros; "hola
    necesito una leva" no lo es, porque "leva" no está en la lista.
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z]+", normalized)
    return bool(words) and all(word in _GREETING_WORDS for word in words)


async def _reengagement_loop() -> None:
    """Revisa periódicamente si algún cliente lleva REENGAGEMENT_DELAY sin responder.

    A diferencia del resto del bot (que solo reacciona a webhooks de Twilio), este mensaje lo
    inicia el bot por su cuenta, así que se manda por la API REST de Twilio (`whatsapp.send_message`)
    en vez de por una respuesta TwiML.
    """
    while True:
        await asyncio.sleep(REENGAGEMENT_CHECK_INTERVAL_SECONDS)
        now = datetime.now()
        # Se recorre una copia (list(...)) porque `_last_seen` puede cambiar mientras iteramos
        # (un webhook nuevo puede llegar en cualquier momento).
        for sender, last_seen in list(_last_seen.items()):
            if sender in _reengaged_senders:
                continue
            if now - last_seen < REENGAGEMENT_DELAY:
                continue
            logger.info("%s lleva %s sin responder; enviando mensaje de reenganche.", sender, REENGAGEMENT_DELAY)
            whatsapp.send_message(sender, REENGAGEMENT_MESSAGE)
            _reengaged_senders.add(sender)
            # Se guarda en el historial para que, si el cliente responde después, el modelo sepa
            # que ese fue el último mensaje de la conversación (y no repita el saludo).
            _conversations.setdefault(sender, []).append({"role": "assistant", "content": REENGAGEMENT_MESSAGE})


def _reply(sender: str, message: str) -> Response:
    """Arma la respuesta TwiML final, anteponiendo el saludo de bienvenida.

    El saludo solo se agrega la PRIMERA vez que un número escribe (mientras
    el servidor no se reinicie); en mensajes siguientes de la misma
    conversación se omite, para no sonar repetitivo.
    """
    if sender not in _greeted_senders:
        _greeted_senders.add(sender)
        message = f"{GREETING}\n\n{message}" if message else GREETING
    return whatsapp.build_twiml_response(message)


@app.post("/webhook/whatsapp")
# El decorador registra esta función como la que atiende POST /webhook/whatsapp.
# Esa es la URL que le vamos a dar a Twilio (vía el túnel) para que nos avise de mensajes nuevos.
async def whatsapp_webhook(request: Request) -> Response:
    # Twilio manda los datos como un formulario clásico (application/x-www-form-urlencoded),
    # no como JSON, por eso usamos request.form() y no request.json().
    form = await request.form()

    sender = form.get("From", "desconocido")  # Número de WhatsApp que escribió, ej. "whatsapp:+573001234567".
    body = (form.get("Body") or "").strip()  # Texto del mensaje (vacío si el mensaje es solo un audio); strip() quita espacios extra.
    num_media = int(form.get("NumMedia") or 0)  # Cantidad de adjuntos que trae el mensaje (Twilio manda "0" o "1").
    media_url = form.get("MediaUrl0")  # URL del primer adjunto, si existe, para poder descargarlo.
    media_content_type = form.get("MediaContentType0") or ""  # Tipo MIME del adjunto, ej. "audio/ogg".

    # Cualquier mensaje entrante reinicia el reloj de inactividad y cancela un reenganche pendiente
    # (si el cliente ya escribió, no hace falta insistir).
    _last_seen[sender] = datetime.now()
    _reengaged_senders.discard(sender)

    # Registro de lo recibido, útil para depurar en vivo mientras haces la demo.
    logger.info(
        "Mensaje recibido de %s (texto=%r, media=%s, content_type=%s)",
        sender,
        body,
        bool(num_media),
        media_content_type,
    )

    try:
        user_text = body  # Por defecto usamos el texto escrito por el cliente.

        # Si el adjunto es un audio, lo descargamos y transcribimos en vez de usar `body`.
        if num_media > 0 and media_content_type.startswith("audio/") and media_url:
            audio_path = None  # Ruta local del archivo descargado; queda en None si la descarga falla antes de crearlo.
            try:
                audio_path = whatsapp.download_audio(media_url, media_content_type)  # Descarga el audio a un archivo temporal en disco.
                user_text = transcription.transcribe(audio_path)  # Lo convierte a texto con faster-whisper (local, sin internet).
            finally:
                # Este bloque se ejecuta siempre (haya error o no) para no dejar archivos temporales acumulados en disco.
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
                    logger.info("Audio temporal eliminado: %s", audio_path)

        # Si después de todo esto seguimos sin texto utilizable, no hay nada que interpretar.
        # Ojo: a propósito NO guardamos esto en el historial (no aporta nada a la conversación).
        if not user_text:
            logger.info("No se obtuvo texto utilizable (ni escrito ni transcrito).")
            return _reply(sender, MSG_REFORMULATE)

        # Si es el PRIMER mensaje de este número y es solo un saludo (sin pedir nada en concreto),
        # respondemos solo con la bienvenida (que ya incluye "¿En qué podemos servirte?") sin pasar
        # por el LLM, para no terminar con dos preguntas parecidas seguidas. Si en cambio el cliente
        # ya pregunta por un repuesto en este mismo primer mensaje (sin haber saludado), esta
        # condición es falsa y sigue el flujo normal de abajo, que sí lo interpreta con el LLM.
        if sender not in _greeted_senders and _is_pure_greeting(user_text):
            logger.info("Primer mensaje de %s es solo un saludo; respondiendo solo con la bienvenida.", sender)
            return _reply(sender, "")

        catalog = sheets.get_catalog()  # Lee en tiempo real TODAS las filas del catálogo desde Google Sheets.
        synonyms = sheets.get_synonyms()  # Lee la pestaña opcional de jerga/sinónimos (lista vacía si no existe).

        # Recupera el historial de esta conversación (o crea uno vacío si es la primera vez que
        # este número escribe) y le agrega el mensaje actual del cliente.
        history = _conversations.setdefault(sender, [])
        history.append({"role": "user", "content": user_text})

        reply_text = llm.chat_reply(history, catalog, synonyms)  # Le pasa historial + catálogo + sinónimos a Claude.

        if reply_text is None:
            # El LLM falló (red, límite de uso, etc.). Sacamos el mensaje que acabamos de agregar
            # para no dejar el historial con una pregunta del cliente sin su respuesta correspondiente.
            history.pop()
            logger.error("El LLM no pudo generar una respuesta para %s", sender)
            return _reply(sender, MSG_GENERIC_ERROR)

        history.append({"role": "assistant", "content": reply_text})
        # Recorta el historial a los últimos MAX_HISTORY_MESSAGES mensajes. "del lista[:-N]" borra
        # todo MENOS los últimos N elementos (si hay menos de N, no borra nada).
        del history[:-MAX_HISTORY_MESSAGES]

        logger.info("Respondiendo a %s: %r", sender, reply_text)
        return _reply(sender, reply_text)  # Antepone el saludo (solo la primera vez) y arma el XML (TwiML) que Twilio espera.

    except Exception:
        # Cualquier fallo no previsto (Sheets caído, Claude caído, etc.) se registra con el stacktrace completo
        # en la consola, pero al cliente NUNCA se le muestra un error técnico: siempre recibe un mensaje amable.
        logger.exception("Error inesperado procesando el mensaje de %s", sender)
        return _reply(sender, MSG_GENERIC_ERROR)
