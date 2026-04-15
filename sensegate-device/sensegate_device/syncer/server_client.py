from __future__ import annotations

import logging
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

    def post_event_batch(self, events: list[dict]) -> bool:
        if not self.config.enabled or not events:
            return True
        url = f"{self.config.base_url.rstrip('/')}{self.config.ingest_path}"
        try:
            response = requests.post(
                url,
                json={"events": events},
                headers=self._headers(),
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Unable to sync events to server: %s", exc)
            return False

    def heartbeat(self, payload: dict) -> bool:
        if not self.config.enabled:
            return True
        url = f"{self.config.base_url.rstrip('/')}{self.config.health_path}"
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
