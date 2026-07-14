from __future__ import annotations

import os

import requests
from fastapi import APIRouter, Query

from app.services.config_service import ConfigService

router = APIRouter(prefix="/api", tags=["ha"])


@router.get("/ha/media-players")
def list_media_players(query: str = Query(default="", alias="q"), limit: int = Query(default=30, ge=1, le=200)) -> dict:
    token = os.getenv("SUPERVISOR_TOKEN", "")
    base_url = os.getenv("SUPERVISOR_URL", "http://supervisor")
    q = query.strip().lower()

    if token:
        try:
            response = requests.get(
                f"{base_url}/core/api/states",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            if response.ok:
                payload = response.json()
                states = []
                if isinstance(payload, list):
                    states = payload
                elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
                    states = payload["data"]

                if states:
                    items = []
                    for row in states:
                        if not isinstance(row, dict):
                            continue
                        entity_id = str(row.get("entity_id", ""))
                        if not entity_id.startswith("media_player."):
                            continue
                        if q and q not in entity_id.lower():
                            continue
                        items.append(entity_id)
                    items = sorted(set(items))
                    return {"items": items[:limit]}
        except Exception:
            pass

    service = ConfigService()
    devices = service.list_devices(page=1, page_size=1000, query="")
    fallback = []
    for row in devices.get("items", []):
        entity_id = str(row.get("entity_id", ""))
        if not entity_id.startswith("media_player."):
            continue
        if q and q not in entity_id.lower():
            continue
        fallback.append(entity_id)

    fallback = sorted(set(fallback))
    return {"items": fallback[:limit]}
