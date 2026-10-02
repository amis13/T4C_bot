# Bot de Discord para Talent4Cyber — Diseño

Fecha: 2026-10-02

## Objetivo

Bot para el servidor de Discord del grupo que participa en Talent4Cyber. Da
acceso rápido a los Notion de estudio (eJPT, eCPPT y el del grupo) desde un
mensaje principal con botones, y permite consultar un modelo local servido por
LM Studio con el comando `/ia`.

Éxito: un miembro del servidor abre cualquiera de los tres Notion con un clic
desde el panel, y obtiene una respuesta del modelo local escribiendo
`/ia mensaje:<texto>`.

## Alcance

Dentro:

- `/panel`: publica el mensaje principal con los tres botones.
- `/ia mensaje:<texto>`: pregunta al modelo de LM Studio, sin memoria.
- `/help`: lista los comandos.

Fuera (versiones posteriores): memoria de conversación, comandos por
certificación, info del evento, utilidades de hacking, despliegue en servidor.

## Stack

- Python 3.12, `discord.py` 2.x.
- `aiohttp` (ya es dependencia de `discord.py`) para llamar a LM Studio.
- `python-dotenv` para la configuración.
- `pytest` y `pytest-asyncio` para las pruebas.

## Estructura

```
bot/
  __init__.py
  main.py       arranque del cliente y registro de comandos
  config.py     carga y validación del .env
  panel.py      embed y botones del mensaje principal, comando /panel
  ia.py         comando /ia, cooldown, troceado de la respuesta
  lmstudio.py   cliente HTTP de /v1/chat/completions
  help.py       comando /help
tests/
  test_config.py
  test_lmstudio.py
  test_chunking.py
.env.example
.gitignore
requirements.txt
README.md
```

Cada módulo tiene una responsabilidad. `lmstudio.py` no conoce Discord y
`panel.py` no conoce LM Studio; `main.py` es el único que los une.

## Configuración

Variables del `.env`:

| Variable | Obligatoria | Valor por defecto |
|---|---|---|
| `DISCORD_TOKEN` | sí | — |
| `GUILD_ID` | sí | — |
| `NOTION_EJPT_URL` | sí | — |
| `NOTION_ECPPT_URL` | sí | — |
| `NOTION_GRUPO_URL` | sí | — |
| `LMSTUDIO_BASE_URL` | no | `http://localhost:1234/v1` |
| `LMSTUDIO_MODEL` | no | vacío (LM Studio usa el modelo cargado) |
| `LMSTUDIO_TIMEOUT` | no | `120` (segundos) |

`config.py` expone una dataclass inmutable `Config` y una función
`load_config(env)` que recibe un diccionario. Si falta una variable obligatoria,
`GUILD_ID` no es un entero o una URL de Notion no empieza por `http://` o
`https://`, lanza `ConfigError` con un mensaje que nombra la variable. `main.py`
captura ese error, lo imprime y termina con código 1.

El `.env` real no se versiona.

## Comandos

Los comandos se registran solo en el servidor `GUILD_ID`, para que aparezcan al
instante. El bot no necesita intents privilegiados.

### `/panel`

- Restringido a miembros con permiso "Gestionar servidor".
- Publica en el canal un embed con el título del grupo y una descripción breve,
  más tres botones de tipo enlace: eJPT, eCPPT y Grupo.
- Al ser botones de enlace, no generan interacciones: siguen funcionando aunque
  el bot esté apagado y no hace falta vista persistente.
- Responde al autor con una confirmación efímera.

### `/ia mensaje:<texto>`

1. Comprueba el cooldown de 10 s por usuario. Si no ha pasado, responde con un
   mensaje efímero indicando los segundos restantes.
2. Difiere la respuesta (`defer`), porque el modelo local puede tardar más de
   los 3 s que da Discord.
3. Adquiere un `asyncio.Lock` global, de modo que solo hay una petición al
   modelo a la vez.
4. Llama a `LMStudioClient.chat(system_prompt, mensaje)`.
5. Trocea la respuesta en bloques de 2000 caracteres como máximo y los envía.
   El primero cita la pregunta del usuario.

El system prompt es fijo: asistente de ciberseguridad para un grupo que prepara
eJPT y eCPPT, que responde en español y de forma concisa.

Todos los envíos usan `AllowedMentions.none()`, de modo que el texto del modelo
no puede mencionar a `@everyone`, roles ni usuarios.

### `/help`

Embed efímero con los tres comandos y una línea de descripción cada uno.

## Cliente de LM Studio

`LMStudioClient(base_url, model, timeout)` con un método:

```python
async def chat(self, system: str, user: str) -> str
```

Hace `POST {base_url}/chat/completions` con los mensajes `system` y `user`. Si
`model` está vacío, omite el campo. Devuelve
`choices[0].message.content` sin espacios sobrantes.

Errores, todos como subclases de `LMStudioError`:

| Situación | Excepción | Mensaje al usuario |
|---|---|---|
| No se puede conectar | `LMStudioUnavailable` | El modelo no está disponible ahora mismo. |
| Se supera el timeout | `LMStudioTimeout` | El modelo ha tardado demasiado en responder. |
| HTTP distinto de 200, o respuesta sin `choices` o vacía | `LMStudioBadResponse` | El modelo ha devuelto una respuesta no válida. |

`ia.py` captura `LMStudioError`, responde con el mensaje efímero
correspondiente y registra el detalle en el log. El cooldown no se consume
cuando la llamada falla.

## Troceado

`chunk_text(text, limit=2000) -> list[str]` es una función pura. Corta
preferentemente en saltos de línea, después en espacios, y solo parte una
palabra si ella sola supera el límite. Nunca devuelve trozos vacíos ni mayores
que `limit`.

## Red: WSL y Windows

LM Studio corre en Windows y el proyecto está en una ruta accesible desde WSL.
`LMSTUDIO_BASE_URL` cubre los dos casos:

- Bot con Python de Windows: el valor por defecto funciona.
- Bot en WSL: activar "Serve on Local Network" en LM Studio y apuntar la
  variable a la IP del host de Windows.

El README documenta ambos.

## Pruebas

- `test_config.py`: carga correcta, variable obligatoria ausente, `GUILD_ID` no
  numérico, URL no válida, valores por defecto.
- `test_lmstudio.py`: contra un servidor `aiohttp` de prueba levantado en local.
  Respuesta correcta, campo `model` omitido cuando está vacío, HTTP 500,
  respuesta sin `choices`, timeout y puerto cerrado.
- `test_chunking.py`: texto corto, corte en salto de línea, corte en espacio,
  palabra más larga que el límite, texto vacío.

Los comandos de Discord no tienen pruebas automáticas: se verifican a mano en el
servidor siguiendo el README, porque requieren el token y el servidor reales.

## Puesta en marcha (README)

1. Crear la aplicación y el bot en el portal de desarrolladores de Discord.
2. Invitarlo con los scopes `bot` y `applications.commands` y los permisos
   "Enviar mensajes" e "Insertar enlaces".
3. Copiar `.env.example` a `.env` y rellenarlo.
4. Instalar dependencias y ejecutar `python -m bot.main`.
5. Arrancar el servidor de LM Studio con un modelo cargado.
