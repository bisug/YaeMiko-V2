from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_COMMAND = "python -m Mikobot"


def test_railway_manifest():
    path = ROOT / "railway.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "$schema" in data
    deploy = data.get("deploy", {})
    assert deploy.get("startCommand") == START_COMMAND
    assert deploy.get("restartPolicyType") in {"ON_FAILURE", "ALWAYS", "NEVER"}


def test_render_manifest():
    path = ROOT / "render.yaml"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "type: worker" in text
    assert "runtime: docker" in text
    assert f"dockerCommand: {START_COMMAND}" in text


def test_uniform_start_commands():
    procfile = (ROOT / "Procfile").read_text(encoding="utf-8").strip()
    assert procfile == f"worker: {START_COMMAND}"

    railway_data = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert railway_data["deploy"]["startCommand"] == START_COMMAND

    render_text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert f"dockerCommand: {START_COMMAND}" in render_text

    docker_text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '"-m", "Mikobot"' in docker_text.replace("'", '"')


def test_app_json():
    path = ROOT / "app.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    addons = data.get("addons", [])
    postgres = [
        addon
        for addon in addons
        if addon.get("plan", "").startswith("heroku-postgresql")
    ]
    assert postgres, "app.json must declare heroku-postgresql addon"
    version = postgres[0].get("options", {}).get("version")
    assert version == "18"
