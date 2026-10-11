from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelRequestError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @classmethod
    def from_environment(cls, api_key_env: str | None = "OPENAI_API_KEY", **kwargs: object) -> "OpenAICompatibleClient":
        api_key = os.environ.get(api_key_env) if api_key_env else None
        return cls(api_key=api_key, **kwargs)  # type: ignore[arg-type]

    def complete(self, prompt: str) -> str:
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ModelRequestError(f"Model endpoint returned HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError) as error:
            raise ModelRequestError(f"Could not reach model endpoint: {error}") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelRequestError(f"Model endpoint returned invalid JSON: {error}") from error

        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelRequestError("Model endpoint response has no choices[0].message.content") from error
        if not isinstance(content, str):
            raise ModelRequestError("Model endpoint content must be a string")
        return content
