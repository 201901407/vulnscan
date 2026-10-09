import json
import re

import pytest

from conftest import FakeClient
from test_stages import FINDING, LESSON
from vulnscan.config import Config
from vulnscan.pipeline import run

INVENTED = FINDING | {"title": "Invented", "evidence": "Runtime.getRuntime().exec(userInput);"}


def teacher(system, user):
    if "general lessons" in system:
        return json.dumps({"lessons": [LESSON]})
    return json.dumps({"findings": [FINDING, INVENTED]})


def student(system, user):
    return json.dumps({"findings": [FINDING] if "<lessons>" in user else []})


def judge(system, user):
    ids = re.findall(r'"id": "(F\d+)"', user[user.index("<findings>") :])
    return json.dumps({"assignments": [{"finding_id": i, "reference_id": "R1", "reason": "same"} for i in ids]})


@pytest.fixture
def config(app_dir):
    return Config.model_validate({
        "app": {"path": str(app_dir)},
        "models": {name: {"model": f"fake/{name}"} for name in ("teacher", "small", "judge")},
        "roles": {"teacher": "teacher", "students": ["small"], "judge": "judge"},
        "scan": {"repeats": 2},
    })


def test_end_to_end_lift_against_teacher_reference(config, tmp_path):
    replies = {"teacher": teacher, "small": student, "judge": judge}
    temperatures = {}

    def make_client(name, temperature):
        temperatures[name] = temperature
        return FakeClient(name, replies[name])

    report = run(config, tmp_path / "run", make_client)

    assert temperatures == {"teacher": None, "small": None, "judge": 0.0}
    assert report["reference"] == {"kind": "teacher", "entries": 1}
    assert report["teacher"]["unverified"] == 1
    assert report["lessons"]["kept"] == 1
    small = report["students"]["small"]
    assert small["baseline"]["recall"]["runs"] == [0.0, 0.0]
    assert small["lessons"]["recall"]["runs"] == [1.0, 1.0]
    assert small["lift"] == 1.0 and small["distinguishable"]
    assert (tmp_path / "run" / "report.md").exists()
    assert "Lesson:" in (tmp_path / "run" / "lessons.txt").read_text()


def test_single_run_per_arm_gives_no_verdict_on_noise(config, tmp_path):
    config.scan.repeats = 1
    replies = {"teacher": teacher, "small": student, "judge": judge}
    report = run(config, tmp_path / "run", lambda name, t: FakeClient(name, replies[name]))
    assert report["students"]["small"]["distinguishable"] is None
    assert "noise is unknown" in (tmp_path / "run" / "report.md").read_text()


def test_resume_reuses_saved_stages_without_model_calls(config, tmp_path):
    replies = {"teacher": teacher, "small": student, "judge": judge}
    first = run(config, tmp_path / "run", lambda name, t: FakeClient(name, replies[name]))

    def no_calls(system, user):
        raise AssertionError("resume must not call a model")

    assert run(config, tmp_path / "run", lambda name, t: FakeClient(name, no_calls)) == first
