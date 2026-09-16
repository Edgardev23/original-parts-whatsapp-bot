"""Wrapper de la conversación con el LLM (Claude Haiku), con memoria de la charla.

Versión anterior de este módulo: el modelo solo hacía una tarea muy
acotada ("¿a cuál número de una lista se refiere este ÚNICO mensaje?"),
sin memoria de la conversación. Eso hacía que el bot no pudiera responder
cosas como "¿cuánto sería el total de los repuestos?" (no recordaba
cuáles) o "¿solo tienen ese?" (no entendía a qué "ese" se refería).

Esta versión le da al modelo dos cosas que antes no tenía:
  1. El catálogo COMPLETO como contexto de sistema, para que pueda hablar
     de cualquier referencia, comparar precios, sumar varias, etc.
  2. El HISTORIAL reciente de la conversación con ese cliente (lo maneja
     `app/main.py`), para que entienda referencias a mensajes anteriores.

Con eso, el modelo responde libremente en lenguaje natural — ya no hace
falta pedirle un código MATCH/NO_MATCH/número: el texto que devuelve es
directamente lo que se le manda al cliente por WhatsApp.
"""

from __future__ import annotations

import logging

import anthropic  # SDK oficial de Anthropic para llamar a la API de Claude.

from app.config import settings
from app.formatting import field, format_price

logger = logging.getLogger(__name__)

# Cliente de Anthropic, creado una sola vez al importar el módulo (reutiliza la configuración/conexión
# en vez de crear un cliente nuevo en cada mensaje de WhatsApp).
_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# Plantilla del prompt de sistema. Se completa en cada llamada con el catálogo actual (porque el
# inventario puede cambiar entre una consulta y otra) usando .format(catalog=..., total=..., sinonimos=...).
_SYSTEM_PROMPT_TEMPLATE = """Eres el asistente de WhatsApp de Original Parts, un almacén de repuestos de motos Suzuki en Colombia. Respondes con calidez y cercanía, como lo haría una persona real del negocio — no como un robot.

TODO el catálogo de abajo es EXCLUSIVAMENTE para la moto {moto_model} — no para ninguna otra moto, ni siquiera otro modelo Suzuki. Esto es así aunque un repuesto de la lista tenga un nombre genérico (ej. "Farola", "Filtro de aceite") que en teoría podría existir también para otras motos.

Este es TODO el catálogo disponible ahora mismo (nombre: precio (unidades disponibles)):
{catalog}
{sinonimos}
Reglas importantes:
- ANTES de dar precio o disponibilidad de cualquier repuesto, necesitas saber el modelo y año de la moto del cliente. Revisa PRIMERO con cuidado si esa información ya aparece en ALGÚN mensaje del cliente — incluyendo el mensaje actual, no solo mensajes anteriores. Si el cliente pregunta por un repuesto concreto (ej. "¿tienen filtro de aceite?") y el modelo y año de su moto NO aparecen en ningún mensaje suyo (ni el actual ni los anteriores de esta conversación), tu ÚNICA respuesta debe ser exactamente: "Por favor especifícame el modelo y año de la motocicleta para validar si tenemos el repuesto que estás solicitando." — sin agregar precio, disponibilidad ni nada más en ese mensaje. Si el cliente YA mencionó el modelo y año — aunque sea en ese mismo mensaje junto con el repuesto, por ejemplo "¿Tienen filtro de aceite para una Suzuki AX100 2015?" — NO se lo vuelvas a preguntar: pasa a la siguiente regla para decidir cómo responder. Una vez que el cliente te haya dado el modelo y año en cualquier punto de la conversación, no lo vuelvas a pedir de nuevo. Esta regla no aplica si el cliente todavía no ha mencionado ningún repuesto (ej. un saludo o un mensaje genérico) — ahí sigue la regla de saludos de más abajo.
- En cuanto sepas el modelo de la moto del cliente, compara con cuidado si es {moto_model} (acepta variaciones de escritura: mayúsculas/minúsculas, con o sin espacios/guiones, con o sin la marca — "gn125", "GN-125" y "Suzuki GN 125" cuentan como {moto_model}). Si el modelo del cliente NO es {moto_model} (otro modelo Suzuki como Gixxer, AX100, Best, etc., o de cualquier otra marca), NUNCA confirmes que tienes el repuesto ni des precio, así el nombre del repuesto exista en la lista del catálogo — esa coincidencia de nombre no significa que le sirva a su moto. En ese caso responde con honestidad, algo como: "Por ahora en el catálogo solo manejamos repuestos para {moto_model}, así que no puedo confirmarte disponibilidad para tu moto." Solo si el modelo SÍ es {moto_model} continúas respondiendo normalmente con precio y disponibilidad.
- Solo puedes hablar de los repuestos de esta lista. Si preguntan por algo que no está, dilo con honestidad; solo si tiene sentido, sugiere la referencia más parecida de la lista, de lo contario tu respuesta es "Lo siento, en este momento no disponemos de ese repuesto"
- Usa los precios y unidades EXACTAMENTE como están arriba. Nunca inventes ni redondees un precio.
- Si te piden el total de varios repuestos, súmalos tú mismo con cuidado y muestra el resultado.
- Usa el historial de la conversación para entender referencias como "ese", "los anteriores" o "el mismo".
- Los clientes de un almacén de repuestos de motos en Colombia usan MUCHA jerga regional y sinónimos para la misma pieza (por ejemplo: rodamientos = cojinetes = cunas = balineras; leva = manigueta = palanca). Además de la lista de sinónimos conocidos de arriba (si la hay), usa tu propio conocimiento general de términos automotrices/de motos en Colombia para reconocer con SEGURIDAD a qué pieza de la lista se refiere el cliente, incluso si usa una palabra que no está en el catálogo ni en esa lista. Evita responder con dudas del tipo "no tenemos X, pero lo más parecido es Y" cuando en realidad X y Y son la misma pieza con otro nombre — en ese caso, respóndelo con seguridad como una sola cosa.
- Si te piden ver "todo" el catálogo o una lista completa, NO listes las {total} referencias: menciona cuántas hay en total y muestra 5-6 de ejemplo, invitando a preguntar por algo puntual.
- Sé breve: máximo 4-5 líneas por respuesta (esto es un chat de WhatsApp, no un correo).
- Puedes usar *negrita* (con asteriscos, así se ve en WhatsApp) para nombres de repuestos y montos, y algún emoji ocasional, sin exagerar.
- IMPORTANTE sobre saludos: el sistema YA le mostró al cliente un saludo de bienvenida ("¡Gracias por comunicarte con Original Parts!") justo antes de tu respuesta, en este mismo mensaje. Por eso tu respuesta NUNCA debe incluir saludos de bienvenida propios: nada de "¡Hola!", "Bienvenido/a", "un gusto saludarte", emojis de saludo tipo 👋, ni repetir "gracias por contactarnos" de ninguna forma. Esto aplica SIEMPRE, incluso si el mensaje del cliente es solo "Hola" o un saludo sin pedir nada en concreto — en ese caso tu ÚNICA respuesta debe ser algo corto tipo: "¿En qué repuesto te puedo ayudar hoy? 🔧" (o una variación breve equivalente), sin agregar nada de bienvenida antes.
- Si de verdad no entiendes qué pide el cliente, pide amablemente que reformule.
"""


