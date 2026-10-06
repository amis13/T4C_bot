# Bot de Discord · Talent4Cyber

Bot del grupo para Talent4Cyber: un panel con botones a los Notion de eJPT, eCPPT
y el grupo, y un comando `/ia` conectado a un modelo local en LM Studio.

## Comandos

| Comando | Qué hace |
|---|---|
| `/panel` | Publica el mensaje principal: botones a los tres Notion y a los recursos de competición (Exploit-DB, GTFOBins, HackTricks…). Requiere "Gestionar servidor". |
| `/ia mensaje:<texto>` | Pregunta al modelo de LM Studio. Con memoria por canal, respuesta en streaming, 10 s de espera por usuario, una pregunta en curso por persona y 4 pendientes como máximo. |
| `/ia-reset` | Borra la memoria de conversación del canal actual. |
| `/initai` | Comprueba y aplica el preset de Qwythos; carga o recarga solo si hace falta. Requiere "Gestionar servidor". |
| `/help` | Lista los comandos. |

## 1. Crear el bot en Discord

1. En <https://discord.com/developers/applications>, crea una aplicación.
2. En **Bot**, pulsa **Reset Token** y copia el token. No hace falta activar
   ningún intent privilegiado.
3. En **OAuth2 → URL Generator**, marca los scopes `bot` y
   `applications.commands`, y los permisos **Send Messages**, **Embed Links** y **Attach Files**.
   Abre la URL generada e invita el bot a tu servidor.
4. En Discord, activa **Ajustes → Avanzado → Modo desarrollador**, haz clic
   derecho en el servidor y pulsa **Copiar ID del servidor**.

## 2. Configurar

Copia `.env.example` a `.env` y rellénalo:

| Variable | Descripción |
|---|---|
| `DISCORD_TOKEN` | Token del bot. |
| `GUILD_ID` | ID del servidor. |
| `NOTION_EJPT_URL` | Enlace al Notion de eJPT. |
| `NOTION_ECPPT_URL` | Enlace al Notion de eCPPT. |
| `NOTION_GRUPO_URL` | Enlace al Notion del grupo. |
| `LMSTUDIO_BASE_URL` | Opcional. Por defecto `http://localhost:1234/v1`. |
| `LMSTUDIO_MODEL` | Opcional. Vacío usa el modelo cargado en LM Studio. |
| `LMSTUDIO_TIMEOUT` | Opcional. Segundos de espera, por defecto `120`. |
| `LMSTUDIO_MAX_TOKENS` | Opcional. Límite de generación, incluido razonamiento, por defecto `8192`. |
| `LMSTUDIO_AUTO_INIT` | Opcional. `true` configura el modelo al arrancar el bot; por defecto `false`. |
| `IA_HISTORY_TOKENS` | Opcional. Presupuesto de tokens de historial que se envía al modelo, por defecto `3000`. |
| `IA_DB_PATH` | Opcional. Fichero SQLite de la memoria, por defecto `ia_history.db`. |

## 3. Arrancar LM Studio

En LM Studio, carga un modelo y arranca el servidor en la pestaña **Developer**
(puerto 1234).

### Inicialización automática o con `/initai`

Con LM Studio y su servidor ya arrancados, `/initai` aplica este preset para
Qwythos MTP Q8_0: contexto 16384, concurrencia 1, GPU 29/33 capas y MTP activo.
Comprueba la configuración efectiva; si ya coincide, no recarga. Comparte el
bloqueo con `/ia`, de modo que espera a la generación en curso antes de recargar.
El resultado se comunica en privado. No arranca la aplicación LM Studio ni
descarga modelos, y no modifica los perfiles guardados en la interfaz.

Para ejecutar la misma comprobación al iniciar el bot, configura:

```dotenv
LMSTUDIO_MODEL=qwythos-9b-v2-mtp
LMSTUDIO_AUTO_INIT=true
```

El modelo debe existir en `GET /api/v1/models`: usa su clave o el ID de una
instancia cargada. Si usas un alias personalizado que desaparece al descargar
el modelo, configura la clave del catálogo. Un fallo de inicialización se
registra y deja el bot disponible para reintentar con `/initai`.

La configuración avanzada usa el protocolo WebSocket de LM Studio, comprobado
con la versión 0.4.25; las claves están aisladas en `bot/aiinit.py`. Si una futura
versión cambia ese protocolo, el comando avisa del error. Una carga fallida
después de descargar la instancia puede requerir cargarla manualmente.

### Qwythos para pentesting y blue team

El prompt mantiene funciones generales de red team y blue team e incluye el
briefing provisional de **Operación Estrecho Fantasma**. Cubre reconstrucción,
OSINT, criptografía, forense, malware, firmware, AIS y decisiones de contención.
Trata las pistas como contexto por confirmar y contempla infraestructura
compartida, continuidad de servicios, reversión, reglas de enfrentamiento y
comunicados con información sensible. No debe atribuir incidentes sin evidencias.
El escenario no se impone a preguntas generales de otras plataformas.

Para obtener respuestas útiles, incluye en cada `/ia` el objetivo o disciplina,
plataforma, evidencias, alcance y restricciones disponibles. Por ejemplo:
`/ia mensaje:Blue team, escenario compartido: necesito aislar un segmento sospechoso manteniendo el panel portuario disponible. Aún no tengo la topología. ¿Qué datos recopilo antes de decidir?`

