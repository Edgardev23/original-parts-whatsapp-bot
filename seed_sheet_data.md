# Datos del Google Sheet

El bot lee dos pestañas del mismo Google Sheet:

1. **La primera pestaña** (el nombre no importa, se toma la primera): el catálogo completo.
2. **Una pestaña llamada exactamente `Sinonimos`** (opcional): jerga regional para ayudar al bot a reconocer distintas formas de nombrar la misma pieza.

## 1. Catálogo (pestaña principal)

Columnas exactas en la primera fila (encabezados):

| Repuesto | Precio | Unidades disponibles |
|---|---|---|
| Rin delantero | 20000 | 2 |
| Rin trasero | 21000 | 3 |
| Bateria | 66000 | 6 |
| ... | ... | ... |

Notas:

- Los encabezados deben coincidir exactamente (`Repuesto`, `Precio`,
  `Unidades disponibles`) — el backend los usa tal cual para leer y
  construir la respuesta.
- El precio se puede dejar como número plano (sin puntos ni símbolo de
  moneda); el bot ya lo formatea al responder (ej. `20000` → `$20.000`).
- Puedes tener tantas filas (referencias) como quieras — el bot lee el
  catálogo completo en cada consulta, en tiempo real.
- Evita dejar celdas de "Unidades disponibles" vacías: si no sabes la
  cantidad exacta, pon `0` en vez de dejarlo en blanco, para que se vea
  más completo en las respuestas (el bot muestra "N/D" si está vacío, pero
  un número real siempre se ve mejor).

## 2. Glosario de sinónimos (pestaña `Sinonimos`, opcional pero recomendada)

Los clientes de un almacén de repuestos de motos usan muchísima jerga
regional para referirse a la misma pieza (ej. "rodamientos" = "cojinetes"
= "cunas" = "balineras"). El modelo ya reconoce bastante de esto por su
cuenta, pero para los términos que ustedes sepan que sus clientes usan
seguido, es mejor no dejarlo a la suerte: agréguenlos aquí.

**Esta pestaña la puede mantener cualquiera del equipo, sin tocar código
ni pedirle nada a un desarrollador** — cada vez que un cliente use una
palabra rara y el bot dude, solo hay que agregar una fila.

Crea una pestaña nueva en el mismo Sheet llamada exactamente `Sinonimos`,
con estas columnas:

| Repuesto | Sinonimos |
|---|---|
| Rodamientos de direccion | cojinetes de direccion, cunas, balineras |
| Rodamientos rueda delantera | cojinetes delanteros, balineras delanteras |
| Rodamientos rueda trasera | cojinetes traseros, balineras traseras |
| Leva de freno | manigueta de freno, palanca de freno |
| Leva de embrague | manigueta de embrague, palanca de embrague, palanca de cloch |
| Bujia | candela |
| Empaques cilindro | juntas de cilindro, empacaduras |
| Pastillas freno delantero | balatas delanteras |
| Bandas freno trasero | balatas traseras, bandas de freno |
| Cable acelerador | guaya del acelerador |
| Cable embrague | guaya del embrague, guaya del cloch |
| Capuchon de bujia | pipeta de bujia |

Notas:

- La columna "Repuesto" debe escribirse **exactamente igual** a como
  aparece en la pestaña principal del catálogo (mayúsculas/minúsculas no
  importan tanto, pero el nombre completo sí).
- En "Sinonimos" pueden ir varios términos separados por coma.
- La tabla de arriba es solo un punto de partida con los ejemplos más
  comunes — agreguen los que vayan escuchando de sus clientes reales; entre
  más completa esté, menos dudas tendrá el bot.
- Si esta pestaña no existe todavía, el bot sigue funcionando normal
  (usa solo el conocimiento general del modelo para reconocer sinónimos).

## Cómo conectar el Sheet al bot

1. Crea o edita el Sheet en [sheets.google.com](https://sheets.google.com).
2. Comparte el Sheet (botón "Compartir") con el `client_email` que aparece
   dentro de tu archivo `credentials/service_account.json` (ver README.md
   para cómo obtenerlo), dándole acceso de **Viewer** (solo lectura) es
   suficiente.
3. Copia el ID del Sheet: es la parte de la URL entre `/d/` y `/edit`, por
   ejemplo:

   ```
   https://docs.google.com/spreadsheets/d/ESTE_ES_EL_ID_DEL_SHEET/edit
   ```

4. Pega ese ID en la variable `GOOGLE_SHEET_ID` de tu archivo `.env`.
