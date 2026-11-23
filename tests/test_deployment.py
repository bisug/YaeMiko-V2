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

    assert data.get("stack") == "heroku-26"
    assert "addons" not in data
    assert data["formation"]["worker"]["size"] == "basic"

    buildpacks = [item["url"] for item in data.get("buildpacks", [])]
    assert buildpacks == [
        "https://github.com/heroku/heroku-buildpack-activestorage-preview",
        "heroku/python",
    ], "ffmpeg buildpack first, Python last"


def test_heroku_uses_buildpacks_not_container():
    assert not (ROOT / "heroku.yml").exists()
    assert not (ROOT / "Aptfile").exists()

    slugignore = (ROOT / ".slugignore").read_text(encoding="utf-8")
    assert "requirements.txt" in slugignore
    assert "tests" in slugignore

    # The Python buildpack installs from uv.lock; keeping requirements.txt in
    # the slug would make the classic buildpack reject the app.
    assert (ROOT / "uv.lock").exists()
