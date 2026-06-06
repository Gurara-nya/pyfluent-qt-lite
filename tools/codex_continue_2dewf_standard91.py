from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
from datetime import datetime
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(os.environ.get("CODEX_PYFLUENT_REPO", r"F:\pyfluent_qt_lit"))
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QCoreApplication

from pyfluent_qt_lite.app import AppSignals, FluentController

try:
    import h5py
except Exception as exc:  # pragma: no cover - checked at runtime in preflight.
    h5py = None
    H5PY_IMPORT_ERROR = exc
else:
    H5PY_IMPORT_ERROR = None


SOURCE_DIR = Path(r"D:\Workshop\Case\2DEWF\morestep")
SOURCE_CASE = SOURCE_DIR / "standard-91.cas.h5"
SOURCE_DAT = SOURCE_DIR / "standard-91-10600.dat.h5"
OUTPUT_ROOT = SOURCE_DIR / "codex_continue_10600"
UDF_PROJECT = Path(r"F:\C32H66-Study\cfd\axisymmetric_film_steady_package")

START_ITER = 10600
TARGET_ITER = 14600
OFFICIAL_CHECKPOINT_STEP = 600
OFFICIAL_CHECKPOINTS = [11200, 11800, 12400, 13000, 13600, 14200, 14600]
RECOVERY_CHECKPOINT_STEP = 100
CHECKPOINTS = list(range(START_ITER + RECOVERY_CHECKPOINT_STEP, TARGET_ITER + 1, RECOVERY_CHECKPOINT_STEP))

DIMENSION = "2D"
CORES = 16
SHUTDOWN_WAIT_SECONDS = 5.0
RESTART_SLEEP_SECONDS = 10.0

BRANCHES: dict[str, dict[str, Any]] = {
    "unchanged": {"courant": None},
    "flow-courant-350": {"courant": 350.0},
}

RUNNER_NAME = "codex_continue_2dewf_standard91"
CHECKPOINT_RE_TEMPLATE = r"^standard-91-{branch}-(\d{{5}})\.dat\.h5$"

current_log_fh = None


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def branch_dir(branch: str) -> Path:
    return OUTPUT_ROOT / branch


def state_path(branch: str) -> Path:
    return branch_dir(branch) / f"{RUNNER_NAME}_state.json"


def checkpoint_dat(branch: str, iteration: int) -> Path:
    return branch_dir(branch) / f"standard-91-{branch}-{iteration:05d}.dat.h5"


def checkpoint_case(branch: str, iteration: int) -> Path:
    return branch_dir(branch) / f"standard-91-{branch}-{iteration:05d}.cas.h5"


def log_path(branch: str, run_id: str) -> Path:
    return branch_dir(branch) / f"{RUNNER_NAME}_{branch}_{run_id}.log"


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_state(branch: str, status: str, stage: str, message: str = "", extra: dict[str, Any] | None = None) -> None:
    data: dict[str, Any] = {
        "runner": RUNNER_NAME,
        "status": status,
        "stage": stage,
        "message": message,
        "updated_at": iso_now(),
        "pid": os.getpid(),
        "branch": branch,
        "work_dir": str(branch_dir(branch)),
        "source_case": str(SOURCE_CASE),
        "source_dat": str(SOURCE_DAT),
        "start_iteration": START_ITER,
        "target_iteration": TARGET_ITER,
        "checkpoint_step": RECOVERY_CHECKPOINT_STEP,
        "official_checkpoint_step": OFFICIAL_CHECKPOINT_STEP,
        "official_checkpoints": OFFICIAL_CHECKPOINTS,
        "checkpoints": CHECKPOINTS,
        "dimension": DIMENSION,
        "cores": CORES,
        "courant_target": BRANCHES[branch]["courant"],
    }
    if extra:
        data.update(extra)
    write_json_atomic(state_path(branch), data)


