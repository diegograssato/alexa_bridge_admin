from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.config_service import ConfigService
from app.services.reload_service import ReloadService

router = APIRouter(prefix="/api", tags=["config"])
service = ConfigService()
reload_service = ReloadService()


class RawYamlRequest(BaseModel):
    yaml: str


@router.get("/config")
def get_config() -> dict:
    return service.load()


@router.put("/config")
def put_config(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload deve ser um objeto JSON")

    previous = service.load()
    webhook_changed = service.webhook_ids_changed(previous, payload)
    try:
        service.save(payload)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    reload_result = {"ok": True, "detail": "nao_necessario"}
    if webhook_changed:
        reload_result = reload_service.reload_pyscript_runtime()
        if reload_result.get("ok"):
            service.append_audit(action="AUTO_PYSCRIPT_RELOAD", detail="pyscript.reload apos alteracao de webhook")
        else:
            service.append_audit(
                action="AUTO_PYSCRIPT_RELOAD_FAILED",
                detail=str(reload_result.get("detail", "falha no pyscript.reload")),
            )

    service.append_audit(action="UPDATE_CONFIG", detail="Configuracao salva via API")
    return {
        "ok": True,
        "detail": "Configuracao salva",
        "requires_pyscript_restart": webhook_changed and not reload_result.get("ok", False),
        "auto_pyscript_reload": webhook_changed,
        "pyscript_reload_ok": bool(reload_result.get("ok", False)) if webhook_changed else True,
        "pyscript_reload_detail": reload_result.get("detail", "nao_necessario"),
        "restart_reason": "webhook_ids_changed" if webhook_changed else "",
    }


@router.get("/config/yaml")
def get_yaml() -> dict:
    return {
        "yaml": service.load_raw(),
    }


@router.post("/config/yaml/validate")
def validate_yaml(payload: RawYamlRequest) -> dict:
    result = service.validate_raw_yaml_schema(payload.yaml)
    service.append_audit(
        action="VALIDATE_RAW_YAML",
        detail="ok" if result.get("ok") else "; ".join(result.get("errors", [])),
    )
    return result


@router.put("/config/yaml")
def put_yaml(payload: RawYamlRequest) -> dict:
    try:
        previous = service.load()
        service.save_raw(payload.yaml)
        service.append_audit(action="SAVE_RAW_YAML", detail="YAML salvo via editor")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    current = service.load()
    webhook_changed = service.webhook_ids_changed(previous, current)

    reload_result = {"ok": True, "detail": "nao_necessario"}
    if webhook_changed:
        reload_result = reload_service.reload_pyscript_runtime()
        if reload_result.get("ok"):
            service.append_audit(action="AUTO_PYSCRIPT_RELOAD", detail="pyscript.reload apos alteracao de webhook (raw yaml)")
        else:
            service.append_audit(
                action="AUTO_PYSCRIPT_RELOAD_FAILED",
                detail=str(reload_result.get("detail", "falha no pyscript.reload")),
            )

    return {
        "ok": True,
        "detail": "YAML salvo",
        "requires_pyscript_restart": webhook_changed and not reload_result.get("ok", False),
        "auto_pyscript_reload": webhook_changed,
        "pyscript_reload_ok": bool(reload_result.get("ok", False)) if webhook_changed else True,
        "pyscript_reload_detail": reload_result.get("detail", "nao_necessario"),
        "restart_reason": "webhook_ids_changed" if webhook_changed else "",
    }
