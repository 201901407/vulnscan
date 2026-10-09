from types import SimpleNamespace

import pytest

from conftest import FakeClient
from vulnscan.config import ConfigError, ModelConfig
from vulnscan.llm import (
    LiteLLMClient,
    ManualClient,
    ManualStepPending,
    ModelOutputError,
    complete_json,
    extract_json,
    make_client,
    retry_after,
)


def test_extract_json_ignores_surrounding_text():
    assert extract_json('Sure:\n```json\n{"findings": []}\n```') == {"findings": []}
    with pytest.raises(ModelOutputError):
        extract_json("no json here")


def test_complete_json_retries_once_then_fails():
    replies = iter(["not json", '{"ok": true}'])
    client = FakeClient("m", lambda system, user: next(replies))
    assert complete_json(client, "s", "u") == {"ok": True}
    assert len(client.calls) == 2

    broken = FakeClient("m", "still not json")
    with pytest.raises(ModelOutputError):
        complete_json(broken, "s", "u")
    assert len(broken.calls) == 2


def test_retry_after_prefers_the_provider_header():
    limited = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "7"}))
    assert retry_after(limited, attempt=1) == 7.0
    via_litellm = SimpleNamespace(litellm_response_headers={"retry-after": "5"}, response=None)
    assert retry_after(via_litellm, attempt=1) == 5.0
    assert retry_after(Exception(), attempt=3) == 8.0


def test_rate_limit_and_unavailable_errors_are_retried_up_to_the_limit(monkeypatch):
    import litellm

    waits = []
    monkeypatch.setattr("vulnscan.llm.time.sleep", waits.append)
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done"))])
    outcomes = iter([
        litellm.ServiceUnavailableError("busy", "p", "m"),
        litellm.RateLimitError("slow down", "p", "m"),
        reply,
    ])

    def completion(**params):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(litellm, "completion", completion)
    assert LiteLLMClient("m", ModelConfig(model="x/y"), max_attempts=3).complete("s", "u") == "done"
    assert waits == [2.0, 4.0]

    monkeypatch.setattr(litellm, "completion", lambda **p: (_ for _ in ()).throw(
        litellm.ServiceUnavailableError("busy", "p", "m")))
    with pytest.raises(litellm.ServiceUnavailableError):
        LiteLLMClient("m", ModelConfig(model="x/y"), max_attempts=2).complete("s", "u")


def test_manual_model_writes_the_prompt_then_reads_the_saved_reply(tmp_path):
    config = ModelConfig(model="chat app", adapter="manual")
    client = make_client("teacher", config, 1, None, tmp_path / "manual")
    assert isinstance(client, ManualClient)

    with pytest.raises(ManualStepPending) as pending:
        client.complete("system text", "user text")
    assert pending.value.prompt_file.read_text() == "system text\n\nuser text"

    pending.value.reply_file.write_text('{"findings": []}')
    assert client.complete("system text", "user text") == '{"findings": []}'
    with pytest.raises(ManualStepPending):
        client.complete("system text", "a different prompt")


def test_missing_key_is_reported_by_variable_name(monkeypatch):
    monkeypatch.delenv("VULNSCAN_TEST_KEY", raising=False)
    with pytest.raises(ConfigError, match="VULNSCAN_TEST_KEY"):
        LiteLLMClient("m", ModelConfig(model="x/y", api_key_env="VULNSCAN_TEST_KEY"), max_attempts=1)
