from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

import h5py


REPO = Path(os.environ.get("CODEX_PYFLUENT_REPO", r"F:\pyfluent_qt_lit"))
RUNNER = REPO / "tools" / "codex_combo256_single_runner.py"
MESH_ROOT = Path(
    os.environ.get(
        "CODEX_MESH_INDEPENDENCE_ROOT",
        r"D:\Workshop\Mesh\d-40\codex-mesh-package\04-fuelend040-060-revisit\fuelend040-060-revisit",
    )
)
DEFAULT_PROJECT = REPO / "fluent_outputs" / "mesh_independence_700__20260522-20260523"
DEFAULT_WORK = DEFAULT_PROJECT / "cas_dat"
WORK = Path(os.environ.get("CODEX_COMBO256_WORK", str(DEFAULT_WORK)))
BASE_CASE = Path(os.environ.get("CODEX_COMBO256_BASE_CASE", str(WORK / "standard-bl12um-h290um.cas.h5")))
DEFAULT_RUN_ROOT = DEFAULT_PROJECT / "run"
RUN_ROOT = Path(os.environ.get("CODEX_BATCH_RUN_ROOT", str(DEFAULT_RUN_ROOT)))
ITERATIONS = int(os.environ.get("CODEX_COMBO256_ITERATIONS", "700"))
CORES = int(os.environ.get("CODEX_COMBO256_CORES", "16"))
MAX_ATTEMPTS = int(os.environ.get("CODEX_BATCH_MAX_ATTEMPTS", "3"))
INCLUDE_FW_RAW = os.environ.get("CODEX_MESH_INCLUDE_FW", "")
CONTINUE_ON_FAILURE = os.environ.get("CODEX_BATCH_CONTINUE_ON_FAILURE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}


def required_int_env(name: str, description: str) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raise RuntimeError(f"{name} must be set; {description} is required campaign input.")
    return int(raw)


COMBO_INDEX = required_int_env("CODEX_COMBO256_COMBO_INDEX", "combo index")


def parse_include_fw(raw: str) -> set[int] | None:
    raw = raw.strip()
    if not raw:
        return None
    values: set[int] = set()
    for part in re.split(r"[\s,;]+", raw):
        if not part:
            continue
        match = re.fullmatch(r"(?:fw)?(\d+)", part.strip(), flags=re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid CODEX_MESH_INCLUDE_FW item: {part!r}")
        values.add(int(match.group(1)))
    return values or None


INCLUDE_FW = parse_include_fw(INCLUDE_FW_RAW)


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sort_key(path: Path) -> tuple[int, int, str]:
    tag = path.parent.name
    fuel = re.search(r"fuelend(\d+)", tag)
    fw = re.search(r"fw(\d+)", tag)
    return (int(fuel.group(1)) if fuel else 10**9, int(fw.group(1)) if fw else 10**9, tag)


def fw_from_mesh(path: Path) -> int | None:
    match = re.search(r"fw(\d+)", path.parent.name)
    return int(match.group(1)) if match else None


def discover_meshes() -> list[Path]:
    meshes = sorted(MESH_ROOT.rglob("*-fluent.msh"), key=sort_key)
    seen: set[str] = set()
    unique: list[Path] = []
    for mesh in meshes:
        tag = mesh.parent.name
        if tag in seen:
            raise RuntimeError(f"Multiple fluent meshes discovered for tag {tag}: {mesh}")
        seen.add(tag)
        unique.append(mesh)
    if INCLUDE_FW is not None:
        filtered = [mesh for mesh in unique if fw_from_mesh(mesh) in INCLUDE_FW]
        found = {fw_from_mesh(mesh) for mesh in filtered}
        missing = sorted(fw for fw in INCLUDE_FW if fw not in found)
        if missing:
            raise RuntimeError(
                "Requested CODEX_MESH_INCLUDE_FW values were not found under "
                f"{MESH_ROOT}: {','.join(str(item) for item in missing)}"
            )
        unique = filtered
    return unique


def output_tag(mesh: Path) -> str:
    return f"{mesh.parent.name}-iter{ITERATIONS}"


def combo_label(index: int) -> str:
    return f"combo-{index:03d}"


def base_case_output_stem() -> str:
    name = BASE_CASE.name
    lower = name.lower()
    for suffix in (".cas.h5", ".cas"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return BASE_CASE.stem


def prepared_case_for(mesh: Path) -> Path:
    return WORK / f"{base_case_output_stem()}-{output_tag(mesh)}.cas.h5"


def final_case_for(mesh: Path) -> Path:
    return prepared_case_for(mesh)


def data_file_for(mesh: Path) -> Path:
    return WORK / f"{combo_label(COMBO_INDEX)}-{output_tag(mesh)}.dat.h5"


def validate_dat(path: Path, expected_iterations: int) -> dict[str, Any]:
    info: dict[str, Any] = {
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
        "hdf5_ok": False,
        "residual_iterations": 0,
        "residual_final_iter": 0,
        "udm_shape": None,
        "ok": False,
        "errors": [],
    }
    if not path.exists():
        info["errors"].append("DAT file does not exist")
        info["error"] = "; ".join(info["errors"])
        return info
    if path.stat().st_size <= 0:
        info["errors"].append("DAT file is empty")
        info["error"] = "; ".join(info["errors"])
        return info
    try:
        with h5py.File(path, "r") as h5:
            if "results/1/phase-1/cells/SV_UDM_I/1" in h5:
                info["udm_shape"] = list(h5["results/1/phase-1/cells/SV_UDM_I/1"].shape)
            residual_path = "results/residuals/phase-1/continuity/iterations"
            if residual_path in h5:
                iterations = h5[residual_path][()]
                info["residual_iterations"] = int(iterations.shape[0])
                if iterations.size:
                    info["residual_final_iter"] = int(float(iterations[-1]))
            else:
                info["errors"].append(f"Missing residual dataset: {residual_path}")
            info["hdf5_ok"] = True
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        info["errors"].append(info["error"])
        return info
    if not (
        info["residual_iterations"] >= expected_iterations
        or info["residual_final_iter"] >= expected_iterations
    ):
        info["errors"].append(
            "Residual iterations "
            f"{info['residual_iterations']} / final_iter {info['residual_final_iter']} "
            f"< expected {expected_iterations}"
        )
    info["ok"] = bool(info["hdf5_ok"] and info["size"] > 0 and not info["errors"])
    if info["errors"]:
        info["error"] = "; ".join(info["errors"])
    return info


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(state: dict[str, Any]) -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    path = RUN_ROOT / "batch_state.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def write_manifest(entries: list[dict[str, Any]]) -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = RUN_ROOT / "manifest.csv"
    fields = [
        "tag",
        "mesh_file",
        "base_case",
        "prepared_case",
        "final_case",
        "data_file",
        "status",
        "attempts",
        "data_size",
        "residual_iterations",
        "residual_final_iter",
        "udm_shape",
        "last_error",
    ]
    with manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for entry in entries:
            row = {key: entry.get(key, "") for key in fields}
            if isinstance(row.get("udm_shape"), list):
                row["udm_shape"] = "x".join(str(v) for v in row["udm_shape"])
            writer.writerow(row)


def append_log(message: str) -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    line = f"[{iso_now()}] {message}\n"
    with (RUN_ROOT / "batch.log").open("a", encoding="utf-8", buffering=1) as f:
        f.write(line)
    print(line, end="", flush=True)


def attempts_label() -> str:
    return "unlimited" if MAX_ATTEMPTS <= 0 else str(MAX_ATTEMPTS)


def initial_entries(meshes: list[Path]) -> list[dict[str, Any]]:
    entries = []
    prior = read_state(RUN_ROOT / "batch_state.json").get("entries", [])
    prior_by_tag = {item.get("tag"): item for item in prior if item.get("tag")}
    for mesh in meshes:
        tag = mesh.parent.name
        dat = data_file_for(mesh)
        validation = validate_dat(dat, ITERATIONS)
        previous = prior_by_tag.get(tag, {})
        attempts = int(previous.get("attempts", 0) or 0)
        if validation["ok"]:
            status = "complete"
        elif previous.get("status") == "failed" and MAX_ATTEMPTS > 0 and attempts >= MAX_ATTEMPTS:
            status = "failed"
        else:
            status = "pending"
        entries.append(
            {
                "tag": tag,
                "output_tag": output_tag(mesh),
                "mesh_file": str(mesh),
                "mesh_dir": str(mesh.parent),
                "base_case": str(BASE_CASE),
                "prepared_case": str(prepared_case_for(mesh)),
                "final_case": str(final_case_for(mesh)),
                "data_file": str(dat),
                "status": status,
                "attempts": attempts,
                "last_error": previous.get("last_error", "") if status == "failed" else "",
                "data_size": validation.get("size", 0),
                "residual_iterations": validation.get("residual_iterations", 0),
                "residual_final_iter": validation.get("residual_final_iter", 0),
                "udm_shape": validation.get("udm_shape"),
            }
        )
    return entries


def run_attempt(entry: dict[str, Any], attempt: int) -> int:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_attempt{attempt}"
    logs_dir = RUN_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = logs_dir / f"{entry['output_tag']}_{run_id}.stdout.log"
    stderr_log = logs_dir / f"{entry['output_tag']}_{run_id}.stderr.log"
    state_path = RUN_ROOT / "states" / f"codex_combo256_{entry['output_tag']}_state.json"
    fluent_log = RUN_ROOT / "fluent_logs" / f"codex_combo256_{entry['output_tag']}_run_{run_id}.log"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fluent_log.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "CODEX_PYFLUENT_REPO": str(REPO),
            "CODEX_COMBO256_WORK": str(WORK),
            "CODEX_COMBO256_BASE_CASE": str(BASE_CASE),
            "CODEX_COMBO256_MESH_DIR": entry["mesh_dir"],
            "CODEX_COMBO256_MESH_FILE": entry["mesh_file"],
            "CODEX_COMBO256_UDF_DIR": r"D:\Workshop\UDF\dpm-cal-udf",
            "CODEX_COMBO256_COMBO_INDEX": str(COMBO_INDEX),
            "CODEX_COMBO256_DIMENSION": "2D",
            "CODEX_COMBO256_CORES": str(CORES),
            "CODEX_COMBO256_ITERATIONS": str(ITERATIONS),
            "CODEX_COMBO256_OUTPUT_TAG": entry["output_tag"],
            "CODEX_COMBO256_RUN_ID": run_id,
            "CODEX_COMBO256_STATE": str(state_path),
            "CODEX_COMBO256_LOG": str(fluent_log),
            "CODEX_COMBO256_PREPARED_CASE": entry["prepared_case"],
            "CODEX_COMBO256_FINAL_CASE": entry["final_case"],
            "CODEX_COMBO256_DATA_FILE": entry["data_file"],
            "CODEX_COMBO256_STDOUT": str(stdout_log),
            "CODEX_COMBO256_STDERR": str(stderr_log),
        }
    )

    append_log(f"start {entry['tag']} attempt {attempt}/{attempts_label()}")
    cmd = [sys.executable, str(RUNNER)]
    with stdout_log.open("w", encoding="utf-8", buffering=1) as out, stderr_log.open("w", encoding="utf-8", buffering=1) as err:
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, stdout=out, stderr=err)
        return_code = proc.wait()
    append_log(f"finish {entry['tag']} attempt {attempt}/{attempts_label()} return_code={return_code}")
    return return_code


