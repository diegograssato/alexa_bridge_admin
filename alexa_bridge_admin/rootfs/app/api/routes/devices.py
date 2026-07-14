from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.config_service import ConfigService

router = APIRouter(prefix="/api", tags=["devices"])
service = ConfigService()


class DevicePayload(BaseModel):
    room: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    aliases: list[str] = []


class DevicesImportRequest(BaseModel):
    yaml: str


@router.get("/devices")
def list_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    query: str = Query(default=""),
) -> dict:
    return service.list_devices(page=page, page_size=page_size, query=query)


@router.get("/devices/yaml")
def export_devices_yaml() -> dict:
    service.append_audit(action="EXPORT_DEVICES_YAML", detail="Exportacao de YAML de devices")
    return {
        "yaml": service.export_devices_yaml(),
    }


@router.post("/devices/import")
def import_devices_yaml(payload: DevicesImportRequest) -> dict:
    try:
        summary = service.import_devices_yaml(payload.yaml)
        service.append_audit(action="IMPORT_DEVICES_YAML", detail=f"rooms={summary['rooms']};devices={summary['devices']}")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    return {
        "ok": True,
        "detail": "Devices importados",
        "summary": summary,
    }


@router.get("/devices/{device_key}")
def get_device(device_key: str) -> dict:
    key = unquote(device_key)
    try:
        return service.get_device(key)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="Device nao encontrado") from ex


@router.post("/devices")
def create_device(payload: DevicePayload) -> dict:
    try:
        item = service.create_device(payload.room, payload.entity_id, payload.aliases)
        service.append_audit(action="CREATE_ENTITY", entity_id=payload.entity_id, detail=f"room={payload.room}")
    except ValueError as ex:
        if str(ex) == "device_already_exists":
            raise HTTPException(status_code=409, detail="Device ja existe") from ex
        raise HTTPException(status_code=400, detail="Payload invalido") from ex

    return {
        "ok": True,
        "item": item,
    }


@router.put("/devices/{device_key}")
def update_device(device_key: str, payload: DevicePayload) -> dict:
    key = unquote(device_key)
    try:
        item = service.update_device(key, payload.room, payload.entity_id, payload.aliases)
        service.append_audit(action="UPDATE_ENTITY", entity_id=payload.entity_id, detail=f"key={key}")
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="Device nao encontrado") from ex
    except ValueError as ex:
        if str(ex) == "device_already_exists":
            raise HTTPException(status_code=409, detail="Device ja existe") from ex
        raise HTTPException(status_code=400, detail="Payload invalido") from ex

    return {
        "ok": True,
        "item": item,
    }


@router.delete("/devices/{device_key}")
def delete_device(device_key: str) -> dict:
    key = unquote(device_key)
    entity_id = "-"
    try:
        current = service.get_device(key)
        entity_id = current.get("entity_id", "-")
    except KeyError:
        pass
    try:
        service.delete_device(key)
        service.append_audit(action="DELETE_ENTITY", entity_id=entity_id, detail=f"key={key}")
    except KeyError as ex:
        raise HTTPException(status_code=404, detail="Device nao encontrado") from ex

    return {
        "ok": True,
    }
