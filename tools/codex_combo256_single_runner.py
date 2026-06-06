from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(os.environ.get("CODEX_PYFLUENT_REPO", r"F:\pyfluent_qt_lit"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TOOLS))

from PySide6.QtCore import QCoreApplication, QSettings

from pyfluent_qt_lite.app import (
    AppSignals,
    FluentController,
    normalize_workflow,
)

import sweep
import sweep_config


def required_int_env(name: str, description: str) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raise RuntimeError(f"{name} must be set; {description} is required campaign input.")
    return int(raw)


def combo_label(index: int) -> str:
    return f"combo-{index:03d}"


DEFAULT_WORK = REPO / "fluent_outputs" / "mesh_independence_700__20260522-20260523" / "cas_dat"
WORK = Path(os.environ.get("CODEX_COMBO256_WORK", str(DEFAULT_WORK)))
BASE_CASE = Path(os.environ.get("CODEX_COMBO256_BASE_CASE", str(WORK / "standard-bl12um-h290um.cas.h5")))
DEFAULT_MESH_DIR = (
    r"D:\Workshop\Mesh\d-40\codex-mesh-package\04-fuelend040-060-revisit"
    r"\fuelend040-060-revisit\fuelend040-fw1600-flowopt"
)
MESH_DIR = Path(os.environ.get("CODEX_COMBO256_MESH_DIR", DEFAULT_MESH_DIR))
MESH_FILE_ENV = os.environ.get("CODEX_COMBO256_MESH_FILE", "")
UDF_DIR = Path(os.environ.get("CODEX_COMBO256_UDF_DIR", r"D:\Workshop\UDF\dpm-cal-udf"))
COMBO_INDEX = required_int_env("CODEX_COMBO256_COMBO_INDEX", "combo index")
DIMENSION = os.environ.get("CODEX_COMBO256_DIMENSION", "2D")
CORES = int(os.environ.get("CODEX_COMBO256_CORES", "16"))
ITERATIONS = int(os.environ.get("CODEX_COMBO256_ITERATIONS", "700"))
ITERATION_CHUNK = int(os.environ.get("CODEX_COMBO256_ITERATION_CHUNK", "10"))
OUTPUT_TAG = os.environ.get("CODEX_COMBO256_OUTPUT_TAG", "fuelend040-fw1600-flowopt-iter700")
RUN_ID = os.environ.get("CODEX_COMBO256_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")
STATE = Path(os.environ.get("CODEX_COMBO256_STATE", str(WORK / f"codex_combo256_{OUTPUT_TAG}_state.json")))
LOG = Path(os.environ.get("CODEX_COMBO256_LOG", str(WORK / f"codex_combo256_{OUTPUT_TAG}_run_{RUN_ID}.log")))
PREPARED_CASE = Path(
    os.environ.get(
        "CODEX_COMBO256_PREPARED_CASE",
        str(WORK / f"standard-bl12um-h290um-{OUTPUT_TAG}.cas.h5"),
    )
)
FINAL_CASE = Path(os.environ.get("CODEX_COMBO256_FINAL_CASE", str(PREPARED_CASE)))
DATA_FILE = Path(os.environ.get("CODEX_COMBO256_DATA_FILE", str(WORK / f"{combo_label(COMBO_INDEX)}-{OUTPUT_TAG}.dat.h5")))
INITIALIZED_CASE_ENV = os.environ.get("CODEX_COMBO256_INITIALIZED_CASE", "")
INITIALIZED_CASE = Path(INITIALIZED_CASE_ENV) if INITIALIZED_CASE_ENV else None
STDOUT_LOG = os.environ.get("CODEX_COMBO256_STDOUT", "")
STDERR_LOG = os.environ.get("CODEX_COMBO256_STDERR", "")
SHUTDOWN_WAIT_SECONDS = float(os.environ.get("CODEX_COMBO256_SHUTDOWN_WAIT_SECONDS", "5"))

FIRST_INIT_NAME = "\u7b2c\u4e00\u6b21\u521d\u59cb\u5316"
INIT_DYNAMIC_NAME = "\u521d\u59cb\u5316 + Use_Dynamic_Sources"

