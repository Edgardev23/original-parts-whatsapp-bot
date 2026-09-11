#  Chatbot de WhatsApp (Muestra / POC)

Backend funcional de un chatbot de WhatsApp para Original Parts (repuestos
de motos Suzuki). Un cliente escribe o manda un audio preguntando por un
repuesto y el bot responde con precio y unidades disponibles, consultados
en tiempo real desde un Google Sheet — con memoria de la conversación,
reconocimiento de jerga regional ("cojinetes" = "rodamientos", etc.) y una
personalidad cálida.

**Alcance actual:** catálogo completo (todas las referencias que tengas
cargadas en el Sheet), texto y audio, conversación con memoria. Fuera de
alcance por ahora: interpretación de fotos, pagos, gestión de pedidos, y
número de WhatsApp de producción (se usa el Sandbox de Twilio).

## Arquitectura

```
Cliente WhatsApp
      │ (texto o audio)
      ▼
Twilio WhatsApp Sandbox ──► Webhook FastAPI (vía túnel ngrok)
                                 │
                                 ├─ audio → faster-whisper (transcripción local)
                                 │
                                 ├─ Google Sheets (gspread, tiempo real)
                                 │     ├─ pestaña principal → catálogo completo
                                 │     └─ pestaña "Sinonimos" → jerga regional (opcional)
                                 │
                                 ├─ Claude Haiku, con:
                                 │     ├─ el catálogo completo como contexto
                                 │     ├─ el historial reciente de ESA conversación
                                 │     └─ el glosario de sinónimos
                                 │
                                 └─ respuesta en lenguaje natural → TwiML → WhatsApp
```

La "inteligencia" no es un simple if/else: cada respuesta la redacta
Claude viendo el catálogo completo y lo que se ha hablado antes en esa
conversación, así que puede sumar precios, recordar referencias anteriores
("ese", "los dos anteriores") y reconocer sinónimos con seguridad.

## 1. Requisitos previos

- Python 3.10 o superior.
- Una cuenta de Twilio, **ya graduada de Trial** (con tarjeta agregada) si quieres probar audio.
- Un proyecto de Google Cloud con una Service Account (acceso de solo lectura a Sheets).
- Una API key de Anthropic con saldo cargado.
- Una cuenta gratuita de [ngrok](https://ngrok.com/) con un dominio estático reservado.

## 2. Instalación

```bash
cd original-parts-bot
python3 -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

> Si mueves esta carpeta a otra ubicación o a otro disco, borra `.venv` y
> vuelve a crearlo (`rm -rf .venv`) — el entorno virtual queda con rutas
> absolutas "quemadas" a la ubicación original y deja de funcionar si se
> mueve la carpeta.

## 3. Configuración (`.env`)

```bash
cp .env.example .env
```

Completa cada variable en `.env`. Si falta alguna al arrancar el
servidor, el bot te lo dirá con un mensaje claro (no un error críptico).

### 3.1 Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER`)

