# VideoStudio: comandos para ejecutarlo en Windows

Guía detallada, paso por paso, para instalar y arrancar el programa en tu PC. Cada comando lleva su explicación y lo que debes ver cuando funciona.

> Usa la terminal de **VS Code** (menú **Terminal → Nueva terminal**, o `Ctrl + ñ` / `Ctrl + \``) o el **Símbolo del sistema (cmd)**. Todos los comandos sirven en ambas.

---

## Antes de empezar (una sola vez)

Necesitas estas tres cosas. Compruébalas:

| Programa | Comando | Debe mostrar |
|----------|---------|--------------|
| Python | `python --version` | `Python 3.12.10` (sirve 3.11, 3.12 o 3.13) |
| FFmpeg | `ffmpeg -version` | `ffmpeg version 9.0.2...` |
| FFprobe | `ffprobe -version` | `ffprobe version 9.0.2...` |

Si alguno dice *"no se reconoce como un comando interno o externo"*, ese programa no está en el PATH. Instálalo o agrégalo, **cierra y vuelve a abrir** la terminal y repite la comprobación.

---

## Paso 0: Entrar a la carpeta del proyecto

Los comandos siguientes **solo funcionan si estás dentro de la carpeta del proyecto**, la que contiene `run.py`, `requirements.txt` y la carpeta `app`.

```
cd /d D:\videostudio\videostudio
```

- `cd` cambia de carpeta.
- `/d` permite cambiar también de disco (de `C:` a `D:`). Sin `/d`, Windows no cambia de unidad.
- Ajusta la ruta si tu carpeta está en otro lugar.

**Comprueba que estás en el lugar correcto:**
```
dir
```
Debes ver `app`, `static`, `assets`, `storage`, `run.py`, `requirements.txt` y `.env.example`. Si no los ves, estás en la carpeta equivocada (a veces hay una carpeta `videostudio` dentro de otra `videostudio`: entra a la de adentro).

---

## Paso 1: Crear el entorno virtual

```
python -m venv venv
```

**Qué hace**
- Crea una carpeta llamada `venv` con una copia aislada de Python solo para este proyecto.
- Así las librerías del programa no se mezclan con otras cosas de tu PC.

**Qué verás**
- Tarda unos segundos y no muestra ningún mensaje. Es normal.
- Aparece una carpeta nueva `venv` dentro del proyecto.

**Si falla**
- *"python no se reconoce"*: Python no está en el PATH (ver "Antes de empezar").
- Si ya existe la carpeta `venv`, no pasa nada: puedes saltarte este paso.

---

## Paso 2: Activar el entorno virtual

```
venv\Scripts\activate
```

**Qué hace**
- Activa el entorno: a partir de aquí, `python` y `pip` usan los de la carpeta `venv`.

**Qué verás**
- Aparece `(venv)` al inicio de la línea de la terminal:
```
(venv) D:\videostudio\videostudio>
```

**Importante**
- Tienes que activarlo **cada vez que abras una terminal nueva**.
- Si ves `(venv)`, ya está activo. Si no lo ves, los siguientes comandos fallarán.

**Si usas PowerShell y sale un error rojo de "la ejecución de scripts está deshabilitada"**, ejecuta esto una sola vez:
```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
Responde `S` (o `Y`) y vuelve a activar. Otra opción es usar cmd en vez de PowerShell, o activar con:
```
venv\Scripts\activate.bat
```

---

## Paso 3: Actualizar pip (recomendado)

```
python -m pip install --upgrade pip
```

**Qué hace**
- Actualiza el instalador de librerías. Evita errores al instalar paquetes grandes como `faster-whisper`.

**Qué verás**
- `Successfully installed pip-...` (o `Requirement already satisfied` si ya está al día).

---

## Paso 4: Instalar las dependencias

```
pip install -r requirements.txt
```

**Qué hace**
- Instala todas las librerías del proyecto: `fastapi`, `uvicorn`, `python-multipart`, `python-dotenv`, `requests` y `faster-whisper`.

**Qué verás**
- Muchas líneas de descarga. **Puede tardar varios minutos** (especialmente `faster-whisper`, que arrastra otras librerías pesadas).
- Al final: `Successfully installed ...` con la lista de paquetes.

**Comprobar que quedó bien**
```
pip list
```
Debes ver, entre otros: `fastapi`, `uvicorn`, `faster-whisper`, `python-dotenv`, `requests`.

**Si falla**
- Error con `av` o con compilación: primero ejecuta el Paso 3 (actualizar pip) y repite.
- *Sin conexión / timeout*: revisa tu internet y vuelve a ejecutar el mismo comando; continúa donde se quedó.

---

## Paso 5: Crear el archivo de configuración

```
copy .env.example .env
```

**Qué hace**
- Copia la plantilla `.env.example` a un archivo nuevo llamado `.env`, que es el que el programa lee.

**Qué verás**
- `1 archivo(s) copiado(s).`
- Si `.env` ya existe, Windows pregunta si quieres sobrescribirlo. Responde `N` para conservar el tuyo.

**Para editarlo**
```
notepad .env
```
(O ábrelo en VS Code desde el explorador de archivos; el nombre empieza con punto y a veces queda oculto en el Explorador de Windows.)

**Valores que puedes cambiar**

| Variable | Qué hace | Cuándo cambiarla |
|----------|----------|------------------|
| `APP_PASSWORD` | Contraseña para entrar a la página | Déjala vacía en tu PC. Obligatoria en un servidor público. |
| `TTS_ENGINE` | Voz: `none`, `elevenlabs` o `xtts` | `none` usa el audio que grabes o subas |
| `WHISPER_MODEL` | Tamaño del modelo: `tiny`, `base`, `small`, `medium` | Usa `base` si tu PC va lenta o tiene poca RAM |
| `FONT_NAME` | Fuente de los subtítulos | `Impact` ya existe en Windows |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Credenciales de ElevenLabs | Solo si usas esa voz |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Envío del video por Telegram | Opcional |

Después de cambiar el `.env`, **reinicia el programa** (`Ctrl + C` y volver a arrancarlo).

---

## Paso 6: Poner el clip de tu personaje (opcional pero recomendado)

Copia tu video del personaje a:
```
assets\personaje_loop.mp4
```
Con el comando:
```
copy "C:\ruta\a\tu_clip.mp4" assets\personaje_loop.mp4
```
o arrastrándolo en el explorador de VS Code. Si no está, la zona de abajo del video sale morada lisa.

---

## Paso 7: Arrancar el programa

```
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Qué significa cada parte**
- `uvicorn`: el servidor que ejecuta la página.
- `app.main:app`: archivo `app/main.py`, objeto `app`.
- `--host 127.0.0.1`: solo accesible desde tu propia PC.
- `--port 8000`: el puerto donde escucha.

