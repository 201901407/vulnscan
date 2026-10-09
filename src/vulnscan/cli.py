from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .config import ConfigError, load_config, save_config
from .ingest import IngestError, load_app
from .llm import ManualStepPending
from .pipeline import run
from .reference import ReferenceFormatError, convert

SAVED_CONFIG = "config.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vulnscan")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="show what would be sent to the models; no model calls")
    scan = commands.add_parser("run", help="teacher scan, lessons, student scans and scoring")
    for command in (ingest, scan):
        command.add_argument("-c", "--config", type=Path, default=Path("config.yaml"))
        command.add_argument("--app", type=Path, help="override app.path")
    scan.add_argument("--reference", type=Path, help="override app.reference")
    scan.add_argument("--resume", type=Path, help="existing run folder to continue")

    reference = commands.add_parser("reference", help="convert a published vulnerability list to reference YAML")
    reference.add_argument("input", type=Path)
    reference.add_argument("-o", "--output", type=Path, required=True)
    reference.add_argument("--section", help="only read list items under headings containing this text")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    load_dotenv(Path.cwd() / ".env")
    handlers = {"ingest": _ingest, "run": _run, "reference": _reference}
    try:
        return handlers[args.command](args)
    except (ConfigError, IngestError, ReferenceFormatError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _config(args: argparse.Namespace):
    config = load_config(args.config)
    if args.app:
        config.app.path = args.app
    if getattr(args, "reference", None):
        config.app.reference = args.reference
    return config


def _ingest(args: argparse.Namespace) -> int:
    config = _config(args)
    app = load_app(config.app.path, config.ingest)
    print(json.dumps(app.summary() | {"files": [f.path for f in app.files]}, indent=2))
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.resume:
        run_dir = args.resume
        config = load_config(run_dir / SAVED_CONFIG)
    else:
        config = _config(args)
        run_dir = config.runs_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True)
        save_config(config, run_dir / SAVED_CONFIG)
    try:
        run(config, run_dir)
    except ManualStepPending as pending:
        print(
            f"Manual step for model '{pending.model}':\n"
            f"  1. Give the model this file:  {pending.prompt_file}\n"
            f"  2. Save its full reply to:    {pending.reply_file}\n"
            f"  3. Continue with:             vulnscan run --resume {run_dir}"
        )
        return 2
    print((run_dir / "report.md").read_text())
    print(f"Run folder: {run_dir}")
    return 0


def _reference(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise ReferenceFormatError(f"{args.output} already exists; remove it or choose another name")
    entries = convert(args.input, args.section)
    args.output.write_text(yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=1000))
    print(f"Wrote {len(entries)} entries to {args.output}. Review the file before using it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