def update_entry_validation(entry: dict[str, Any]) -> dict[str, Any]:
    validation = validate_dat(Path(entry["data_file"]), ITERATIONS)
    entry["data_size"] = validation.get("size", 0)
    entry["residual_iterations"] = validation.get("residual_iterations", 0)
    entry["residual_final_iter"] = validation.get("residual_final_iter", 0)
    entry["udm_shape"] = validation.get("udm_shape")
    if validation.get("ok"):
        entry["status"] = "complete"
        entry["last_error"] = ""
    else:
        entry["last_error"] = validation.get("error", "dat validation failed")
    return validation


def run_batch(max_runs: int | None = None) -> int:
    if not RUNNER.exists():
        raise FileNotFoundError(f"Runner not found: {RUNNER}")
    meshes = discover_meshes()
    entries = initial_entries(meshes)
    started = 0
    state: dict[str, Any] = {
        "status": "running",
        "updated_at": iso_now(),
        "mesh_root": str(MESH_ROOT),
        "work_dir": str(WORK),
        "base_case": str(BASE_CASE),
        "mesh_include_fw": sorted(INCLUDE_FW) if INCLUDE_FW is not None else None,
        "iterations": ITERATIONS,
        "cores": CORES,
        "max_attempts": MAX_ATTEMPTS,
        "continue_on_failure": CONTINUE_ON_FAILURE,
        "total": len(entries),
        "entries": entries,
    }
    write_state(state)
    write_manifest(entries)
    append_log(f"batch start total={len(entries)} iterations={ITERATIONS} cores={CORES}")

    for entry in entries:
        if (
            CONTINUE_ON_FAILURE
            and entry.get("status") == "failed"
            and MAX_ATTEMPTS > 0
            and int(entry.get("attempts", 0) or 0) >= MAX_ATTEMPTS
        ):
            validation = validate_dat(Path(entry["data_file"]), ITERATIONS)
            if validation.get("ok"):
                entry["status"] = "complete"
                entry["last_error"] = ""
                entry["data_size"] = validation.get("size", 0)
                entry["residual_iterations"] = validation.get("residual_iterations", 0)
                entry["residual_final_iter"] = validation.get("residual_final_iter", 0)
                entry["udm_shape"] = validation.get("udm_shape")
            else:
                write_state({**state, "updated_at": iso_now(), "entries": entries})
                write_manifest(entries)
                append_log(f"skip failed {entry['tag']} attempts={entry['attempts']} error={entry.get('last_error', '')}")
                continue
        validation = update_entry_validation(entry)
        if validation.get("ok"):
            write_state({**state, "updated_at": iso_now(), "entries": entries})
            write_manifest(entries)
            append_log(f"skip complete {entry['tag']} residual_iterations={entry['residual_iterations']}")
            continue
        if max_runs is not None and started >= max_runs:
            break

        entry["status"] = "running"
        write_state({**state, "updated_at": iso_now(), "current": entry["tag"], "entries": entries})
        write_manifest(entries)

        while MAX_ATTEMPTS <= 0 or entry["attempts"] < MAX_ATTEMPTS:
            entry["attempts"] += 1
            started += 1
            return_code = run_attempt(entry, entry["attempts"])
            validation = update_entry_validation(entry)
            write_state({**state, "updated_at": iso_now(), "current": entry["tag"], "entries": entries})
            write_manifest(entries)
            if return_code == 0 and validation.get("ok"):
                append_log(f"validated {entry['tag']} residual_iterations={entry['residual_iterations']} size={entry['data_size']}")
                break
            entry["status"] = "failed"
            entry["last_error"] = f"return_code={return_code}; {entry.get('last_error', '')}"
            append_log(f"failed {entry['tag']} attempt={entry['attempts']} error={entry['last_error']}")
            if max_runs is not None and started >= max_runs:
                break

        if entry.get("status") != "complete":
            if CONTINUE_ON_FAILURE:
                append_log(f"continue after failed {entry['tag']} attempts={entry['attempts']}")
                continue
            state["status"] = "failed"
            state["failed_at"] = iso_now()
            state["current"] = entry["tag"]
            state["entries"] = entries
            write_state(state)
            write_manifest(entries)
            append_log(f"batch stopped at {entry['tag']}")
            return 1

    complete_count = sum(1 for item in entries if item.get("status") == "complete")
    failed_count = sum(1 for item in entries if item.get("status") == "failed")
    if complete_count == len(entries):
        state["status"] = "complete"
    elif CONTINUE_ON_FAILURE and failed_count:
        state["status"] = "complete_with_failures"
    else:
        state["status"] = "paused"
    state["updated_at"] = iso_now()
    state["completed"] = complete_count
    state["failed"] = failed_count
    state["entries"] = entries
    write_state(state)
    write_manifest(entries)
    append_log(f"batch {state['status']} completed={complete_count}/{len(entries)}")
    return 0 if state["status"] == "complete" else (1 if failed_count else 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run combo-256 mesh-independence Fluent jobs.")
    parser.add_argument("--dry-run", action="store_true", help="Only list discovered meshes and intended outputs.")
    parser.add_argument("--max-runs", type=int, default=None, help="Run at most this many mesh attempts before pausing.")
    args = parser.parse_args()

    meshes = discover_meshes()
    if args.dry_run:
        entries = initial_entries(meshes)
        print(
            json.dumps(
                {
                    "total": len(entries),
                    "mesh_include_fw": sorted(INCLUDE_FW) if INCLUDE_FW is not None else None,
                    "entries": entries,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    return run_batch(max_runs=args.max_runs)


if __name__ == "__main__":
    raise SystemExit(main())
