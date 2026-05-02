#!/usr/bin/env python3
"""Emit NDJSON for debug session: Railway config on disk + local docker/npm checks."""
# region agent log
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / ".cursor" / "debug-b60e9d.log"
SESSION = "b60e9d"
ROOT = Path(__file__).resolve().parents[1]


def _log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    line = {
        "sessionId": SESSION,
        "runId": os.environ.get("DEBUG_RUN_ID", "local"),
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _read_toml_build_section(path: Path) -> dict:
    if not path.is_file():
        return {"missing": True}
    text = path.read_text(encoding="utf-8")
    out = {"path": str(path.relative_to(ROOT)), "builder": None, "buildCommand": None, "dockerfilePath": None}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("builder"):
            out["builder"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("buildCommand"):
            out["buildCommand"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("dockerfilePath"):
            out["dockerfilePath"] = line.split("=", 1)[1].strip().strip('"')
    return out


def main() -> None:
    _log(
        "H1",
        "debug_railway_config.py:main",
        "railway.toml at repo root vs legacy app/web path (must not exist for main deploy)",
        {
            "root_railway": _read_toml_build_section(ROOT / "railway.toml"),
            "app_web_railway": _read_toml_build_section(ROOT / "app" / "web" / "railway.toml"),
            "static_example_exists": (ROOT / "railway.static.example.toml").is_file(),
            "dockerfile_exists": (ROOT / "Dockerfile").is_file(),
        },
    )
    npm = shutil.which("npm")
    _log(
        "H3",
        "debug_railway_config.py:main",
        "local PATH npm (dashboard buildCommand would fail similarly if no node)",
        {"npm_which": npm},
    )
    # H4: Dockerfile web-build stage should have npm inside container — verify docker build works
    if os.environ.get("SKIP_DOCKER") == "1":
        _log("H4", "debug_railway_config.py:docker_build", "skipped SKIP_DOCKER=1", {})
        return
    try:
        r = subprocess.run(
            ["docker", "build", "-t", "derby-debug-railway", "."],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        _log(
            "H4",
            "debug_railway_config.py:docker_build",
            "docker build from repo root",
            {
                "returncode": r.returncode,
                "stderr_tail": (r.stderr or "")[-2000:] if r.stderr else "",
            },
        )
    except FileNotFoundError:
        _log(
            "H4",
            "debug_railway_config.py:docker_build",
            "docker CLI not installed locally",
            {"docker": None},
        )
    except subprocess.TimeoutExpired as e:
        _log(
            "H4",
            "debug_railway_config.py:docker_build",
            "docker build timed out",
            {"stderr_tail": (e.stderr or "")[-1500:] if e.stderr else ""},
        )


if __name__ == "__main__":
    main()
# endregion
