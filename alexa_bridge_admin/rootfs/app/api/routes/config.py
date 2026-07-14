from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.config_service import ConfigService

router = APIRouter(prefix="/api", tags=["config"])
service = ConfigService()


class RawYamlRequest(BaseModel):
    yaml: str


@router.get("/config")
def get_config() -> dict:
    return service.load()


@router.put("/config")
def put_config(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload deve ser um objeto JSON")

    service.save(payload)
    service.append_audit(action="UPDATE_CONFIG", detail="Configuracao salva via API")
    return {
        "ok": True,
        "detail": "Configuracao salva",
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
        service.save_raw(payload.yaml)
        service.append_audit(action="SAVE_RAW_YAML", detail="YAML salvo via editor")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    return {
        "ok": True,
        "detail": "YAML salvo",
    }