current_stage = "starting"
log_fh = None
controller = None


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_state(status: str = "running", stage: str | None = None, message: str = "", extra: dict | None = None) -> None:
    data = {
        "status": status,
        "stage": stage or current_stage,
        "message": str(message),
        "updated_at": iso_now(),
        "run_id": RUN_ID,
        "pid": os.getpid(),
        "work_dir": str(WORK),
        "base_case": str(BASE_CASE),
        "mesh_dir": str(MESH_DIR),
        "udf_dir": str(UDF_DIR),
        "prepared_case": str(PREPARED_CASE),
        "final_case": str(FINAL_CASE),
        "initialized_case": str(INITIALIZED_CASE) if INITIALIZED_CASE else "",
        "data_file": str(DATA_FILE),
        "log_file": str(LOG),
        "stdout_log": STDOUT_LOG,
        "stderr_log": STDERR_LOG,
        "combo_index": COMBO_INDEX,
        "combo_label": sweep.combo_label(COMBO_INDEX),
        "output_tag": OUTPUT_TAG,
        "dimension": DIMENSION,
        "cores": CORES,
        "iterations": ITERATIONS,
        "iteration_chunk": ITERATION_CHUNK,
    }
    if extra:
        data.update(extra)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def set_stage(stage: str, message: str = "") -> None:
    global current_stage
    current_stage = stage
    write_state(stage=stage, message=message)
    line = f"[{iso_now()}] {stage}: {message}\n"
    if log_fh:
        log_fh.write(line)
    print(line, end="", flush=True)


def saved_file_info(path: Path) -> dict[str, object]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists else 0,
    }


def require_saved_file(path: Path, label: str) -> int:
    info = saved_file_info(path)
    if not info["exists"] or int(info["size"]) <= 0:
        raise RuntimeError(f"{label} was not saved or is empty: {path}")
    return int(info["size"])


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


def shutdown_own_fluent_and_verify() -> dict[str, object]:
    global controller
    if controller is None:
        return {
            "shutdown_attempted": False,
            "shutdown_probe": "no-controller",
            "fluent_shutdown_verified": True,
        }
    session = controller.session
    result: dict[str, object] = {
        "shutdown_attempted": session is not None,
        "shutdown_wait_seconds": SHUTDOWN_WAIT_SECONDS,
        "shutdown_probe": "not-started" if session is None else "pending",
        "fluent_shutdown_verified": session is None,
    }
    shutdown_error = ""
    try:
        controller.shutdown()
    except Exception as exc:
        shutdown_error = f"{type(exc).__name__}: {exc}"
        result["shutdown_error"] = shutdown_error
    if SHUTDOWN_WAIT_SECONDS > 0:
        time.sleep(SHUTDOWN_WAIT_SECONDS)
    online = probe_own_session_online(session)
    if online is True:
        result["shutdown_probe"] = "online"
        result["fluent_shutdown_verified"] = False
        raise RuntimeError(
            "Own Fluent session still responds after shutdown; "
            "leaving other Fluent sessions untouched."
        )
    if online is False:
        result["shutdown_probe"] = "offline"
        result["fluent_shutdown_verified"] = True
    else:
        result["shutdown_probe"] = "unavailable"
        result["fluent_shutdown_verified"] = None
    if shutdown_error and result["fluent_shutdown_verified"] is False:
        raise RuntimeError(f"Own Fluent shutdown failed: {shutdown_error}")
    controller = None
    return result


def find_mesh() -> Path:
    if MESH_FILE_ENV:
        mesh = Path(MESH_FILE_ENV)
        if not mesh.is_file():
            raise FileNotFoundError(f"Mesh file not found: {mesh}")
        return mesh
    candidates = sorted(MESH_DIR.glob("*fluent*.msh"))
    candidates += sorted(MESH_DIR.glob("*fluent*.msh.h5"))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No fluent-tagged mesh file found in {MESH_DIR}")
    return candidates[0]


def find_workflow(name: str) -> dict:
    settings = QSettings("pyfluent_qt_lite", "pyfluent_qt_lite")
    for key in ("automation_workflows", "sweep_workflows"):
        raw = settings.value(key, "") or ""
        if not raw:
            continue
        for item in json.loads(raw):
            if item.get("name") == name:
                return normalize_workflow(item)
    raise KeyError(f"Workflow not found: {name}")


def connect_signals(signals: AppSignals) -> None:
    def on_log(text: str) -> None:
        value = str(text or "")
        if log_fh:
            log_fh.write(value)
        if value.startswith("["):
            print(value, end="", flush=True)

    def on_status(text: str) -> None:
        write_state(stage=current_stage, message=str(text or ""))

    signals.log.connect(on_log)
    signals.status.connect(on_status)