1. Crea una cuenta en [twilio.com/try-twilio](https://www.twilio.com/try-twilio).
2. En la [Consola de Twilio](https://console.twilio.com), copia tu **Account SID** y tu **Auth Token** (dashboard principal) → pégalos en `.env`.
3. Activa el WhatsApp Sandbox: la configuración de sandbox se maneja desde
   la **consola clásica ("legacy")** de Twilio, no desde la consola nueva:
   **[twilio.com/console/sms/whatsapp/sandbox](https://www.twilio.com/console/sms/whatsapp/sandbox)**
   (la consola nueva ya no tiene esta pantalla — es un cambio reciente de Twilio).
4. Desde tu celular, envía por WhatsApp el código "join `<palabra>`" que te
   indique esa pantalla, al número que te asignen (varía por cuenta).
5. En `.env`, `TWILIO_WHATSAPP_NUMBER` puedes dejarlo como
   `whatsapp:+14155238886` — esta variable no se usa para enviar mensajes
   (Twilio responde solo dentro del mismo hilo del sandbox), así que su
   valor exacto no es crítico.

> **Para que el audio funcione**, la cuenta debe estar graduada (no
> Trial): consola de Twilio → botón **"Upgrade"** → agregar tarjeta (no
> cobra de inmediato, conserva el saldo de prueba). En Trial, Twilio
> bloquea la descarga de media con `401 - This feature is not available
> on a Trial account`, aunque las credenciales sean correctas.

### 3.2 Google Sheets (`GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_SHEET_ID`)

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita la **Google Sheets API**: [console.cloud.google.com/apis/library/sheets.googleapis.com](https://console.cloud.google.com/apis/library/sheets.googleapis.com).
3. Crea una Service Account: **IAM y administración → Cuentas de servicio → Crear cuenta de servicio**.
4. Si al crear la clave te sale el error *"La creación de claves de la cuenta de servicio está inhabilitada"* (política `iam.disableServiceAccountKeyCreation`, común en proyectos nuevos): ve a **Políticas de la organización**, busca esa restricción, click **Administrar política → Editar → Anular política del elemento superior → regla "No aplicada" → Configurar política**. Espera 1-2 min y reintenta.
5. Dentro de la Service Account: pestaña **Claves → Agregar clave → Crear clave nueva → JSON**. Se descarga un `.json`.
6. Copia ese archivo a `credentials/service_account.json` dentro de este proyecto (ver [credentials/README.md](credentials/README.md)).
7. Abre el JSON y copia el valor de `client_email`.
8. Crea el Google Sheet siguiendo [seed_sheet_data.md](seed_sheet_data.md) (catálogo + pestaña opcional de sinónimos) y compártelo (botón "Compartir") con ese `client_email`, permiso **Viewer** (solo lectura) es suficiente — el bot nunca escribe en el Sheet.
9. Copia el ID del Sheet (parte de la URL entre `/d/` y `/edit`) en `GOOGLE_SHEET_ID` dentro de `.env`.

### 3.3 Anthropic (`ANTHROPIC_API_KEY`)

1. Crea una cuenta en [console.anthropic.com](https://console.anthropic.com/) — **ojo:** esto es independiente de una suscripción a Claude.ai (Pro/Max); son facturaciones distintas.
2. **Settings → Billing** → agrega saldo (con $5 USD alcanza de sobra para todo el POC).
3. **Settings → API Keys → Create Key** → copia la key en `.env`.

## 4. Poblar el Google Sheet

Sigue [seed_sheet_data.md](seed_sheet_data.md) para las columnas exactas
del catálogo y el formato de la pestaña opcional `Sinonimos`.

## 5. Levantar el servidor local

Con el entorno virtual activado (`source .venv/bin/activate`):

```bash
uvicorn app.main:app --port 8000
```

Deberías ver `Uvicorn running on http://127.0.0.1:8000`. Si falta alguna
variable en `.env`, el servidor no arranca y verás exactamente cuál falta.

Para desarrollo (que reinicie solo al guardar cambios en el código):

```bash
uvicorn app.main:app --port 8000 --reload
```

> ⚠️ Cada reinicio del servidor borra la memoria de las conversaciones en
> curso (vive en RAM, no en disco). Evita reiniciar a mitad de una demo.

## 6. Exponer el servidor con ngrok (dominio fijo)

**Primera vez únicamente** — crear cuenta y reservar el dominio:

1. Cuenta gratis: [dashboard.ngrok.com/signup](https://dashboard.ngrok.com/signup).
2. Copia tu authtoken: [dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken).
3. Reserva un dominio estático gratis: [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains) → **+ New Domain**.
4. Descarga el binario (Linux x86_64) y guarda tu authtoken:
   ```bash
   curl -s -L https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -o ngrok.tgz
   tar -xzf ngrok.tgz && rm ngrok.tgz
   ./ngrok config add-authtoken TU_AUTHTOKEN_AQUI
   ```

**Cada vez que quieras exponer el servidor** (con el servidor del paso 5 ya corriendo, en otra terminal):

```bash
./ngrok http --url=https://TU-DOMINIO.ngrok-free.dev 8000
```

Reemplaza `TU-DOMINIO.ngrok-free.dev` por el que reservaste — **no
cambia entre sesiones**, así que el webhook de Twilio solo se configura
una vez (ver siguiente paso).

## 7. Configurar el webhook en Twilio

1. Ve a la consola clásica: **[twilio.com/console/sms/whatsapp/sandbox](https://www.twilio.com/console/sms/whatsapp/sandbox)**.
2. En **"WHEN A MESSAGE COMES IN"**, pega tu URL de ngrok + `/webhook/whatsapp`, por ejemplo:
   ```
   https://tu-dominio.ngrok-free.dev/webhook/whatsapp
   ```
3. Método: **HTTP POST**. Clic en **Save**.

Como el dominio de ngrok es fijo, **este paso normalmente solo se hace una vez** — no hace falta repetirlo cada vez que reinicies el servidor o el túnel, solo si cambias de dominio.

## 8. Arrancar todo junto (referencia rápida)

Dos terminales, con el entorno ya instalado (pasos 1-4 ya hechos):

```bash
# Terminal 1 — el servidor
cd original-parts-bot
source .venv/bin/activate
uvicorn app.main:app --port 8000

# Terminal 2 — el túnel
cd original-parts-bot
./ngrok http --url=https://TU-DOMINIO.ngrok-free.dev 8000
```

Deja ambas terminales abiertas mientras quieras que el bot responda por WhatsApp.

## 9. Probar de punta a punta

1. Desde tu celular (ya unido al sandbox, ver 3.1), escríbele al bot por WhatsApp.
2. **Texto:** *"tienen filtro de aceite?"* → responde con precio y unidades reales del Sheet.
3. **Audio:** graba una nota de voz preguntando lo mismo → se transcribe localmente y responde igual (la primera vez tarda más porque descarga el modelo de Whisper, ~1 min; luego es cuestión de segundos).
4. **Conversación con memoria:** pregunta por dos repuestos distintos y luego *"¿cuánto sería el total de esos dos?"* → debe sumarlos correctamente.
5. **Jerga regional:** prueba con sinónimos (ej. "cojinetes" en vez de "rodamientos") → debe responder con seguridad, no con dudas.
6. **Repuesto no disponible:** pregunta por algo que no esté en el catálogo → debe decirlo con honestidad y, si aplica, sugerir algo parecido.
7. Revisa la consola donde corre `uvicorn`: cada etapa (mensaje recibido, transcripción si aplica, consulta a Sheets, llamada al LLM, respuesta enviada) queda logueada para depurar en vivo.

## Limitaciones actuales

- El Sandbox de Twilio requiere que cada número se "una" con un código; no es un número de producción abierto al público.
- La memoria de la conversación vive en RAM del servidor: se pierde si el proceso se reinicia.
- Las sumas de precios las hace el modelo (Claude), no una calculadora determinística — muy confiable con montos redondos, pero no 100% garantizado matemáticamente.
- `faster-whisper` en CPU (sin GPU) tarda unos segundos extra en audios largos.
- No incluye pagos ni gestión de pedidos/despachos.

## Siguientes pasos (si el cliente aprueba la muestra)

- **Base de conocimiento técnico ("manual de mecánica"):** darle al bot contexto adicional (más allá del catálogo de precios) sobre qué componentes incluye un kit, o recomendaciones de mantenimiento (ej. "al cambiar el aceite, recuerda también el filtro"). Se puede extender el mismo patrón que ya usamos para sinónimos (una fuente de datos editable, sin tocar código) o pasar a una búsqueda tipo RAG si el manual crece mucho.
- Fase 1: interpretación de fotos de piezas/carenajes.
- Fase 2: pasarela de pagos y flujo de despacho.
- Migración del Sandbox de Twilio a la API oficial de WhatsApp Business (Meta) para producción.
