from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Protocol

from .config import ConfigError, ModelConfig

log = logging.getLogger(__name__)

RETRY_NOTE = "\n\nYour previous reply was not valid JSON. Reply with the JSON object only."
MAX_BACKOFF_SECONDS = 60


class ModelOutputError(Exception):
    pass


class LLMClient(Protocol):
    """The only thing the pipeline knows about a model (ADR 0006)."""

    name: str
    budget: int

    def complete(self, system: str, user: str) -> str: ...


class LiteLLMClient:
    def __init__(
        self,
        name: str,
        config: ModelConfig,
        max_attempts: int,
        temperature: float | None = None,
    ) -> None:
        self.name = name
        self.budget = config.input_budget_tokens
        self._max_attempts = max_attempts
        self._params: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_output_tokens,
            "drop_params": True,
            "num_retries": 0,
            **config.extra,
        }
        if config.api_base:
            self._params["api_base"] = config.api_base
        chosen = config.temperature if temperature is None else temperature
        if chosen is not None:
            self._params["temperature"] = chosen
        if config.api_key_env:
            key = os.environ.get(config.api_key_env)
            if not key:
                raise ConfigError(
                    f"model '{name}': environment variable {config.api_key_env} is not set"
                )
            self._params["api_key"] = key

    def complete(self, system: str, user: str) -> str:
        import litellm

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = litellm.completion(messages=messages, **self._params)
                return response.choices[0].message.content or ""
            except (litellm.RateLimitError, litellm.ServiceUnavailableError) as error:
                if attempt == self._max_attempts:
                    raise
                wait = retry_after(error, attempt)
                log.warning(
                    "%s: %s; waiting %.0fs (attempt %d of %d)",
                    self.name, type(error).__name__, wait, attempt, self._max_attempts,
                )
                time.sleep(wait)
        raise AssertionError("unreachable")


class ManualStepPending(Exception):
    """A manual model needs a person to supply the reply before the run can continue."""

    def __init__(self, model: str, prompt_file: Path, reply_file: Path) -> None:
        super().__init__(f"waiting for a reply to {prompt_file}")
        self.model = model
        self.prompt_file = prompt_file
        self.reply_file = reply_file


class ManualClient:
    """A model reached by hand, e.g. through a chat app (ADR 0006).

    Files are named by a hash of the prompt, so a resumed run finds the reply
    to exactly the prompt it would send again.
    """

    def __init__(self, name: str, config: ModelConfig, directory: Path) -> None:
        self.name = name
        self.budget = config.input_budget_tokens
        self._directory = directory

    def complete(self, system: str, user: str) -> str:
        prompt = f"{system.strip()}\n\n{user}"
        stem = f"{self.name}-{hashlib.sha256(prompt.encode()).hexdigest()[:8]}"
        prompt_file = self._directory / f"{stem}.prompt.txt"
        reply_file = self._directory / f"{stem}.reply.txt"
        if reply_file.exists() and reply_file.read_text().strip():
            return reply_file.read_text()
        self._directory.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)
        raise ManualStepPending(self.name, prompt_file, reply_file)


def make_client(
    name: str, config: ModelConfig, max_attempts: int, temperature: float | None, manual_dir: Path
) -> LLMClient:
    if config.adapter == "manual":
        return ManualClient(name, config, manual_dir)
    return LiteLLMClient(name, config, max_attempts, temperature)


def retry_after(error: Exception, attempt: int) -> float:
    """Seconds to wait after a 429 or 503: the provider's retry-after, else backoff."""
    for headers in (
        getattr(error, "litellm_response_headers", None),
        getattr(getattr(error, "response", None), "headers", None),
    ):
        try:
            return max(float((headers or {}).get("retry-after")), 0.0)
        except (TypeError, ValueError):
            continue
    return float(min(2**attempt, MAX_BACKOFF_SECONDS))


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return int(len(text) / chars_per_token)


def extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ModelOutputError("no JSON object in reply")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise ModelOutputError(str(error)) from error
    if not isinstance(data, dict):
        raise ModelOutputError("reply is not a JSON object")
    return data


def complete_json(client: LLMClient, system: str, user: str, retries: int = 1) -> dict[str, Any]:
    prompt = user
    for attempt in range(retries + 1):
        try:
            return extract_json(client.complete(system, prompt))
        except ModelOutputError as error:
            if attempt == retries:
                raise
            log.warning("%s returned unparseable output (%s); retrying", client.name, error)
            prompt = user + RETRY_NOTE
    raise AssertionError("unreachable")
