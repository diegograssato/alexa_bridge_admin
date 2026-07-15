from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.backup import router as backup_router
from app.api.routes.audit import router as audit_router
from app.api.routes.config import router as config_router
from app.api.routes.devices import router as devices_router
from app.api.routes.ha import router as ha_router
from app.api.routes.reload import router as reload_router
from app.services.config_service import ConfigService

app = FastAPI(title="Alexa Bridge Admin", version="0.7.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(devices_router)
app.include_router(reload_router)
app.include_router(backup_router)
app.include_router(audit_router)
app.include_router(ha_router)

frontend_dir = Path("/app/frontend")
if not frontend_dir.exists():
    frontend_dir = Path(__file__).resolve().parent / "frontend"
app.mount("/frontend", StaticFiles(directory=str(frontend_dir)), name="frontend")


@app.on_event("startup")
def setup_bridge_script() -> None:
    service = ConfigService()
    try:
        app.state.bridge_script_setup = service.sync_bridge_script()
    except Exception as ex:  # pragma: no cover
        app.state.bridge_script_setup = {
            "ok": False,
            "copied": False,
            "detail": "setup_exception",
            "error": str(ex),
        }

    try:
        app.state.bridge_yaml_setup = service.ensure_bridge_yaml()
    except Exception as ex:  # pragma: no cover
        app.state.bridge_yaml_setup = {
            "ok": False,
            "copied": False,
            "detail": "setup_exception",
            "error": str(ex),
        }


@app.get("/api/health")
def health() -> dict:
    script_setup = getattr(app.state, "bridge_script_setup", {})
    yaml_setup = getattr(app.state, "bridge_yaml_setup", {})
    return {
        "ok": True,
        "bridge_script_setup": script_setup,
        "bridge_yaml_setup": yaml_setup,
        "bridge_script_sync": {
            "last_sync_status": str(script_setup.get("detail", "unknown")),
            "overwritten": bool(script_setup.get("overwritten", False)),
            "copied": bool(script_setup.get("copied", False)),
            "ok": bool(script_setup.get("ok", False)),
        },
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")