def log_line(text: str) -> None:
    value = str(text)
    if current_log_fh:
        current_log_fh.write(value)
        if not value.endswith("\n"):
            current_log_fh.write("\n")
    print(value, end="" if value.endswith("\n") else "\n", flush=True)


def hdf5_readable(path: Path) -> bool:
    if h5py is None:
        raise RuntimeError(f"h5py is not available: {H5PY_IMPORT_ERROR}")
    with h5py.File(path, "r"):
        return True


def validate_nonempty_hdf5(path: Path, label: str) -> int:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"{label} is empty: {path}")
    hdf5_readable(path)
    return size


def validate_dat(path: Path) -> int:
    return validate_nonempty_hdf5(path, "DAT")


def validate_case(path: Path) -> int:
    return validate_nonempty_hdf5(path, "CAS")


def checkpoint_iteration(path: Path, branch: str) -> int | None:
    pattern = CHECKPOINT_RE_TEMPLATE.format(branch=re.escape(branch))
    match = re.match(pattern, path.name)
    if not match:
        return None
    return int(match.group(1))


def find_latest_checkpoint(branch: str) -> tuple[int, Path, Path] | None:
    work = branch_dir(branch)
    if not work.exists():
        return None
    candidates: list[int] = []
    for path in work.glob(f"standard-91-{branch}-*.dat.h5"):
        iteration = checkpoint_iteration(path, branch)
        if iteration is not None:
            candidates.append(iteration)
    for iteration in sorted(set(candidates), reverse=True):
        dat = checkpoint_dat(branch, iteration)
        case = checkpoint_case(branch, iteration)
        try:
            validate_dat(dat)
            validate_case(case)
        except Exception as exc:
            log_line(f"[{iso_now()}] checkpoint-skip: {iteration} is not a valid restart pair: {exc}")
            continue
        return iteration, case, dat
    return None


def next_checkpoint_after(iteration: int) -> int | None:
    for checkpoint in CHECKPOINTS:
        if checkpoint > iteration:
            return checkpoint
    return None


def preflight() -> None:
    validate_case(SOURCE_CASE)
    validate_dat(SOURCE_DAT)
    if not UDF_PROJECT.exists() or not UDF_PROJECT.is_dir():
        raise FileNotFoundError(f"UDF project not found: {UDF_PROJECT}")
    if CHECKPOINTS[-1] != TARGET_ITER:
        raise RuntimeError("Final checkpoint must equal TARGET_ITER")
    if OFFICIAL_CHECKPOINTS[-1] != TARGET_ITER:
        raise RuntimeError("Final official checkpoint must equal TARGET_ITER")
    if not set(OFFICIAL_CHECKPOINTS).issubset(set(CHECKPOINTS)):
        raise RuntimeError("Official checkpoints must be included in recovery checkpoints")
    if CHECKPOINTS[0] - START_ITER > RECOVERY_CHECKPOINT_STEP:
        raise RuntimeError("First checkpoint is farther than RECOVERY_CHECKPOINT_STEP from START_ITER")
    for left, right in zip(CHECKPOINTS, CHECKPOINTS[1:]):
        if right - left > RECOVERY_CHECKPOINT_STEP:
            raise RuntimeError("Checkpoint spacing exceeds RECOVERY_CHECKPOINT_STEP")


def dry_run(selected_branches: list[str]) -> None:
    preflight()
    data = {
        "source_case": str(SOURCE_CASE),
        "source_dat": str(SOURCE_DAT),
        "output_root": str(OUTPUT_ROOT),
        "udf_project": str(UDF_PROJECT),
        "dimension": DIMENSION,
        "cores": CORES,
        "start_iteration": START_ITER,
        "target_iteration": TARGET_ITER,
        "official_checkpoint_step": OFFICIAL_CHECKPOINT_STEP,
        "official_checkpoints": OFFICIAL_CHECKPOINTS,
        "recovery_checkpoint_step": RECOVERY_CHECKPOINT_STEP,
        "checkpoints": CHECKPOINTS,
        "branches": {},
    }
    for branch in selected_branches:
        latest = find_latest_checkpoint(branch)
        start = latest[0] if latest else START_ITER
        case = latest[1] if latest else SOURCE_CASE
        dat = latest[2] if latest else SOURCE_DAT
        data["branches"][branch] = {
            "work_dir": str(branch_dir(branch)),
            "courant_target": BRANCHES[branch]["courant"],
            "resume_iteration": start,
            "resume_case": str(case),
            "resume_dat": str(dat),
            "remaining_checkpoints": [item for item in CHECKPOINTS if item > start],
        }
    print(json.dumps(data, ensure_ascii=False, indent=2))


