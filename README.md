# App Deportes – Backend (FastAPI)

Backend en **FastAPI** con arquitectura modular (API, core, modelos, servicios), autenticación y base de datos. Incluye endpoints documentados automáticamente con Swagger/OpenAPI.

## 🧰 Stack
- Python 3.12
- FastAPI
- Uvicorn
- SQLite (desarrollo)

## 📁 Estructura
- `app/main.py` → entrada de la app
- `app/api/` → rutas y dependencias
- `app/core/` → config, seguridad, DB
- `app/models/` → modelos
- `app/schemas/` → esquemas (validación/serialización)
- `app/services/` → lógica de negocio
- `app/realtime/` → SSE (Server-Sent Events)
- `app/web/` → templates/static (si aplica)

## ⚙️ Instalación y ejecución (local)
> Requisitos: Python 3.12

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