def main() -> None:
    global log_fh, controller
    WORK.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_fh = LOG.open("a", encoding="utf-8", buffering=1)
    write_state(message="Runner process started")

    missing = [str(path) for path in (BASE_CASE, MESH_DIR, UDF_DIR) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required paths: " + "; ".join(missing))
    mesh_file = find_mesh()

    QCoreApplication.instance() or QCoreApplication([])
    signals = AppSignals()
    connect_signals(signals)
    controller = FluentController(signals)

    param_grid = sweep_config.PARAM_GRID
    combos = sweep.list_combos(param_grid)
    if COMBO_INDEX < 0 or COMBO_INDEX >= len(combos):
        raise IndexError(f"Combo index {COMBO_INDEX} out of range; total={len(combos)}")
    combo = combos[COMBO_INDEX]
    combo_info = sweep.combo_summary(combo)
    write_state(
        extra={
            "mesh_file": str(mesh_file),
            "combo_summary": combo_info,
            "total_combos": len(combos),
        }
    )

    set_stage("launch", f"Launching Fluent with base case: {BASE_CASE}")
    controller.launch(str(WORK), str(BASE_CASE), DIMENSION, CORES, False, False, "")

    set_stage("replace_mesh", f"Replacing mesh while keeping case settings: {mesh_file}")
    controller.read_mesh(str(mesh_file), keep_case=True)

    set_stage("compile_udf", f"Compiling and loading UDF: {UDF_DIR}")
    controller.build_and_load_udf(str(UDF_DIR))

    set_stage("save_prepared_case", f"Writing prepared case: {PREPARED_CASE}")
    controller.write_case(str(PREPARED_CASE))

    first_init = find_workflow(FIRST_INIT_NAME)
    set_stage("first_initialization", f"Running workflow: {FIRST_INIT_NAME}")
    controller.run_workflow(first_init)

    set_stage("define_rpvars", "Creating sweep rpvars")
    controller.define_sweep_rpvars(param_grid)

    set_stage("apply_combo", f"Applying {sweep.combo_label(COMBO_INDEX)}: {combo_info}")
    controller.apply_sweep_combo(combo, COMBO_INDEX, len(combos), reload_params=True)

    init_dynamic = find_workflow(INIT_DYNAMIC_NAME)
    set_stage("init_dynamic", f"Running workflow: {INIT_DYNAMIC_NAME}")
    controller.run_workflow(init_dynamic)

    if INITIALIZED_CASE is not None:
        set_stage("save_initialized_case", f"Writing initialized case: {INITIALIZED_CASE}")
        controller.write_case(str(INITIALIZED_CASE))

    done = 0
    chunk = max(1, ITERATION_CHUNK)
    while done < ITERATIONS:
        step = min(chunk, ITERATIONS - done)
        set_stage("iterate", f"Running iterations {done + 1}-{done + step} of {ITERATIONS}")
        controller.start_calculation(step)
        done += step
        write_state(stage="iterate", message=f"Completed {done}/{ITERATIONS} iterations", extra={"iterations_completed": done})

    set_stage("save_data", f"Writing data: {DATA_FILE}")
    controller.write_data(str(DATA_FILE))
    data_size = require_saved_file(DATA_FILE, "Data file")

    set_stage("save_final_case", f"Writing final case: {FINAL_CASE}")
    controller.write_case(str(FINAL_CASE))
    final_case_size = require_saved_file(FINAL_CASE, "Final case file")

    set_stage("shutdown", "Closing this runner's Fluent session")
    shutdown_info = shutdown_own_fluent_and_verify()

    write_state(
        status="success",
        stage="complete",
        message="Calculation complete",
        extra={
            "mesh_file": str(mesh_file),
            "combo_summary": combo_info,
            "total_combos": len(combos),
            "prepared_case_exists": PREPARED_CASE.exists(),
            "prepared_case_size": PREPARED_CASE.stat().st_size if PREPARED_CASE.exists() else 0,
            "final_case": str(FINAL_CASE),
            "final_case_exists": FINAL_CASE.exists(),
            "final_case_size": final_case_size,
            "data_file_exists": DATA_FILE.exists(),
            "data_file_size": data_size,
            **shutdown_info,
        },
    )
    print(f"[{iso_now()}] complete: success\n", end="", flush=True)
    if log_fh:
        log_fh.write(f"[{iso_now()}] complete: success\n")


try:
    main()
except Exception as exc:
    tb = traceback.format_exc()
    shutdown_info: dict[str, object] = {}
    try:
        if log_fh:
            log_fh.write(tb + "\n")
        print(tb, file=sys.stderr, flush=True)
    finally:
        if controller is not None:
            try:
                shutdown_info = shutdown_own_fluent_and_verify()
            except Exception as shutdown_exc:
                shutdown_info = {
                    "shutdown_after_failure_error": f"{type(shutdown_exc).__name__}: {shutdown_exc}",
                }
    try:
        write_state(
            status="failed",
            stage=current_stage,
            message=f"{type(exc).__name__}: {exc}",
            extra={"traceback": tb, **shutdown_info},
        )
    except Exception:
        pass
    sys.exit(1)
finally:
    if log_fh:
        with contextlib.suppress(Exception):
            log_fh.close()
