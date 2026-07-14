from __future__ import annotations

from fastapi import APIRouter

from app.services.config_service import ConfigService
from app.services.reload_service import ReloadService

router = APIRouter(prefix="/api", tags=["reload"])
service = ReloadService()
config_service = ConfigService()


@router.post("/reload")
def reload_bridge() -> dict:
    ret = service.reload_pyscript()
    if ret.get("ok"):
        config_service.append_audit(action="RELOAD", detail="pyscript.alexa_bridge_reload")
    else:
        config_service.append_audit(action="RELOAD_FAILED", detail=str(ret.get("detail", "falha")))
    return ret
