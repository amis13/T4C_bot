# Bot de Discord · Talent4Cyber

Bot del grupo para Talent4Cyber: un panel con botones a los Notion de eJPT, eCPPT
y el grupo, y un comando `/ia` conectado a un modelo local en LM Studio.

## Comandos

| Comando | Qué hace |
|---|---|
| `/panel` | Publica el mensaje principal con los tres botones. Requiere "Gestionar servidor". |
| `/ia mensaje:<texto>` | Pregunta al modelo de LM Studio. Sin memoria, 10 s de espera por usuario. |
| `/help` | Lista los comandos. |

## 1. Crear el bot en Discord

1. En <https://discord.com/developers/applications>, crea una aplicación.
2. En **Bot**, pulsa **Reset Token** y copia el token. No hace falta activar
   ningún intent privilegiado.
3. En **OAuth2 → URL Generator**, marca los scopes `bot` y
   `applications.commands`, y los permisos **Send Messages** y **Embed Links**.
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

## 3. Arrancar LM Studio

En LM Studio, carga un modelo y arranca el servidor en la pestaña **Developer**
(puerto 1234).

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

1. `/help` muestra los tres comandos.
2. `/panel` publica el mensaje y los tres botones abren su Notion.
3. `/ia mensaje:¿qué es nmap?` responde con el modelo.
4. Con el servidor de LM Studio parado, `/ia` avisa de que el modelo no está
   disponible.

## Tests

```bash
.venv-wsl/bin/python -m pytest -q
```
