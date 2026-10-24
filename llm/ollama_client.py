import json
from typing import Any

import requests

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout_seconds: int = OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host
        self.model = model
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            return any(model.get("name") == self.model for model in models)
        except (requests.RequestException, ValueError, TypeError):
            return False

    def generate_json(self, system: str, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json().get("response", "")
            result = json.loads(raw)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama JSON generation failed: {exc}") from exc
        if not isinstance(result, dict):
            raise OllamaError("Ollama returned JSON, but not a JSON object")
        return result
