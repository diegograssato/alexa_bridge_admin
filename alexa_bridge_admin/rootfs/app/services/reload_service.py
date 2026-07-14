from __future__ import annotations

import os

import requests


class ReloadService:
    def __init__(self) -> None:
        self.supervisor_token = os.getenv("SUPERVISOR_TOKEN", "")
        self.base_url = os.getenv("SUPERVISOR_URL", "http://supervisor")

    def reload_pyscript(self) -> dict:
        if not self.supervisor_token:
            return {
                "ok": False,
                "detail": "SUPERVISOR_TOKEN nao encontrado",
            }

        headers = {
            "Authorization": f"Bearer {self.supervisor_token}",
            "Content-Type": "application/json",
        }

        service_candidates = [
            "alexa_bridge_reload",
            "alexa_wrapper_reload",
        ]

        last_status = 0
        last_body = ""
        for service_name in service_candidates:
            url = f"{self.base_url}/core/api/services/pyscript/{service_name}"
            response = requests.post(url, headers=headers, json={}, timeout=10)
            if response.status_code < 400:
                return {
                    "ok": True,
                    "detail": f"pyscript.{service_name} executado",
                }
            last_status = response.status_code
            last_body = response.text

        return {
            "ok": False,
            "detail": f"Falha ao chamar servico: HTTP {last_status}",
            "body": last_body,
        }
