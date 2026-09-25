"""Validate the deployment manifests.

Runs as a script from CI and is imported by tests/test_regressions.py, so the
same checks cover both gates. No third party dependency: render.yaml is read
line by line instead of parsed as YAML.
"""

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_COMMAND = "python -m Mikobot"

# Secrets must be prompted for, never written into a committed file.
SECRETS = {
    "API_ID",
    "API_HASH",
    "TOKEN",
    "OWNER_ID",
    "MONGO_DB_URI",
    "SUPPORT_CHAT",
    "SUPPORT_ID",
    "EVENT_LOGS",
    "MESSAGE_DUMP",
    "DEV_USERS",
    "DRAGONS",
    "DEMONS",
    "WOLVES",
    "TIGERS",
    "BL_CHATS",
    "GEMINI_API_KEY",
}


def _env_vars(text):
    """Return the env var keys declared under an envVars block, in order."""
    keys = []
    in_block = False
    for line in text.splitlines():
        if re.match(r"^\s*envVars:\s*$", line):
            in_block = True
            continue
        if in_block:
            match = re.match(r"^\s*-\s*key:\s*(\S+)\s*$", line)
            if match:
                keys.append(match.group(1))
            elif re.match(r"^\S", line):
                in_block = False
    return keys


def _secret_sync_false(text):
    """Return the set of keys that are declared with sync: false."""
    found = set()
    pattern = re.compile(r"-\s*key:\s*(\S+)\s*\n\s*sync:\s*false", re.MULTILINE)
    for key in pattern.findall(text):
        found.add(key)
    return found


def check_railway(errors):
    config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    build = config.get("build", {})
    if build.get("builder") != "DOCKERFILE":
        errors.append("railway.json: build.builder must be DOCKERFILE")
    dockerfile = build.get("dockerfilePath")
    if not dockerfile or not (ROOT / dockerfile).exists():
        errors.append(f"railway.json: build.dockerfilePath {dockerfile!r} does not exist")
    deploy = config.get("deploy", {})
    if deploy.get("startCommand") != START_COMMAND:
        errors.append(
            f"railway.json: deploy.startCommand must be {START_COMMAND!r}, "
            f"found {deploy.get('startCommand')!r}"
        )
    if deploy.get("restartPolicyType") not in {"ON_FAILURE", "ALWAYS", "NEVER"}:
        errors.append(
            "railway.json: deploy.restartPolicyType must be ON_FAILURE, ALWAYS or NEVER"
        )
    if "healthcheckPath" in deploy:
        errors.append(
            "railway.json: a long polling bot has no HTTP endpoint, drop deploy.healthcheckPath"
        )


def check_render(errors):
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")

    if "type: worker" not in text:
        errors.append("render.yaml: the service must be type worker, not a web service")
    if "runtime: docker" not in text:
        errors.append("render.yaml: the service must use runtime docker")

    dockerfile = re.search(r"^\s*dockerfilePath:\s*(\S+)\s*$", text, re.MULTILINE)
    if not dockerfile or not (ROOT / dockerfile.group(1).lstrip("./")).exists():
        errors.append("render.yaml: dockerfilePath must point at an existing Dockerfile")

    command = re.search(r"^\s*dockerCommand:\s*(.+?)\s*$", text, re.MULTILINE)
    if not command or command.group(1) != START_COMMAND:
        errors.append(
            f"render.yaml: dockerCommand must be {START_COMMAND!r}, "
            f"found {command.group(1) if command else None!r}"
        )

    keys = _env_vars(text)
    if len(keys) != len(set(keys)):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        errors.append(f"render.yaml: duplicate env vars {duplicates}")

    missing = sorted(SECRETS - set(_secret_sync_false(text)))
    if missing:
        errors.append(f"render.yaml: these must use sync: false, found literal values: {missing}")

    if "ENV" not in keys:
        errors.append("render.yaml: ENV must be set so the environment is read instead of variables.py")

    if re.search(r"-\s*key:\s*DATABASE_URL\s*\n\s*value:", text):
        errors.append("render.yaml: DATABASE_URL must come from fromDatabase, not a literal value")

    reference = re.search(r"fromDatabase:\s*\n\s*name:\s*(\S+)", text)
    databases = re.findall(r"^\s{2}-\s*name:\s*(\S+)\s*$", text.split("databases:", 1)[-1], re.MULTILINE)
    if not reference:
        errors.append("render.yaml: DATABASE_URL must be wired with fromDatabase")
    elif reference.group(1) not in databases:
        errors.append(
            f"render.yaml: fromDatabase references {reference.group(1)!r}, "
            f"declared databases are {databases}"
        )

    for field in ("plan", "name", "dockerfilePath", "dockerContext"):
        if not re.search(rf"^\s*{field}:", text, re.MULTILINE):
            errors.append(f"render.yaml: missing {field}")


def check_start_command_is_uniform(errors):
    """Every deployment entry point must run the same command."""
    procfile = (ROOT / "Procfile").read_text(encoding="utf-8").strip()
    if procfile != f"worker: {START_COMMAND}":
        errors.append(f"Procfile: must be 'worker: {START_COMMAND}', found {procfile!r}")

    heroku_yml = (ROOT / "heroku.yml").read_text(encoding="utf-8")
    if f"worker: {START_COMMAND}" not in heroku_yml:
        errors.append(f"heroku.yml: run block must use worker: {START_COMMAND}")

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    if f'"-m", "Mikobot"' not in dockerfile.replace("'", '"'):
        errors.append("Dockerfile: CMD must run python -m Mikobot")


def main():
    errors = []
    for check in (check_railway, check_render, check_start_command_is_uniform):
        check(errors)
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("deployment manifests ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
