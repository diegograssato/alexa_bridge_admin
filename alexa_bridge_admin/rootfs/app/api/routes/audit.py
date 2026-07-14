from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.config_service import ConfigService

router = APIRouter(prefix="/api", tags=["audit"])
service = ConfigService()


@router.get("/audit")
def list_audit(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return {
        "items": service.list_audits(limit=limit),
    }