**Qué verás**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```
La terminal queda ocupada: **no la cierres** mientras uses el programa.

**Ábrelo en el navegador**
```
http://localhost:8000
```
(o `http://127.0.0.1:8000`, o `Ctrl + clic` sobre el enlace de la terminal).

**Variante para desarrollar:** reinicia solo cuando cambias código
```
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Variante si `uvicorn` no se reconoce**
```
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## Paso 8: Usarlo

1. Elige el video y escribe el título.
2. Graba tu narración o sube un audio.
3. Pulsa **Subir y continuar**. La **primera vez** descarga el modelo de Whisper (unos 460 MB para `small`), así que tarda.
4. Revisa el guion y pulsa **Generar video**.
5. Descarga el resultado, que también queda en `storage\output\`.

> El micrófono del navegador funciona en `localhost`. Si da error de permisos, pulsa el candado junto a la dirección y permite el micrófono.

---

## Detener el programa

En la terminal donde corre, pulsa:
```
Ctrl + C
```
Si pregunta si terminar el trabajo por lotes, responde `S`.

---

## Volver a usarlo otro día

Ya no hace falta instalar nada. Solo estos tres comandos:

```
cd /d D:\videostudio\videostudio
venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## Probar sin la página (por consola)

Con el entorno activo, desde la carpeta del proyecto:

```
python run.py "C:\ruta\video.mp4" "Mi título" --audio "C:\ruta\narracion.m4a"
```

Con guion propio (sin transcribir) y video completo sin recortar:
```
python run.py "C:\ruta\video.mp4" "Mi título" --audio "C:\ruta\narracion.m4a" --script "Texto de la narración" --mode fit
```
El video final aparece en `storage\output\`. Pon las rutas **entre comillas** si tienen espacios.

---

## Solución de problemas

| Mensaje | Causa | Solución |
|---------|-------|----------|
| `"python" no se reconoce` | Python no está en el PATH | Reinstala marcando *Add python.exe to PATH*; abre una terminal nueva |
| `"uvicorn" no se reconoce` | El entorno no está activo | Ejecuta `venv\Scripts\activate` (debe aparecer `(venv)`) o usa `python -m uvicorn ...` |
| `ModuleNotFoundError: No module named 'app'` | Estás fuera de la carpeta del proyecto | `cd /d D:\videostudio\videostudio` y repite |
| `ModuleNotFoundError: No module named 'fastapi'` | Faltan dependencias o el entorno no está activo | Activa `venv` y ejecuta `pip install -r requirements.txt` |
| `ffmpeg no se reconoce` o error de FFmpeg en la página | FFmpeg no está en el PATH | Agrega `C:\ffmpeg\bin` al PATH y reabre la terminal |
| `Address already in use` / `[Errno 10048]` | El puerto 8000 está ocupado (quizá otra copia abierta) | Usa otro puerto: `--port 8001` y abre `http://localhost:8001` |
| El micrófono no graba | Permiso del navegador o no es `localhost` | Permite el micrófono; entra por `localhost` |
| "No pude transcribir" en la página | Whisper no se pudo descargar o cargar | Comprueba internet; prueba `WHISPER_MODEL=base` en `.env` y reinicia |
| "No hay audio: graba tu narración..." | Con `TTS_ENGINE=none` hace falta un audio | Sube o graba un audio en el paso 2 |
| Aviso de Hugging Face sobre "symlinks" | Windows sin modo desarrollador | Es solo un aviso, se puede ignorar |
| Subtítulos con cuadros en vez de emojis | Las fuentes no tienen emojis | Quita los emojis del guion |

**Liberar un puerto ocupado**
```
netstat -ano | findstr :8000
taskkill /PID NUMERO_DE_PID /F
```
Reemplaza `NUMERO_DE_PID` por el número de la última columna.

---

## Empezar de cero (si el entorno se dañó)

```
deactivate
rmdir /s /q venv
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```
- `deactivate` sale del entorno actual.
- `rmdir /s /q venv` borra la carpeta `venv` sin pedir confirmación. Tu código, el `.env` y `storage` no se tocan.

---

## Resumen rápido (todo en orden)

```
cd /d D:\videostudio\videostudio
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Luego abre **http://localhost:8000**.

---

## Equivalente en Linux (para el servidor, más adelante)

```
cd ~/videostudio
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Las diferencias con Windows son `python3` en vez de `python`, `source venv/bin/activate` en vez de `venv\Scripts\activate`, y `cp` en vez de `copy`.
