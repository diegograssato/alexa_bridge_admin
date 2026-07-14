from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.services.config_service import ConfigService

router = APIRouter(prefix="/api", tags=["backup"])
service = ConfigService()


class RestoreBackupRequest(BaseModel):
    filename: str = Field(min_length=1)


class RestoreYamlRequest(BaseModel):
    yaml: str


@router.get("/backups")
def list_backups() -> dict:
    return {
        "items": service.list_backups(),
    }


@router.post("/backups")
def create_backup() -> dict:
    item = service.create_backup()
    service.append_audit(action="BACKUP", detail=f"filename={item['filename']}")
    return {
        "ok": True,
        "detail": "Backup criado",
        "item": item,
    }


@router.get("/backups/{filename}/download")
def download_backup(filename: str) -> PlainTextResponse:
    decoded = unquote(filename)
    try:
        raw = service.read_backup(decoded)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except FileNotFoundError as ex:
        raise HTTPException(status_code=404, detail=f"Backup nao encontrado: {ex.args[0]}") from ex

    response = PlainTextResponse(content=raw, media_type="application/x-yaml")
    response.headers["Content-Disposition"] = f'attachment; filename="{decoded}"'
    return response


@router.post("/backups/restore")
def restore_backup(payload: RestoreBackupRequest) -> dict:
    try:
        ret = service.restore_backup(payload.filename)
        service.append_audit(action="RESTORE_BACKUP", detail=f"filename={payload.filename}")
        return ret
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except FileNotFoundError as ex:
        raise HTTPException(status_code=404, detail=f"Backup nao encontrado: {ex.args[0]}") from ex


@router.post("/backups/restore-yaml")
def restore_yaml(payload: RestoreYamlRequest) -> dict:
    try:
        service.save_raw(payload.yaml)
        service.append_audit(action="RESTORE_YAML_UPLOAD", detail="Restauracao por upload")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    return {
        "ok": True,
        "detail": "Configuracao restaurada via arquivo",
    }


@router.delete("/backups/{filename}")
def delete_backup(filename: str) -> dict:
    decoded = unquote(filename)
    try:
        service.delete_backup(decoded)
        service.append_audit(action="DELETE_BACKUP", detail=f"filename={decoded}")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except FileNotFoundError as ex:
        raise HTTPException(status_code=404, detail=f"Backup nao encontrado: {ex.args[0]}") from ex

    return {
        "ok": True,
        "detail": "Backup removido",
    }
