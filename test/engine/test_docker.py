"""Checks on docker/. The static ones need no Docker daemon, and guard that settings and Terraform
state stay out of the image and that the app stays on localhost.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "docker"
ALLOWED = {
    "requirements.txt",
    "app/engine/",
    "app/front/",
    "script/serve.py",
    "vendor/geolocate/src/",
}
SECRETS = (".asset-risk.json", ".geolocate.json", "*.tfstate*", "*.tfvars", ".env", ".env.*")
PROJECT = "asset-risk-test"
TEST_PORT = "18765"


def _rules() -> list[str]:
    lines = (line.strip() for line in (DOCKER / "Dockerfile.dockerignore").read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def test_dockerignore_is_an_allow_list():
    rules = _rules()
    assert rules[0] == "*"
    assert {r[1:] for r in rules if r.startswith("!")} == ALLOWED


def test_dockerignore_leaves_out_host_build_output():
    rules = _rules()
    assert "app/front/node_modules" in rules
    assert "app/front/dist" in rules


def test_no_allowed_path_is_a_secret():
    for path in ALLOWED:
        assert not any(fnmatch.fnmatch(Path(path).name, secret) for secret in SECRETS)


def test_dockerfile_copies_only_allowed_paths():
    dockerfile = (DOCKER / "Dockerfile").read_text()
    copies = re.findall(r"^COPY\s+(?!--from)(.+)$", dockerfile, re.MULTILINE)
    sources = {source for line in copies for source in line.split()[:-1]}
    for source in sources:
        assert any(source == path or source.startswith(path) for path in ALLOWED), source


def test_dockerfile_runs_as_a_user_and_points_at_the_mounts():
    dockerfile = (DOCKER / "Dockerfile").read_text()
    assert "USER app" in dockerfile
    assert "ASSET_RISK_CONFIG=/config/.asset-risk.json" in dockerfile
    assert "GEOLOCATE_CONFIG=/config/.geolocate.json" in dockerfile
    assert "ASSET_RISK_DATA_DIR=/data" in dockerfile


def test_compose_only_publishes_on_localhost():
    compose = (DOCKER / "compose.yml").read_text()
    published = re.findall(r'^\s*- "(.*:8000)"$', compose, re.MULTILINE)
    assert published == ["127.0.0.1:${API_PORT:-8000}:8000"]
    assert "0.0.0.0" not in compose


def test_compose_mounts_settings_read_only():
    compose = (DOCKER / "compose.yml").read_text()
    assert "../.asset-risk.json:/config/.asset-risk.json:ro" in compose
    assert "../vendor/geolocate/.geolocate.json:/config/.geolocate.json:ro" in compose


def test_start_script_explains_what_is_missing(tmp_path):
    root = tmp_path / "repo"
    (root / "script").mkdir(parents=True)
    shutil.copy(ROOT / "script" / "start.sh", root / "script" / "start.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        '[ "$1" = compose ] && [ "$2" = version ] && exit 0\n'
        f'echo "$HOST_UID $API_PORT $*" > {tmp_path}/called\n'
    )
    fake_docker.chmod(0o755)
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    env.pop("API_PORT", None)

    def start():
        return subprocess.run(
            ["bash", "script/start.sh"], cwd=root, env=env, capture_output=True, text=True
        )

    assert "git submodule update --init" in start().stderr

    (root / "vendor/geolocate/src").mkdir(parents=True)
    (root / "vendor/geolocate/src/geolocate.py").touch()
    assert ".asset-risk.json is missing" in start().stderr

    (root / ".asset-risk.json").write_text(json.dumps({"api_port": 9123}))
    assert ".geolocate.json is missing" in start().stderr

    (root / "vendor/geolocate/.geolocate.json").touch()
    result = start()
    assert result.returncode == 0
    assert "http://127.0.0.1:9123" in result.stdout
    called = (tmp_path / "called").read_text()
    assert called.startswith(f"{os.getuid()} 9123 compose")
    assert "up --build" in called


def _compose(*args, **kwargs):
    env = os.environ | {
        "API_PORT": TEST_PORT,
        "HOST_UID": str(os.getuid()),
        "HOST_GID": str(os.getgid()),
    }
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", str(DOCKER / "compose.yml"), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _get(path: str) -> bytes:
    with urllib.request.urlopen(f"http://127.0.0.1:{TEST_PORT}{path}", timeout=5) as response:
        return response.read()


@pytest.mark.e2e
def test_the_stack_starts_and_serves_the_app():
    """Uses its own project, port and volume, so it can't touch a running copy of the app."""
    try:
        _compose("up", "--build", "--detach", timeout=1200)
        for _ in range(60):
            try:
                if json.loads(_get("/api/health")) == {"status": "ok"}:
                    break
            except OSError:
                time.sleep(1)
        else:
            raise AssertionError(_compose("logs").stdout)
        assert b'<div id="root">' in _get("/")
        assert b"id,lat,lon" in _get("/sample_portfolio.csv")
        assert json.loads(_get("/api/runs")) == []
    finally:
        _compose("down", "--volumes")


@pytest.mark.e2e
def test_the_image_holds_no_settings_or_state():
    _compose("build", timeout=1200)
    image = _compose("config", "--images").stdout.strip()
    names = " -o ".join(f"-name '{secret}'" for secret in SECRETS)
    found = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "root",  # so find can read every folder
            "--entrypoint",
            "sh",
            image,
            "-c",
            f"find / -xdev \\( {names} \\)",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert found.strip() == ""
