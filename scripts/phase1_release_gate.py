#!/usr/bin/env python3
"""Run the Phase 1 stabilization gate and write a reproducible JSON report."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DATASET_GROUPS = {
    "document_print_copy": ROOT / "test_dataset/document_print_copy",
    "active_liveness": ROOT / "test_dataset/active_liveness",
    "selfie_passive_liveness": ROOT / "test_dataset/selfie_passive_liveness_face_login",
    "face_login": ROOT / "test_dataset/face_login",
    "face_matching": ROOT / "test_dataset/face_matching",
}


def run_check(
    name: str,
    command: list[str],
    env: dict[str, str],
    cwd: Path = ROOT,
) -> dict:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
        return {
            "name": name,
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": command,
            "output_tail": completed.stdout[-12000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "status": "failed",
            "exit_code": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": command,
            "output_tail": str(exc),
        }


def command_output(command: list[str], fallback: str = "unknown") -> str:
    try:
        return subprocess.check_output(command, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback


def dataset_inventory() -> dict[str, dict]:
    inventory: dict[str, dict] = {}
    for group, path in DATASET_GROUPS.items():
        classes: dict[str, int] = {}
        if path.exists():
            for child in sorted(item for item in path.iterdir() if item.is_dir()):
                classes[child.name] = sum(
                    1 for file in child.rglob("*") if file.suffix.lower() in IMAGE_SUFFIXES
                )
        inventory[group] = {
            "path": str(path.relative_to(ROOT)),
            "total_images": sum(classes.values()),
            "classes": classes,
            "readiness": "present" if classes and all(classes.values()) else "incomplete",
        }
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="outputs/phase1/release-gate.json")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    python = ROOT / ".venv/bin/python"
    if not python.exists():
        python = Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")

    checks = [run_check("backend_compile", [str(python), "-m", "compileall", "-q", "backend/app"], env)]
    if not args.skip_tests:
        checks.append(run_check("backend_tests", [str(python), "-m", "pytest", "backend/tests", "-q"], env))
    if not args.skip_build:
        checks.append(run_check("frontend_build", ["npm", "--prefix", "frontend", "run", "build"], env))
        checks.append(run_check("typescript_sdk", ["npm", "--prefix", "sdk/typescript", "run", "typecheck"], env))
        checks.append(
            run_check(
                "flutter_sdk",
                ["flutter", "test"],
                env,
                cwd=ROOT / "sdk/flutter",
            )
        )

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_status": "passed" if all(check["status"] == "passed" for check in checks) else "failed",
        "release": {
            "git_commit": command_output(["git", "rev-parse", "HEAD"]),
            "git_dirty": bool(command_output(["git", "status", "--porcelain"], "")),
            "pipeline_version": os.getenv("LALIGENCE_PIPELINE_VERSION", "phase1-2026.07"),
            "decision_policy_version": os.getenv("LALIGENCE_DECISION_POLICY_VERSION", "2026.07-v1"),
            "build_sha": os.getenv("LALIGENCE_BUILD_SHA", command_output(["git", "rev-parse", "--short", "HEAD"])),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "node": command_output(["node", "--version"]),
            "npm": command_output(["npm", "--version"]),
        },
        "checks": checks,
        "dataset_inventory": dataset_inventory(),
        "notes": [
            "Dataset readiness is advisory in milestone 1 and does not change gate_status.",
            "A passing gate is not evidence of NIST, ISO, PAD, or regulatory certification.",
        ],
    }

    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate_status": report["gate_status"], "report": str(report_path)}, indent=2))
    return 0 if report["gate_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
