# 0011. Project setup: Python venv, one YAML config, few dependencies

Status: Accepted

## Context

The assignment asks for "clean code that is easy to extend" and to "keep model
choice, app path, and thresholds in config". The pipeline should stay
lightweight. API keys are secrets.

## Decision

1. Python 3.11 in a project virtual environment.
2. One YAML config file holds models, roles, app path, reference path and every
   threshold. Each setting has a default in one place in code (batch sizes,
   retry limits, size caps, file patterns), so the file only lists overrides.
3. Runtime dependencies: LiteLLM (pinned, ADR 0006), pydantic (schema
   validation), PyYAML (config), python-dotenv (loads a local `.env`). pytest is
   a development dependency.
4. Secrets: keys are read only from environment variables named in config. The
   repo ships `.env.example` with empty placeholders; `.env` is git-ignored.
   Nothing prints or logs a key.
5. Tests and fixtures use a small made-up app. No code, test, prompt or default
   is built from the assignment's target app.

## Why

- pydantic and python-dotenv are already installed by LiteLLM, so they add no
  weight.
- A made-up fixture keeps the implementation from being shaped by one app.

## Consequences

- The reference list for a target app is run data, added when measuring.