def probe_own_session_online(session: object | None) -> bool | None:
    if session is None:
        return False
    version = getattr(session, "get_fluent_version", None)
    if callable(version):
        try:
            version()
            return True
        except Exception:
            return False
    scheme_eval = getattr(session, "scheme_eval", None)
    scheme_exec = getattr(scheme_eval, "exec", None)
    if callable(scheme_exec):
        try:
            scheme_exec(("(+ 1 1)",), wait=True, silent=True)
            return True
        except Exception:
            return False
    return None


def shutdown_own_fluent_and_verify(controller: FluentController | None) -> dict[str, Any]:
    if controller is None:
        return {"shutdown_attempted": False, "fluent_shutdown_verified": True}
    session = controller.session
    result: dict[str, Any] = {
        "shutdown_attempted": session is not None,
        "shutdown_wait_seconds": SHUTDOWN_WAIT_SECONDS,
    }
    try:
        controller.shutdown()
    except Exception as exc:
        result["shutdown_error"] = f"{type(exc).__name__}: {exc}"
    if SHUTDOWN_WAIT_SECONDS > 0:
        time.sleep(SHUTDOWN_WAIT_SECONDS)
    online = probe_own_session_online(session)
    if online is True:
        result["shutdown_probe"] = "online"
        result["fluent_shutdown_verified"] = False
    elif online is False:
        result["shutdown_probe"] = "offline"
        result["fluent_shutdown_verified"] = True
    else:
        result["shutdown_probe"] = "unavailable"
        result["fluent_shutdown_verified"] = None
    return result


def connect_signals(signals: AppSignals) -> None:
    def on_log(text: str) -> None:
        value = str(text or "")
        if current_log_fh:
            current_log_fh.write(value)
        if value.startswith("["):
            print(value, end="", flush=True)

    def on_status(text: str) -> None:
        log_line(f"[{iso_now()}] status: {text}")

    signals.log.connect(on_log)
    signals.status.connect(on_status)


def setting_get(setting: Any) -> float:
    getter = getattr(setting, "get_state", None)
    if callable(getter):
        return float(getter())
    caller = getattr(setting, "__call__", None)
    if callable(caller):
        return float(caller())
    return float(setting)


def setting_set(setting: Any, value: float) -> None:
    setter = getattr(setting, "set_state", None)
    if callable(setter):
        setter(float(value))
        return
    if callable(setting):
        setting(float(value))
        return
    raise RuntimeError(f"Setting object is not writable: {setting!r}")


def get_attr_path(root: Any, path: tuple[str, ...]) -> Any:
    obj = root
    for name in path:
        obj = getattr(obj, name)
    return obj