El modelo utilizado es `Qwythos-9B-v2-MTP-Q8_0.gguf` (9,79 GB), de
[Empero AI](https://huggingface.co/empero-ai/Qwythos-9B-v2-GGUF).
Pon en `LMSTUDIO_MODEL` el identificador que publica `GET /v1/models`
(por ejemplo, `qwythos-9b-v2-mtp`), no el nombre del archivo por suposición.
Deja la plantilla Qwen3.5 que incorpora el GGUF: LM Studio la aplica al chat.
Tener el archivo MTP no demuestra que la aceleración MTP esté activa;
comprueba el soporte y los registros del motor instalado.

El bot envía `temperature=0.6`, `top_p=0.95` y `top_k=20`, siguiendo la
ficha del modelo. Limita la generación a 8192 tokens para el uso compartido;
la ficha recomienda hasta 16384. El razonamiento consume parte de ese presupuesto
y se elimina antes de publicar. Si el servidor indica `finish_reason=length`,
el bot avisa en privado y descarta la respuesta incompleta.

Con una RTX 4070 de 12 GB y 64 GB de RAM, prueba un contexto de 16384 como
punto de partida y comprueba VRAM, descarga a CPU y velocidad real: el tamaño
del archivo no incluye caché de contexto ni memoria de ejecución. Aumentar
contexto o generación puede requerir más memoria y tiempo. No configures
el millón de tokens anunciado para este uso.

`/ia` acepta hasta 4000 caracteres y la respuesta es pública. Incluye objetivo,
plataforma y evidencias relevantes en la pregunta. Procesa una petición a la vez, admite cuatro entre activas y pendientes,
y limita a 600 segundos la espera total por petición, incluida la cola, para
dejar margen antes de caducar la interacción de Discord. El timeout HTTP sigue
siendo `LMSTUDIO_TIMEOUT`. El bot propone pasos; no ejecuta comandos ni consulta
Internet o archivos.

### Memoria por canal y streaming

Cada canal tiene su propia conversación: `/ia` envía al modelo los turnos
recientes de ese canal, recortados para no superar `IA_HISTORY_TOKENS`. La
memoria se guarda en SQLite (`IA_DB_PATH`), así que sobrevive a reinicios del
bot. `/ia-reset` la borra para el canal actual. Bajo WSL la base de datos se
crea en el directorio de trabajo salvo que fijes `IA_DB_PATH`; `ia_history.db`
está en `.gitignore`.

La respuesta se muestra en streaming: un mensaje de vista previa se va
actualizando mientras el modelo genera y, al terminar, se sustituye por la
respuesta final con formato.

Las respuestas largas se dividen en mensajes de hasta 2000 unidades UTF-16,
conservando el lenguaje y la sangría de los bloques de código. Si hay varias
partes, el primer mensaje incluye `respuesta-ia.md` con la pregunta y la respuesta
completas, para copiar comandos sin los cortes de Discord. Si harían falta más
de seis mensajes, se publica un aviso y el archivo completo.

Antes del evento, prueba ambos casos y mide cuánto tardan:

- Pentesting: `/ia mensaje:CTF autorizado: host Linux con SSH y HTTP. ¿Qué datos de enumeración recojo primero y cómo interpreto los resultados?`
- Blue team: `/ia mensaje:Windows: varios eventos 4625 y después un 4624 desde la misma IP. ¿Qué campos correlaciono y qué evidencias preservo antes de contener?`

Comprueba también una respuesta larga, una pregunta en cola y LM Studio apagado.
No pegues tokens ni credenciales; confirma que los comandos y consultas propuestos
corresponden a la plataforma y versiones del ejercicio.

En la prueba local del 2026-10-02, las consultas breves de pentesting y blue team
tardaron aproximadamente 23 y 18 segundos. Tras reforzar el idioma, ambas
respondieron en español. Esto no certifica precisión: la respuesta de Windows
confundió el identificador de evento con el campo `Logon Type`, y la de Linux
propuso una ruta de claves SSH incorrecta. Contrasta los detalles con evidencias
y documentación antes de usarlos durante la competición.

## 4. Ejecutar el bot

En Windows (PowerShell), que es lo más simple porque LM Studio queda en
`localhost`:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m bot.main
```

En WSL, LM Studio no está en `localhost`. Activa **Serve on Local Network** en
LM Studio y pon en el `.env` la IP de Windows:

```bash
python3 -m venv .venv-wsl
.venv-wsl/bin/python -m pip install -r requirements.txt
echo "LMSTUDIO_BASE_URL=http://$(ip route show default | awk '{print $3}'):1234/v1"
.venv-wsl/bin/python -m bot.main
```

## 5. Probar en Discord

1. `/help` muestra los comandos.
2. `/panel` publica el mensaje; los botones abren los Notion y los recursos.
3. `/ia mensaje:¿qué es nmap?` responde con el modelo.
4. Con el servidor de LM Studio parado, `/ia` avisa de que el modelo no está
   disponible. Compruébalo con una segunda cuenta: el aviso solo debe
   verlo quien preguntó.

## Añadir recursos al panel

Edita la lista `RESOURCES` de `bot/panel.py` (máximo 20) y vuelve a lanzar `/panel`.

## Tests

```bash
.venv-wsl/bin/python -m pytest -q
```
