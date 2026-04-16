from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class ServerClient:
    def __init__(self, config):
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_token and self.config.api_token != "CHANGE_ME":
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        return headers

    def _build_url(self, path: str | None) -> str:
        base = self.config.base_url.rstrip("/")
        if not path:
            return base
        if path.startswith("/"):
            return f"{base}{path}"
        return f"{base}/{path}"

    def push_stats(self, payload: dict[str, Any]) -> bool:
        if not self.config.enabled:
            return True

        url = self._build_url(self.config.ingest_path)
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Unable to sync stats to server: %s", exc)
            return False

    def heartbeat(self, payload: dict[str, Any]) -> bool:
        if not self.config.enabled:
            return True

        health_path = (self.config.health_path or "").strip()
        if not health_path:
            return True

        url = self._build_url(health_path)
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)
            return False