def set_flow_courant(controller: FluentController, value: float) -> tuple[str, float]:
    session = controller.session
    if session is None:
        raise RuntimeError("Fluent session is not available")
    paths = [
        ("settings", "solution", "controls", "p_v_controls", "flow_courant_number"),
        ("settings", "solution", "controls", "zonal_pbns_solution_controls", "flow_courant_number"),
        ("settings", "solution", "controls", "courant_number"),
    ]
    errors: list[str] = []
    for path in paths:
        dotted = ".".join(path)
        try:
            setting = get_attr_path(session, path)
            before = setting_get(setting)
            setting_set(setting, value)
            after = setting_get(setting)
            if abs(after - value) <= max(1e-9, abs(value) * 1e-9):
                log_line(f"[{iso_now()}] courant: {dotted} {before:.12g} -> {after:.12g}")
                return dotted, after
            errors.append(f"{dotted}: readback {after:.12g}, expected {value:.12g}")
        except Exception as exc:
            errors.append(f"{dotted}: {type(exc).__name__}: {exc}")

    tui_paths = [
        ("solve", "set", "p_v_controls", "flow_courant_number"),
        ("solve", "set", "zonal_pbns_solution_controls", "flow_courant_number"),
    ]
    for path in tui_paths:
        dotted = "tui." + ".".join(path)
        try:
            command = get_attr_path(session.tui, path)
            command(float(value))
            setting = get_attr_path(session, paths[0])
            after = setting_get(setting)
            if abs(after - value) <= max(1e-9, abs(value) * 1e-9):
                log_line(f"[{iso_now()}] courant: {dotted} -> {after:.12g}")
                return dotted, after
            errors.append(f"{dotted}: readback {after:.12g}, expected {value:.12g}")
        except Exception as exc:
            errors.append(f"{dotted}: {type(exc).__name__}: {exc}")

    raise RuntimeError("Unable to set Flow Courant Number. Attempts: " + " | ".join(errors))


def run_attempt(branch: str, attempt: int, resume_iteration: int, resume_case: Path, resume_dat: Path) -> tuple[bool, int]:
    global current_log_fh
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = branch_dir(branch)
    work.mkdir(parents=True, exist_ok=True)
    log_file = log_path(branch, run_id)
    controller: FluentController | None = None
    current_iteration = resume_iteration
    current_log_fh = log_file.open("a", encoding="utf-8", buffering=1)

    try:
        write_state(
            branch,
            "running",
            "launch",
            f"Attempt {attempt}: launching from {resume_iteration}",
            {
                "attempt": attempt,
                "run_id": run_id,
                "log_file": str(log_file),
                "resume_iteration": resume_iteration,
                "resume_case": str(resume_case),
                "resume_dat": str(resume_dat),
            },
        )
        log_line(f"[{iso_now()}] launch: branch={branch} attempt={attempt} resume={resume_iteration}")
        QCoreApplication.instance() or QCoreApplication([])
        signals = AppSignals()
        connect_signals(signals)
        controller = FluentController(signals)

        controller.launch(str(work), str(resume_case), DIMENSION, CORES, False, False, "")
        write_state(branch, "running", "read_data", f"Reading DAT {resume_dat}", {"attempt": attempt})
        controller.read_data(str(resume_dat))

        write_state(branch, "running", "load_udf", f"Compiling and loading UDF: {UDF_PROJECT}", {"attempt": attempt})
        controller.build_and_load_udf(str(UDF_PROJECT))

        courant_target = BRANCHES[branch]["courant"]
        courant_result: dict[str, Any] = {}
        if courant_target is not None:
            write_state(branch, "running", "set_courant", f"Setting Flow Courant Number to {courant_target}", {"attempt": attempt})
            method, readback = set_flow_courant(controller, float(courant_target))
            courant_result = {"courant_method": method, "courant_readback": readback}

        while current_iteration < TARGET_ITER:
            next_iter = next_checkpoint_after(current_iteration)
            if next_iter is None:
                break
            step = next_iter - current_iteration
            write_state(
                branch,
                "running",
                "iterate",
                f"Running {step} iterations: {current_iteration}->{next_iter}",
                {
                    "attempt": attempt,
                    "run_id": run_id,
                    "current_iteration": current_iteration,
                    "next_checkpoint": next_iter,
                    **courant_result,
                },
            )
            controller.start_calculation(step)

            dat_out = checkpoint_dat(branch, next_iter)
            case_out = checkpoint_case(branch, next_iter)
            write_state(branch, "running", "save_data", f"Writing {dat_out}", {"attempt": attempt, "current_iteration": next_iter})
            controller.write_data(str(dat_out))
            dat_size = validate_dat(dat_out)

            write_state(branch, "running", "save_case", f"Writing {case_out}", {"attempt": attempt, "current_iteration": next_iter})
            controller.write_case(str(case_out))
            case_size = validate_case(case_out)

            current_iteration = next_iter
            write_state(
                branch,
                "running" if current_iteration < TARGET_ITER else "success",
                "checkpoint" if current_iteration < TARGET_ITER else "complete",
                f"Checkpoint {current_iteration} saved",
                {
                    "attempt": attempt,
                    "run_id": run_id,
                    "current_iteration": current_iteration,
                    "latest_case": str(case_out),
                    "latest_dat": str(dat_out),
                    "latest_case_size": case_size,
                    "latest_dat_size": dat_size,
                    **courant_result,
                },
            )
            log_line(f"[{iso_now()}] checkpoint: branch={branch} iter={current_iteration} dat={dat_size} case={case_size}")

        shutdown_info = shutdown_own_fluent_and_verify(controller)
        controller = None
        write_state(
            branch,
            "success",
            "complete",
            f"Branch {branch} reached {current_iteration}",
            {
                "attempt": attempt,
                "run_id": run_id,
                "current_iteration": current_iteration,
                **shutdown_info,
                **courant_result,
            },
        )
        return current_iteration >= TARGET_ITER, current_iteration
    except Exception as exc:
        tb = traceback.format_exc()
        log_line(tb)
        shutdown_info = shutdown_own_fluent_and_verify(controller)
        write_state(
            branch,
            "failed_attempt",
            "failed",
            f"{type(exc).__name__}: {exc}",
            {
                "attempt": attempt,
                "run_id": run_id,
                "current_iteration": current_iteration,
                "traceback": tb,
                **shutdown_info,
            },
        )
        return False, current_iteration
    finally:
        if current_log_fh:
            with contextlib.suppress(Exception):
                current_log_fh.close()
        current_log_fh = None