def _build_catalog_context(catalog: list[dict]) -> str:
    """Arma el bloque de texto del catálogo que se le manda al modelo como contexto.

    Una línea por referencia, ya con el precio formateado ($20.000 en vez
    de 20000), para que el modelo lo repita tal cual en sus respuestas sin
    tener que formatearlo él mismo.
    """
    lineas = [
        f"- {field(item, 'Repuesto', '?')}: {format_price(field(item, 'Precio'))} "
        f"({field(item, 'Unidades disponibles')} unidades)"
        for item in catalog
    ]
    return "\n".join(lineas)


def _build_synonyms_context(synonyms: list[dict]) -> str:
    """Arma el bloque de texto del glosario de sinónimos, si hay alguno cargado.

    Devuelve una cadena vacía si no hay sinónimos (para que simplemente no
    aparezca esa sección en el prompt), en vez de mandar un bloque vacío
    con un título sin contenido.
    """
    lineas = [
        f"- {field(s, 'Repuesto', '?')}: también le dicen {field(s, 'Sinonimos', '')}"
        for s in synonyms
        if field(s, "Sinonimos", "")  # Se salta filas de sinónimos vacías (por si acaso).
    ]
    if not lineas:
        return ""
    return "\nSinónimos conocidos (además de los que ya sepas por tu cuenta):\n" + "\n".join(lineas) + "\n"


def chat_reply(history: list[dict], catalog: list[dict], synonyms: list[dict] | None = None) -> str | None:
    """Genera la respuesta del asistente a partir del historial de la conversación.

    `history` es una lista de mensajes en el formato que espera la API de
    Anthropic: [{"role": "user"|"assistant", "content": "texto"}, ...], ya
    truncada por `app/main.py` a los últimos turnos (para no dejar crecer
    el costo de cada llamada indefinidamente). El último elemento debe ser
    el mensaje más reciente del cliente.

    `synonyms` es la tabla opcional de jerga regional (ver `sheets.get_synonyms`);
    puede venir vacía o None si esa pestaña del Sheet todavía no existe.

    Devuelve el texto de la respuesta, o `None` si hubo un error llamando
    al LLM (el llamador decide qué mensaje de error mostrarle al cliente
    en ese caso).
    """

    # El catálogo (y los sinónimos) se arman de nuevo en cada llamada (no se cachean) porque el
    # inventario puede cambiar entre una pregunta y la siguiente, y siempre queremos reflejar el
    # dato más reciente.
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        catalog=_build_catalog_context(catalog),
        sinonimos=_build_synonyms_context(synonyms or []),
        total=len(catalog),
        moto_model=settings.catalog_moto_model,
    )

    try:
        logger.info(
            "Consultando LLM (%s) con %d mensaje(s) de historial…",
            settings.anthropic_model,
            len(history),
        )
        response = _client.messages.create(
            model=settings.anthropic_model,  # Modelo configurado en .env (Claude Haiku por defecto: barato y rápido).
            max_tokens=350,  # Suficiente para varias líneas de respuesta, incluso con una suma o una lista corta.
            system=system_prompt,
            messages=history,
        )
        # response.content es una lista de bloques (por si el modelo devolviera varios); tomamos el
        # texto del primer bloque y quitamos espacios sobrantes.
        texto = response.content[0].text.strip()
        logger.info("Respuesta del LLM: %r", texto)
        return texto
    except Exception:
        # Cualquier error de red, límite de uso, API caída, etc. se loguea; el llamador decide
        # qué responderle al cliente (normalmente un mensaje de error genérico y amable).
        logger.exception("Error llamando al LLM")
        return None
