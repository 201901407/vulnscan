from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# OWASP MASVS control groups (ADR 0002).
MASVS_CATEGORIES = {
    "storage": "Sensitive data stored on the device",
    "crypto": "Cryptography and key management",
    "auth": "Authentication and authorization",
    "network": "Network communication",
    "platform": "Interaction with the mobile platform: IPC, WebViews, UI",
    "code": "Code quality: input validation, dependencies, platform versions",
    "resilience": "Resilience against reverse engineering and tampering",
    "privacy": "Handling of personal data",
}


class ConfigError(Exception):
    pass


class ModelConfig(BaseModel):
    model: str
    # "manual" writes each prompt to a file and reads the reply from one a person saves.
    adapter: Literal["litellm", "manual"] = "litellm"
    api_key_env: str | None = None
    api_base: str | None = None
    input_budget_tokens: int = 100_000
    max_output_tokens: int = 8_000
    temperature: float | None = 0.2
    extra: dict[str, Any] = Field(default_factory=dict)


class Roles(BaseModel):
    teacher: str
    students: list[str]
    judge: str


class AppConfig(BaseModel):
    path: Path
    reference: Path | None = None


class IngestConfig(BaseModel):
    decompiler: list[str] = ["jadx", "-d", "{out}", "{apk}"]
    decompiler_timeout_seconds: float = Field(600, gt=0)
    cache_dir: Path = Path(".cache/decompiled")
    include_packages: list[str] = []
    exclude_packages: list[str] = []
    source_extensions: list[str] = [".java", ".kt"]
    generated_patterns: list[str] = [
        "R.java",
        "R$*.java",
        "BR.java",
        "DataBinderMapperImpl.java",
        "*Binding.java",
        "*BindingImpl.java",
    ]
    # Kotlin's binary metadata field: unreadable, and costly in tokens.
    strip_patterns: list[str] = [r'd1 = \{(?:\s*"(?:[^"\\]|\\.)*",?)*\s*\},\s*']
    resource_patterns: list[str] = [
        "res/values/strings.xml",
        "res/xml/*.xml",
        "*.json",
        "*.properties",
        "*.html",
        "*.js",
    ]
    max_resource_bytes: int = 40_000
    skip_dirs: list[str] = ["build", ".gradle", ".git", ".idea", "node_modules"]


class ScanConfig(BaseModel):
    repeats: int = Field(3, ge=1)
    chars_per_token: float = Field(3.5, gt=0)
    # Share of a model's input budget that lessons may take in each call.
    lesson_budget_share: float = Field(0.25, gt=0, lt=1)


class EvidenceConfig(BaseModel):
    check: Literal["off", "flag", "exclude"] = "exclude"
    min_match: float = Field(0.5, gt=0, le=1)
    trivial_line_chars: int = 5


class MatchConfig(BaseModel):
    batch_size: int = Field(20, ge=1)
    # None uses the judge model's own temperature setting.
    judge_temperature: float | None = 0.0


class LessonConfig(BaseModel):
    allow_terms: list[str] = []


class LLMConfig(BaseModel):
    max_attempts: int = Field(5, ge=1)


class Config(BaseModel):
    app: AppConfig
    models: dict[str, ModelConfig]
    roles: Roles
    ingest: IngestConfig = IngestConfig()
    scan: ScanConfig = ScanConfig()
    evidence: EvidenceConfig = EvidenceConfig()
    match: MatchConfig = MatchConfig()
    lessons: LessonConfig = LessonConfig()
    llm: LLMConfig = LLMConfig()
    categories: dict[str, str] = MASVS_CATEGORIES
    runs_dir: Path = Path("runs")

    @model_validator(mode="after")
    def _check_roles(self) -> Config:
        named = [self.roles.teacher, self.roles.judge, *self.roles.students]
        missing = sorted(set(named) - set(self.models))
        if missing:
            raise ValueError(f"roles refer to undefined models: {missing}")
        if self.roles.judge in self.roles.students:
            raise ValueError("the judge must not be a student model")
        return self


def load_config(path: Path) -> Config:
    try:
        return Config.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ConfigError(f"{path}: {error}") from error


def save_config(config: Config, path: Path) -> None:
    path.write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