def run_branch(branch: str) -> None:
    preflight()
    work = branch_dir(branch)
    work.mkdir(parents=True, exist_ok=True)
    attempt = 1
    while True:
        latest = find_latest_checkpoint(branch)
        if latest:
            resume_iteration, resume_case, resume_dat = latest
        else:
            resume_iteration, resume_case, resume_dat = START_ITER, SOURCE_CASE, SOURCE_DAT

        if resume_iteration >= TARGET_ITER:
            write_state(
                branch,
                "success",
                "complete",
                f"Existing checkpoint already reaches {TARGET_ITER}",
                {
                    "current_iteration": resume_iteration,
                    "latest_case": str(resume_case),
                    "latest_dat": str(resume_dat),
                },
            )
            log_line(f"[{iso_now()}] complete: {branch} already has valid {TARGET_ITER} checkpoint")
            return

        ok, current_iteration = run_attempt(branch, attempt, resume_iteration, resume_case, resume_dat)
        if ok:
            log_line(f"[{iso_now()}] complete: branch={branch} reached {current_iteration}")
            return
        attempt += 1
        write_state(
            branch,
            "restarting",
            "restart_wait",
            f"Attempt will restart in {RESTART_SLEEP_SECONDS} seconds",
            {"attempt": attempt, "last_iteration_seen": current_iteration},
        )
        time.sleep(RESTART_SLEEP_SECONDS)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continue 2DEWF standard-91 from 10600 to 14600 in two Courant branches.")
    parser.add_argument("--branch", choices=["all", *BRANCHES.keys()], default="all")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def selected_branches(value: str) -> list[str]:
    return list(BRANCHES) if value == "all" else [value]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    branches = selected_branches(args.branch)
    if args.dry_run:
        dry_run(branches)
        return 0
    for branch in branches:
        run_branch(branch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
