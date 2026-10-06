# Memoria y streaming para `/ia` — Diseño

Fecha: 2026-10-06

## Objetivo

Dar a `/ia` dos capacidades que hoy no tiene:

1. **Memoria de conversación por canal**: las preguntas dejan de ser
   independientes. Dentro de un canal, los dos miembros del equipo suman
   contexto a un mismo hilo mental mientras trabajan la misma máquina o
   servicio durante el A&D.
2. **Respuesta en streaming**: el modelo tarda, y hoy el usuario ve un
   "pensando…" congelado hasta que llega el bloque completo. Con streaming la
   respuesta se va mostrando a medida que se genera.

Éxito: dos personas preguntan en el mismo canal y el modelo tiene en cuenta lo
hablado antes; la respuesta aparece progresivamente en vez de de golpe; y un
`/ia-reset` permite empezar limpio al cambiar de objetivo.

## Alcance

Dentro:

- Memoria de conversación **por canal**, persistente en SQLite.
- Recorte de la ventana que se envía al modelo por **presupuesto de tokens**.
- `/ia-reset`: borra la memoria del canal actual.
- Streaming de la respuesta de LM Studio con preview en vivo (enfoque A).
- Cambios de configuración (`IA_HISTORY_TOKENS`, `IA_DB_PATH`) y documentación.

Fuera:

- Memoria por usuario o por hilo (se eligió por canal).
- Resumen automático del historial viejo (se descartó: coste y complejidad).
- Streaming multimensaje puro (enfoque B, descartado por cortes de bloques de
  código y por romper el adjunto `.md`).
- Botones o modales para lanzar `/ia` (descartado: el equipo teclea el comando).

## Decisiones de diseño (y por qué)

- **Ámbito de la memoria: por canal.** Dos ingenieros trabajando el mismo
  objetivo en un canal comparten contexto sin configurar nada. El cooldown y la
  cola siguen siendo por usuario, así que si ambos preguntan a la vez sus turnos
  se intercalan en el mismo historial; es el comportamiento buscado.
- **Persistencia en SQLite.** La competición puede durar días y el bot puede
  reiniciarse (crash, redeploy, recarga de LM Studio). SQLite viene en la stdlib
  (sin dependencias nuevas), tiene escrituras atómicas y aguanta la concurrencia
  mejor que varios JSON.
- **Guardar ≠ enviar.** En disco se guarda todo el historial (barato, no afecta
  a la latencia). Al modelo se envía solo una ventana recortada por tope de
  tokens, de modo que el contexto nunca se desborda ni la generación se
  ralentiza sin control.
- **Recorte por presupuesto de tokens, no por "últimos N turnos".** El equipo
  pega logs, correos y volcados; un solo turno puede ser enorme. Un tope por
  tokens evita que un pegote reviente el contexto. La pregunta actual nunca se
  recorta: va entera siempre.
- **Reset manual, no por caducidad.** El equipo sabe cuándo cambia de objetivo
  mejor que un temporizador; `/ia-reset` es explícito y predecible.
- **Streaming enfoque A (preview en vivo + formateo final).** Da el feedback
  inmediato del streaming en el caso común (respuesta corta) y reutiliza intacta
  la lógica robusta de troceado/adjunto ya probada para el render final. El
  enfoque B partiría bloques de código a mitad y rompería el adjunto `.md`.

## Presupuesto de contexto

Contexto del modelo: 16384. `LMSTUDIO_MAX_TOKENS` (respuesta): 8192. System
prompt: ~1500 tokens. Queda ~6700 para pregunta + historial.

- `IA_HISTORY_TOKENS` por defecto **3000** (≈ 3-4 intercambios normales, menos si
  hay pegotes grandes), configurable por env.
- La estimación de tokens es aproximada por caracteres (constante
  caracteres-por-token, sin tokenizer exacto). Sirve para recortar, no para
  contar con precisión.
- Si el equipo quiere más historial, baja `LMSTUDIO_MAX_TOKENS` y sube
  `IA_HISTORY_TOKENS` sin tocar código.
- LM Studio (llama.cpp) reutiliza la caché KV del prefijo común, así que una
  pregunta de seguimiento no reprocesa toda la conversación desde cero; el
  recorte invalida caché solo cuando descarta turnos viejos.

## Componentes

### `bot/memory.py` (nuevo) — `ConversationStore`

Almacén de conversación respaldado por SQLite.

- Esquema: `messages(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER,
  ts REAL, role TEXT, content TEXT)`, con índice por `channel_id`.
- `append(channel_id, role, content)`: inserta un turno.
- `window(channel_id, budget_tokens) -> list[dict]`: recupera los mensajes del
  canal del más reciente al más viejo, acumula hasta `budget_tokens` (estimados)
  y los devuelve en orden cronológico como `[{"role", "content"}, ...]`.
- `reset(channel_id)`: borra todos los mensajes del canal.
- Las llamadas a SQLite son bloqueantes; se ejecutan en `asyncio.to_thread` para
  no bloquear el event loop. Conexión con `check_same_thread=False` protegida por
  un lock interno, o conexión por operación (a elegir en implementación; el
  volumen es bajo).
- Estimación de tokens: `estimate_tokens(text)` por caracteres.

### `bot/lmstudio.py` (cambios)

