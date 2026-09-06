"""Wrapper de transcripción de audio con faster-whisper (local, sin GPU)."""

from __future__ import annotations

import logging

from faster_whisper import WhisperModel  # Implementación optimizada de Whisper: más rápida y liviana que openai-whisper en CPU.

from app.config import settings

logger = logging.getLogger(__name__)

# Variable a nivel de módulo (compartida por todas las peticiones) que guarda el modelo ya cargado,
# para no volver a cargarlo en cada mensaje: cargar el modelo es lento (varios segundos).
_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    """Carga el modelo de Whisper una sola vez (es costoso) y lo reutiliza."""

    global _model  # Necesario en Python para poder reasignar, dentro de la función, una variable definida fuera de ella.
    if _model is None:  # Solo entra aquí la primera vez que se llama a esta función (o si nunca se ha llamado).
        logger.info(
            "Cargando modelo faster-whisper '%s' (CPU, int8)… puede tardar la primera vez.",
            settings.whisper_model_size,
        )
        # device="cpu"        -> corre en el procesador normal, no necesita tarjeta gráfica.
        # compute_type="int8" -> usa precisión numérica reducida para ser más rápido y liviano en CPU
        #                        (a cambio de una pizca de precisión, aceptable para esta muestra).
        _model = WhisperModel(settings.whisper_model_size, device="cpu", compute_type="int8")
    return _model  # En llamadas siguientes, esto devuelve el modelo ya cargado en memoria (instantáneo).


def transcribe(audio_path: str) -> str:
    """Transcribe un archivo de audio a texto.

    Si el audio no se puede transcribir o queda vacío, se devuelve una
    cadena vacía en vez de lanzar una excepción: el llamador interpreta un
    texto vacío como "no se entendió la consulta" y responde amablemente.
    """

    try:
        model = _get_model()
        logger.info("Transcribiendo audio: %s", audio_path)
        # language="es" evita que Whisper pierda tiempo detectando el idioma y falle por acentos/ruido.
        # Devuelve un generador de "segments" (fragmentos con texto y timestamps) y un objeto "info".
        segments, info = model.transcribe(audio_path, language="es")
        # Recorre cada fragmento, le quita espacios sobrantes con strip(), y los une todos con espacios
        # en un único string con el texto completo transcrito.
        text = " ".join(segment.text.strip() for segment in segments).strip()
        logger.info(
            "Transcripción completada (idioma detectado=%s, duración=%.1fs): %r",
            info.language,
            info.duration,
            text,
        )
        return text
    except Exception:
        # Si algo falla (audio corrupto, formato raro, etc.) no se rompe el webhook completo:
        # se devuelve texto vacío, que app/main.py interpreta como "no se entendió la consulta".
        logger.exception("Error transcribiendo el audio con faster-whisper")
        return ""