- `chat(messages)` pasa a aceptar una **lista de mensajes** (`[{"role",
  "content"}, ...]`) en vez de `(system, user)`. El payload usa esa lista.
- `stream_chat(messages)`: async iterator. Payload con `"stream": true`; parsea
  SSE línea a línea (prefijo `data: `), corta en `data: [DONE]`, emite el texto
  de `choices[0].delta.content`. Guarda el último `finish_reason`.
- Manejo de `<think>`:
  - Texto final (para guardar y para el render): se aplica `_strip_reasoning`
    como hoy.
  - En vivo: máquina de estados que oculta el contenido mientras está dentro de
    `<think>` y empieza a mostrar la respuesta al cerrar `</think>`. Contempla el
    caso de delta separada (`reasoning_content`) si el modelo la emite, además
    del `<think>` inline.
- Errores: se conservan las clases actuales (`LMStudioUnavailable`,
  `LMStudioTimeout`, `LMStudioBadResponse`, `LMStudioTruncated`). Con
  `finish_reason == "length"` se lanza `LMStudioTruncated`.

### `bot/ia.py` (cambios)

- `answer_question` construye `[{"role": "system", ...}] + window(canal) +
  {"role": "user", "content": pregunta}` y llama a `stream_chat`.
- Preview en vivo (enfoque A):
  - Mientras el estado es "pensando" (dentro de `<think>`): el mensaje muestra
    `🤔 pensando…`.
  - Tras cerrar el razonamiento: se edita el mensaje con la cita de la pregunta
    + respuesta parcial, **con throttling de ~1s** entre ediciones (respeta el
    rate limit de Discord, ~5 ediciones/5s por canal).
  - Si el preview supera ~1900 caracteres, se congela el vivo con un aviso de
    "respuesta larga" y se espera al formateo final.
- Render final: al terminar la generación se usa tal cual
  `format_reply`/`chunk_text`/adjunto `.md` actuales para dejar el resultado
  bien formateado (bloques de código intactos, adjunto si procede).
- Memoria: se guardan pregunta + respuesta **solo si la generación tuvo éxito**.
  Timeout, error o truncado → comportamiento actual (borra el preview público,
  aviso ephemeral) y **no se guarda nada** (sin turnos huérfanos).
- `/ia-reset`: comando sin `default_permissions` de admin (lo usa el equipo),
  `guild_only`, llama a `store.reset(interaction.channel_id)` y confirma de forma
  ephemeral.

### `bot/config.py` (cambios)

- `IA_HISTORY_TOKENS`: entero > 0, por defecto 3000.
- `IA_DB_PATH`: ruta del fichero SQLite, por defecto `ia_history.db`.
- Validación consistente con el resto (`_max_tokens`-style para el entero).

### `bot/main.py` (cambios)

- Instancia `ConversationStore(config.ia_db_path)` y la pasa al `register` de
  `ia.py`. Registra `/ia-reset`.

## Flujo de datos

```
/ia mensaje:<texto>
  -> admission/cooldown (por usuario, como hoy)
  -> defer(thinking=True)
  -> messages = [system] + store.window(channel, IA_HISTORY_TOKENS) + user
  -> async for delta in client.stream_chat(messages):
       acumula; si cerró <think>, edita el mensaje cada ~1s (preview)
  -> al terminar:
       si éxito:  render final (chunk_text / .md); store.append(user); store.append(assistant)
       si error:  delete preview + aviso ephemeral; no se guarda nada
```

## Manejo de errores

- Igual que hoy para timeout / indisponible / respuesta inválida / truncado: se
  borra la respuesta pública en curso y se avisa en ephemeral solo a quien
  preguntó.
- Truncado (`finish_reason == "length"`): se trata como error, no se publica la
  respuesta parcial como definitiva ni se guarda en memoria.
- Fallo de SQLite al leer la ventana: se degrada a conversación sin historial
  (se registra en log, no se interrumpe la respuesta). Fallo al guardar: se
  registra en log; la respuesta ya se ha mostrado.

## Pruebas

Con fakes, sin LM Studio ni Discord reales (como el resto de la suite).

- `test_memory.py`: `append`/`window`/`reset`; recorte por presupuesto (un
  pegote grande deja menos turnos); aislamiento por canal; persistencia
  (reabrir el store ve lo guardado).
- `test_lmstudio.py` (amplía): parseo de SSE, acumulación de deltas, corte en
  `[DONE]`, `finish_reason == "length"` → `LMStudioTruncated`, strip de
  `<think>` incremental y con delta `reasoning_content`.
- `test_ia_command.py` (amplía): el historial del canal se pasa al cliente; un
  fallo no guarda nada; la ruta de truncado; `/ia-reset` limpia el canal.
- `test_config.py` (amplía): `IA_HISTORY_TOKENS` e `IA_DB_PATH` por defecto y
  validación.

## Compatibilidad y migración

- Cambiar la firma de `chat()` rompe a sus llamadores actuales; se actualizan en
  el mismo cambio (`ia.py` y tests). `aiinit.py` usa `set_model`, no `chat`, y no
  se ve afectado.
- El fichero SQLite se crea al vuelo si no existe. No hay datos previos que
  migrar.
- `.env.example` y `README.md` se actualizan con las dos variables nuevas.
