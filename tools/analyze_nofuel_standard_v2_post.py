from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from analyze_mesh_independence_results import (
    UDM,
    find_face_zone,
    finite_stats,
    percent_diff,
    read_face_field,
    read_fuelwall_cells,
    residual_summary,
    weighted_mean,
    weighted_percentile,
)

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None


PROJECT_ROOT = Path(r"F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524")
DEFAULT_CAS_DAT = PROJECT_ROOT / "cas_dat"
DEFAULT_POST = PROJECT_ROOT / "post"

KEY_UDM_METRICS = {
    "r_total_m_s": UDM["r_total"],
    "r_wax_m_s": UDM["r_wax"],
    "r_v_m_s": UDM["r_v"],
    "r_ent_m_s": UDM["r_ent"],
    "gf_total_kg_m2_s": UDM["gf_total"],
    "gf_ent_kg_m2_s": UDM["gf_ent"],
    "t_surf_K": UDM["t_surf"],
    "t_cell_K": UDM["t_cell"],
    "q_total": UDM["q_total"],
    "q_relaxed": UDM["q_relaxed"],
    "surface_diam_m": UDM["surface_diam"],
}

CONVERGENCE_METRICS = [
    ("r_total_area_mean_mm_s", "fuel-wall area mean burn rate (mm/s)", 1.0),
    ("t_surf_area_mean_K", "fuel-wall area mean Tsurf (K)", 0.5),
    ("gf_total_area_mean_kg_m2_s", "fuel-wall area mean Gf_total (kg/m2/s)", 1.0),
    ("sv_wall_t_inner_area_mean_K", "fuel-wall face SV_WALL_T_INNER (K)", 0.5),
]


def parse_fw_list(raw: str) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for part in re.split(r"[\s,;]+", raw.strip()):
        if not part:
            continue
        match = re.fullmatch(r"(?:fw)?(\d+)", part, flags=re.IGNORECASE)
        if not match:
            raise argparse.ArgumentTypeError(f"Invalid fw value: {part!r}")
        fw = int(match.group(1))
        if fw not in seen:
            seen.add(fw)
            values.append(fw)
    return values


def load_campaign_status(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        if isinstance(data.get("entries"), list):
            return list(data["entries"])
        if isinstance(data.get("cases"), list):
            return list(data["cases"])
    if isinstance(data, list):
        return data
    raise ValueError(f"Unsupported campaign status JSON shape: {path}")


def status_fw(entry: dict[str, Any]) -> int | None:
    if entry.get("fw") is not None:
        return int(entry["fw"])
    for key in ("tag", "output_tag", "mesh_file", "data_file", "case", "prepared_case"):
        value = entry.get(key)
        if value is None:
            continue
        match = re.search(r"fw(\d+)", str(value), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def fw_from_name(path: Path) -> int | None:
    match = re.search(r"fw(\d+)", path.name)
    return int(match.group(1)) if match else None


def classify_dat(dat_path: Path, fw: int) -> tuple[str, str, int]:
    text = str(dat_path).lower()
    name = dat_path.name.lower()
    if "flowsoftlr" in text or "flowsoft-lr" in text:
        return (
            f"nofuel-standard-v2-fw{fw}-flowsoftlr-8core-recovery",
            "flowsoft-lr recovery, 8 cores",
            80,
        )
    if "rerun_8core" in text or "8core" in name:
        return (
            f"nofuel-standard-v2-fw{fw}-standard-rerun-8core",
            "standard case rerun, 8 cores",
            70,
        )
    if "rerun" in text:
        return (
            f"nofuel-standard-v2-fw{fw}-standard-rerun",
            "standard case rerun, 16 cores",
            60,
        )
    return (f"nofuel-standard-v2-fw{fw}", "primary standard case, 16 cores", 10)


def discover_dat_cases(
    cas_dat: Path,
    iteration_tag: str,
    requested_fws: list[int] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates_by_fw: dict[int, list[dict[str, Any]]] = defaultdict(list)
    requested = set(requested_fws or [])
    tag_text = iteration_tag.lower()
    for dat_path in sorted(cas_dat.rglob("*.dat.h5"), key=lambda p: (fw_from_name(p) or 999999, str(p))):
        fw = fw_from_name(dat_path)
        if fw is None:
            continue
        if requested and fw not in requested:
            continue
        if tag_text not in dat_path.name.lower():
            candidates_by_fw[fw].append(
                {
                    "tag": f"nofuel-standard-v2-fw{fw}",
                    "fw": fw,
                    "setup": "non-target intermediate data",
                    "selection_priority": -999,
                    "data_file": dat_path,
                    "case_file": None,
                    "excluded_reason": f"excluded because filename does not contain {iteration_tag}",
                }
            )
            continue
        tag, setup, priority = classify_dat(dat_path, fw)
        case_matches = sorted(dat_path.parent.glob(f"*fw{fw}*.cas.h5"))
        if not case_matches:
            raise FileNotFoundError(f"No matching case found for {dat_path}")
        candidates_by_fw[fw].append(
            {
                "tag": tag,
                "fw": fw,
                "setup": setup,
                "selection_priority": priority,
                "data_file": dat_path,
                "case_file": case_matches[0],
            }
        )

    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for fw, candidates in sorted(candidates_by_fw.items()):
        ordered = sorted(
            [item for item in candidates if item.get("case_file") is not None],
            key=lambda row: (int(row["selection_priority"]), Path(row["data_file"]).stat().st_mtime),
            reverse=True,
        )
        for item in candidates:
            if item.get("case_file") is None:
                excluded.append(
                    {
                        "fw": item["fw"],
                        "tag": item["tag"],
                        "setup": item["setup"],
                        "data_file": str(item["data_file"]),
                        "reason": item.get("excluded_reason", "excluded intermediate data"),
                    }
                )
        if not ordered:
            continue
        selected.append(ordered[0])
        for item in ordered[1:]:
            excluded.append(
                {
                    "fw": item["fw"],
                    "tag": item["tag"],
                    "setup": item["setup"],
                    "data_file": str(item["data_file"]),
                    "reason": f"superseded by {ordered[0]['tag']}",
                }
            )
    return selected, excluded


def mesh_info(case_path: Path) -> dict[str, Any]:
    def attr_int(obj: h5py.Group, name: str) -> int | None:
        raw = obj.attrs.get(name)
        if raw is None:
            return None
        arr = np.asarray(raw).reshape(-1)
        return int(arr[0]) if arr.size else None

    with h5py.File(case_path, "r") as h5:
        mesh = h5["meshes/1"]
        return {
            "cell_count": attr_int(mesh, "cellCount"),
            "face_count": attr_int(mesh, "faceCount"),
            "node_count": attr_int(mesh, "nodeCount"),
        }


def read_residual_series(dat_path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    with h5py.File(dat_path, "r") as h5:
        base = "results/residuals/phase-1"
        if base not in h5:
            return series
        group = h5[base]
        for name in group.keys():
            obj = group[name]
            if not isinstance(obj, h5py.Group) or "data" not in obj or "iterations" not in obj:
                continue
            data = obj["data"][()]
            iterations = obj["iterations"][()]
            residual = np.asarray(data[:, 0] if data.ndim > 1 else data, dtype=float)
            series[name] = (np.asarray(iterations, dtype=float), residual)
    return series


def analyze_record(
    record: dict[str, Any],
    expected_iterations: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    dat_path = Path(record["data_file"])
    case_path = Path(record["case_file"])
    fw = int(record["fw"])
    wall_cells = read_fuelwall_cells(dat_path)
    area = np.asarray(wall_cells[:, UDM["face_area"]], dtype=float)
    valid_area = np.isfinite(area) & (area > 0.0)
    weights = area if np.any(valid_area) else None
    active = np.isfinite(wall_cells[:, UDM["r_total"]]) & (wall_cells[:, UDM["r_total"]] > 1e-12)
    residuals = residual_summary(dat_path)
    zone = find_face_zone(case_path, "fuel-wall")

    metric: dict[str, Any] = {
        "tag": record["tag"],
        "fw": fw,
        "setup": record["setup"],
        "data_file": str(dat_path),
        "case_file": str(case_path),
        "data_size_bytes": dat_path.stat().st_size,
        "fuelwall_face_zone_id": zone["id"],
        "fuelwall_face_zone_count": zone["count"],
        "fuelwall_cell_udm_count": int(wall_cells.shape[0]),
        "area_valid_count": int(np.count_nonzero(valid_area)),
        "area_sum_m2": float(np.sum(area[valid_area])) if np.any(valid_area) else None,
        "active_count": int(np.count_nonzero(active)),
        "active_fraction": float(np.count_nonzero(active) / wall_cells.shape[0]),
    }
    metric.update(mesh_info(case_path))

    for metric_name, udm_index in KEY_UDM_METRICS.items():
        values = np.asarray(wall_cells[:, udm_index], dtype=float)
        stats = finite_stats(values)
        metric[f"{metric_name}_mean"] = stats["mean"]
        metric[f"{metric_name}_min"] = stats["min"]
        metric[f"{metric_name}_max"] = stats["max"]
        metric[f"{metric_name}_p05"] = stats["p05"]
        metric[f"{metric_name}_p50"] = stats["p50"]
        metric[f"{metric_name}_p95"] = stats["p95"]
        metric[f"{metric_name}_area_mean"] = weighted_mean(values, weights)
        metric[f"{metric_name}_area_p05"] = weighted_percentile(values, weights, 5.0)
        metric[f"{metric_name}_area_p50"] = weighted_percentile(values, weights, 50.0)
        metric[f"{metric_name}_area_p95"] = weighted_percentile(values, weights, 95.0)

    metric["r_total_area_mean_mm_s"] = metric["r_total_m_s_area_mean"] * 1000.0
    metric["r_total_area_mean_mm_min"] = metric["r_total_m_s_area_mean"] * 60000.0
    metric["r_wax_area_mean_mm_s"] = metric["r_wax_m_s_area_mean"] * 1000.0
    metric["r_v_area_mean_mm_s"] = metric["r_v_m_s_area_mean"] * 1000.0
    metric["r_ent_area_mean_mm_s"] = metric["r_ent_m_s_area_mean"] * 1000.0
    metric["gf_total_area_mean_kg_m2_s"] = metric["gf_total_kg_m2_s_area_mean"]
    metric["gf_ent_area_mean_kg_m2_s"] = metric["gf_ent_kg_m2_s_area_mean"]
    metric["t_surf_area_mean_K"] = metric["t_surf_K_area_mean"]
    metric["t_cell_area_mean_K"] = metric["t_cell_K_area_mean"]
    metric["surface_diam_area_mean_um"] = none_mul(metric["surface_diam_m_area_mean"], 1e6)
    metric["mdot_ent_dpm_sum_kg_s"] = float(np.nansum(wall_cells[:, UDM["mdot_ent_dpm"]]))
    metric["mdot_ent_dpm_abs_sum_kg_s"] = float(np.nansum(np.abs(wall_cells[:, UDM["mdot_ent_dpm"]])))

    face_values = read_face_field(dat_path, "SV_WALL_T_INNER", zone["min_id"], zone["max_id"])
    if face_values is not None:
        face_arr = np.asarray(face_values, dtype=float).reshape(-1)
        face_stats = finite_stats(face_arr)
        metric["sv_wall_t_inner_mean_K"] = face_stats["mean"]
        metric["sv_wall_t_inner_min_K"] = face_stats["min"]
        metric["sv_wall_t_inner_max_K"] = face_stats["max"]
        metric["sv_wall_t_inner_p50_K"] = face_stats["p50"]
        metric["sv_wall_t_inner_area_mean_K"] = (
            weighted_mean(face_arr, area) if face_arr.shape[0] == area.shape[0] else face_stats["mean"]
        )

    for residual_name, summary in residuals.items():
        safe = residual_name.replace("-", "_").replace(" ", "_")
        metric[f"res_{safe}_n"] = summary["n"]
        metric[f"res_{safe}_final_iter"] = summary["final_iter"]
        metric[f"res_{safe}_initial"] = summary["initial"]
        metric[f"res_{safe}_final"] = summary["final"]
        metric[f"res_{safe}_min"] = summary["min"]

    status, notes = physical_validation(metric, expected_iterations)
    metric["analysis_status"] = status
    metric["analysis_notes"] = "; ".join(notes)

    profiles = build_profiles(metric, wall_cells, area)
    detail = {
        "tag": record["tag"],
        "fuelwall_zone": zone,
        "residuals": residuals,
        "case_file": str(case_path),
        "data_file": str(dat_path),
    }
    return metric, detail, profiles


def physical_validation(metric: dict[str, Any], expected_iterations: int) -> tuple[str, list[str]]:
    notes: list[str] = []
    iterations = metric.get("res_continuity_final_iter") or metric.get("res_continuity_n") or 0
    continuity = safe_float(metric.get("res_continuity_final"))
    burn = safe_float(metric.get("r_total_area_mean_mm_s"))
    t_surf = safe_float(metric.get("t_surf_area_mean_K"))
    wall_t = safe_float(metric.get("sv_wall_t_inner_area_mean_K"))

    if not isinstance(iterations, (float, int)) or int(iterations) < expected_iterations:
        notes.append(f"continuity residual final iteration is {iterations}; expected at least {expected_iterations}")
    if continuity is None or continuity > 1e-2:
        notes.append(f"continuity final residual is {fmt(continuity, 4)}")
    if burn is None or burn < 0.5:
        notes.append(f"fuel-wall area mean burn rate is {fmt(burn, 6)} mm/s")
    if t_surf is None or t_surf < 700.0:
        notes.append(f"fuel-wall area mean Tsurf is {fmt(t_surf, 3)} K")
    if wall_t is None or wall_t < 700.0:
        notes.append(f"fuel-wall SV_WALL_T_INNER is {fmt(wall_t, 3)} K")
    return ("accepted" if not notes else "failed_physical_validation", notes)


def build_profiles(metric: dict[str, Any], wall_cells: np.ndarray, area: np.ndarray, bins: int = 200) -> list[dict[str, Any]]:
    x = np.asarray(wall_cells[:, UDM["face_x"]], dtype=float)
    valid = np.isfinite(x)
    if not np.any(valid):
        return []
    xmin = float(np.nanmin(x[valid]))
    xmax = float(np.nanmax(x[valid]))
    if not math.isfinite(xmin) or not math.isfinite(xmax) or xmax <= xmin:
        return []
    edges = np.linspace(xmin, xmax, bins + 1)
    assignments = np.clip(np.digitize(x, edges, right=False) - 1, 0, bins - 1)
    rows: list[dict[str, Any]] = []
    for i in range(bins):
        mask = valid & (assignments == i)
        if not np.any(mask):
            continue
        weights = area[mask]
        if not np.any(np.isfinite(weights) & (weights > 0.0)):
            weights = None
        x_mid = float((edges[i] + edges[i + 1]) / 2.0)
        rows.append(
            {
                "tag": metric["tag"],
                "fw": metric["fw"],
                "setup": metric["setup"],
                "x_mid_m": x_mid,
                "x_norm": float((x_mid - xmin) / (xmax - xmin)),
                "count": int(np.count_nonzero(mask)),
                "area_sum_m2": float(np.nansum(area[mask])),
                "r_total_mm_s_area_mean": none_mul(weighted_mean(wall_cells[mask, UDM["r_total"]], weights), 1000.0),
                "t_surf_K_area_mean": weighted_mean(wall_cells[mask, UDM["t_surf"]], weights),
                "gf_total_kg_m2_s_area_mean": weighted_mean(wall_cells[mask, UDM["gf_total"]], weights),
            }
        )
    return rows


def none_mul(value: float | None, scale: float) -> float | None:
    return None if value is None else float(value) * scale


def build_convergence(metrics: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    sorted_metrics = sorted(metrics, key=lambda m: int(m["fw"]))
    accepted_metrics = [m for m in sorted_metrics if m.get("analysis_status") == "accepted"]
    reference_pool = accepted_metrics or sorted_metrics
    reference = max(reference_pool, key=lambda m: int(m["fw"]))
    for item in sorted_metrics:
        row: dict[str, Any] = {
            "tag": item["tag"],
            "fw": item["fw"],
            "setup": item["setup"],
            "analysis_status": item.get("analysis_status"),
            "analysis_notes": item.get("analysis_notes"),
            "reference_tag": reference["tag"],
            "reference_fw": reference["fw"],
            "reference_setup": reference["setup"],
            "is_reference": item["tag"] == reference["tag"],
        }
        for key, label, _threshold in CONVERGENCE_METRICS:
            row[label] = item.get(key)
            row[f"{label} diff to fw{reference['fw']} (%)"] = percent_diff(item.get(key), reference.get(key))
        rows.append(row)

    adjacent_rows: list[dict[str, Any]] = []
    for prev, cur in zip(sorted_metrics, sorted_metrics[1:]):
        row = {
            "from_tag": prev["tag"],
            "to_tag": cur["tag"],
            "from_fw": prev["fw"],
            "to_fw": cur["fw"],
            "from_setup": prev["setup"],
            "to_setup": cur["setup"],
            "from_status": prev.get("analysis_status"),
            "to_status": cur.get("analysis_status"),
            "mixed_setup": prev["setup"] != cur["setup"],
        }
        for key, label, _threshold in CONVERGENCE_METRICS:
            row[f"{label} adjacent change (%)"] = percent_diff(cur.get(key), prev.get(key))
        adjacent_rows.append(row)
    return rows, adjacent_rows


def csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_float(value: Any) -> float | None:
    if isinstance(value, (float, int)) and math.isfinite(float(value)):
        return float(value)
    return None


def fmt(value: Any, digits: int = 4) -> str:
    value = safe_float(value)
    if value is None:
        return "-"
    if abs(value) >= 1e4 or (0.0 < abs(value) < 1e-3):
        return f"{value:.{digits}e}"
    return f"{value:.{digits}f}"


def reference_fw_from_convergence(convergence: list[dict[str, Any]]) -> int:
    for row in convergence:
        if row.get("is_reference") and row.get("reference_fw") is not None:
            return int(row["reference_fw"])
    refs = [int(row["reference_fw"]) for row in convergence if row.get("reference_fw") is not None]
    return max(refs) if refs else 0


def make_plots(
    metrics: list[dict[str, Any]],
    convergence: list[dict[str, Any]],
    adjacent: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    outdir: Path,
) -> list[Path]:
    if plt is None:
        return []
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    figures = outdir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    rows = sorted(metrics, key=lambda m: int(m["fw"]))
    fws = [int(m["fw"]) for m in rows]

    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0), constrained_layout=True)
    panels = [
        ("r_total_area_mean_mm_s", "Area mean burn rate (mm/s)", axes[0, 0]),
        ("t_surf_area_mean_K", "Area mean Tsurf (K)", axes[0, 1]),
        ("gf_total_area_mean_kg_m2_s", "Area mean Gf_total (kg/m2/s)", axes[1, 0]),
        ("sv_wall_t_inner_area_mean_K", "SV_WALL_T_INNER (K)", axes[1, 1]),
    ]
    for key, ylabel, ax in panels:
        y = [m.get(key) for m in rows]
        ax.plot(fws, y, marker="o", linewidth=1.6)
        for m, yy in zip(rows, y):
            if "recovery" in str(m["setup"]):
                ax.scatter([m["fw"]], [yy], s=85, facecolors="none", edgecolors="#d62728", linewidths=1.6, zorder=4)
            if m.get("analysis_status") != "accepted":
                ax.scatter([m["fw"]], [yy], s=90, marker="x", color="#111111", linewidths=1.8, zorder=5)
        ax.set_xlabel("fw tag")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
    fig.suptitle("Nofuel standard-v2 mesh sensitivity metrics")
    path = figures / "mesh_metrics_vs_fw.png"
    fig.savefig(path, dpi=190)
    plt.close(fig)
    outputs.append(path)

    valid_primary = [m for m in rows if m.get("analysis_status") == "accepted" and "primary standard" in str(m["setup"])]
    if len(valid_primary) >= 2:
        ref = max(valid_primary, key=lambda m: int(m["fw"]))
        fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0), constrained_layout=True)
        strict_panels = [
            ("r_total_area_mean_mm_s", "Area mean burn rate (mm/s)", axes[0, 0]),
            ("t_surf_area_mean_K", "Area mean Tsurf (K)", axes[0, 1]),
            ("gf_total_area_mean_kg_m2_s", "Area mean Gf_total (kg/m2/s)", axes[1, 0]),
            ("sv_wall_t_inner_area_mean_K", "SV_WALL_T_INNER (K)", axes[1, 1]),
        ]
        for key, ylabel, ax in strict_panels:
            x_vals = [int(m["fw"]) for m in valid_primary]
            y_vals = [m.get(key) for m in valid_primary]
            ax.plot(x_vals, y_vals, marker="o", linewidth=1.6)
            ax.set_xlabel("fw tag")
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.25)
        fig.suptitle(f"Strict primary-sequence metrics, accepted cases only; reference fw{ref['fw']}")
        path = figures / "strict_primary_metrics_accepted_only.png"
        fig.savefig(path, dpi=190)
        plt.close(fig)
        outputs.append(path)

    fig, ax = plt.subplots(figsize=(9.5, 5.2), constrained_layout=True)
    x = np.arange(len(fws), dtype=float)
    width = 0.22
    reference_fw = reference_fw_from_convergence(convergence)
    diff_fields = [
        (f"fuel-wall area mean burn rate (mm/s) diff to fw{reference_fw} (%)", "burn", -width),
        (f"fuel-wall area mean Tsurf (K) diff to fw{reference_fw} (%)", "Tsurf", 0.0),
        (f"fuel-wall area mean Gf_total (kg/m2/s) diff to fw{reference_fw} (%)", "Gf", width),
    ]
    for field, label, offset in diff_fields:
        ax.bar(x + offset, [abs(r[field]) if safe_float(r.get(field)) is not None else np.nan for r in convergence], width, label=label)
    ax.axhline(1.0, color="#666666", linestyle="--", linewidth=0.9, alpha=0.7, label="1%")
    ax.set_xticks(x)
    ax.set_xticklabels([str(fw) for fw in fws])
    ax.set_xlabel("fw tag")
    ax.set_ylabel(f"Absolute relative difference to fw{reference_fw} (%)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    ax.set_title("Grid-independence relative difference to finest case")
    path = figures / f"relative_difference_to_fw{reference_fw}.png"
    fig.savefig(path, dpi=190)
    plt.close(fig)
    outputs.append(path)

    fig, ax = plt.subplots(figsize=(9.5, 5.2), constrained_layout=True)
    pairs = [f"{r['from_fw']}-{r['to_fw']}" for r in adjacent]
    x = np.arange(len(pairs), dtype=float)
    for field, label, offset in [
        ("fuel-wall area mean burn rate (mm/s) adjacent change (%)", "burn", -width),
        ("fuel-wall area mean Tsurf (K) adjacent change (%)", "Tsurf", 0.0),
        ("fuel-wall area mean Gf_total (kg/m2/s) adjacent change (%)", "Gf", width),
    ]:
        ax.bar(x + offset, [abs(r[field]) if safe_float(r.get(field)) is not None else np.nan for r in adjacent], width, label=label)
    for idx, row in enumerate(adjacent):
        if row.get("mixed_setup"):
            ax.axvspan(idx - 0.5, idx + 0.5, color="#d62728", alpha=0.08)
    ax.axhline(1.0, color="#666666", linestyle="--", linewidth=0.9, alpha=0.7, label="1%")
    ax.set_xticks(x)
    ax.set_xticklabels(pairs)
    ax.set_xlabel("adjacent fw pair")
    ax.set_ylabel("Absolute adjacent change (%)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    ax.set_title("Adjacent mesh sensitivity; red band marks mixed setup")
    path = figures / "adjacent_mesh_change.png"
    fig.savefig(path, dpi=190)
    plt.close(fig)
    outputs.append(path)

    profile_by_fw: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in profiles:
        profile_by_fw[int(row["fw"])].append(row)
    for metric_key, ylabel, filename in [
        ("r_total_mm_s_area_mean", "Burn rate (mm/s)", "fuelwall_profile_burn_rate.png"),
        ("t_surf_K_area_mean", "Tsurf (K)", "fuelwall_profile_tsurf.png"),
        ("gf_total_kg_m2_s_area_mean", "Gf_total (kg/m2/s)", "fuelwall_profile_gf_total.png"),
    ]:
        fig, ax = plt.subplots(figsize=(10.5, 5.8), constrained_layout=True)
        for fw in fws:
            group = sorted(profile_by_fw.get(fw, []), key=lambda r: float(r["x_norm"]))
            if not group:
                continue
            label = f"fw{fw}"
            if any("recovery" in str(r["setup"]) for r in group):
                label += " recovery"
            ax.plot([r["x_norm"] for r in group], [r[metric_key] for r in group], linewidth=1.25, label=label)
        ax.set_xlabel("Normalized fuel-wall x")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2, fontsize=8)
        ax.set_title(f"Fuel-wall binned profile: {ylabel}")
        path = figures / filename
        fig.savefig(path, dpi=190)
        plt.close(fig)
        outputs.append(path)

    fig, ax = plt.subplots(figsize=(10.0, 5.6), constrained_layout=True)
    for metric in rows:
        series = read_residual_series(Path(metric["data_file"]))
        if "continuity" not in series:
            continue
        iters, values = series["continuity"]
        label = f"fw{metric['fw']}"
        if "recovery" in str(metric["setup"]):
            label += " recovery"
        ax.semilogy(iters, np.where(values > 0.0, values, np.nan), linewidth=1.15, label=label)
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Continuity residual")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    ax.set_title("Continuity residual histories")
    path = figures / "continuity_residual_histories.png"
    fig.savefig(path, dpi=190)
    plt.close(fig)
    outputs.append(path)

    return outputs


def write_report(
    outdir: Path,
    metrics: list[dict[str, Any]],
    convergence: list[dict[str, Any]],
    adjacent: list[dict[str, Any]],
    plot_paths: list[Path],
    excluded_records: list[dict[str, Any]],
) -> None:
    rows = sorted(metrics, key=lambda m: int(m["fw"]))
    ref = rows[-1]
    failed = [m for m in rows if m.get("analysis_status") != "accepted"]
    comparable_rows = [
        m for m in rows if "primary standard" in str(m["setup"]) and m.get("analysis_status") == "accepted"
    ]
    comparable_ref = max(comparable_rows, key=lambda m: int(m["fw"])) if comparable_rows else ref
    prev_primary = sorted(comparable_rows, key=lambda m: int(m["fw"]))[-2] if len(comparable_rows) >= 2 else None

    final_checks: list[dict[str, Any]] = []
    if prev_primary is not None:
        for key, label, threshold in CONVERGENCE_METRICS:
            diff = percent_diff(prev_primary.get(key), comparable_ref.get(key))
            final_checks.append(
                {
                    "metric": label,
                    "diff_pct": diff,
                    "threshold_pct": threshold,
                    "pass": safe_float(diff) is not None and abs(float(diff)) <= threshold,
                }
            )
    passed = bool(final_checks) and all(item["pass"] for item in final_checks)

    lines: list[str] = [
        "# nofuel standard-v2 后处理与网格无关性验证",
        "",
        "## 数据范围",
        "",
        f"- 后处理目录：`{outdir}`",
        f"- DAT 来源：`{DEFAULT_CAS_DAT}`",
        f"- 共解析 `{len(rows)}` 个当前选用 `.dat.h5`，每个文件均来自 700 步计算结果。",
        "- 同一个 `fw` 如果存在重算 DAT，则优先选用重算结果，旧异常 DAT 保留但不进入当前网格无关性统计。",
        "- 指标主要来自 fuel-wall UDM：`udm_FuelWallFlag > 0.5` 的单元，并用 `udm_FaceArea` 做面积加权。",
        "- 空间云图、直方图、残差图等逐 DAT 图件位于 `dat_plots/`；汇总网格无关性图件位于 `figures/`。",
        "",
        "## 重要说明",
        "",
        "- `fw1250` 是 8 核标准 case 重算结果；原始 `fw1250` 物理异常，已被该重算 DAT 替代。",
        "- `fw1500` 是 8 核 `flowsoft-lr` 补算结果；其基准 case 和核数与主批处理结果不同。",
        "- 因此 `fw1250` 和 `fw1500` 可以用于补齐结果覆盖和趋势观察，但不作为严格同条件网格无关性判据。",
        f"- 物理校验通过 `{len(rows) - len(failed)}/{len(rows)}` 个 DAT；物理校验失败的 DAT 不进入严格网格无关性判据。",
        f"- 严格同条件判据采用主批处理序列中最细的 `fw{comparable_ref['fw']}` 作为参考，并重点比较相邻较细网格 `fw{prev_primary['fw'] if prev_primary else '-'}`。",
        "",
        "## 判定结论",
        "",
    ]
    if passed:
        lines.append(f"- 当前主批处理序列在 `fw{prev_primary['fw']}` 到 `fw{comparable_ref['fw']}` 的关键面积加权指标变化均低于设定阈值，可作为网格无关性通过的当前证据。")
    else:
        lines.append(f"- 当前主批处理序列在 `fw{prev_primary['fw'] if prev_primary else '-'}` 到 `fw{comparable_ref['fw']}` 的关键面积加权指标仍有超过阈值的变化，严格意义上不建议直接判定完全网格无关。")
    lines.append("- 若后续论文/报告需要更严格结论，建议将 6 个网格统一用相同 `flowsoft-lr` case 和相同核数重跑，以消除 `fw1500` 补算条件差异。")
    lines.append("")
    if failed:
        lines.append("### 物理校验失败样本")
        lines.append("")
        lines.append("| fw | 来源 | burn mm/s | Tsurf K | continuity final | 原因 |")
        lines.append("|---:|---|---:|---:|---:|---|")
        for m in failed:
            lines.append(
                f"| {m['fw']} | {m['setup']} | {fmt(m.get('r_total_area_mean_mm_s'), 6)} | "
                f"{fmt(m.get('t_surf_area_mean_K'), 3)} | {fmt(m.get('res_continuity_final'), 3)} | "
                f"{m.get('analysis_notes') or ''} |"
            )
        lines.append("")
    if excluded_records:
        lines.append("### 未纳入当前统计的旧 DAT")
        lines.append("")
        lines.append("| fw | tag | 来源 | 原因 |")
        lines.append("|---:|---|---|---|")
        for item in excluded_records:
            lines.append(f"| {item['fw']} | {item['tag']} | {item['setup']} | {item['reason']} |")
        lines.append("")
    lines.append("### 最细主批处理相邻网格检查")
    lines.append("")
    lines.append("| 指标 | 比较 | 相对差异 % | 阈值 % | 结论 |")
    lines.append("|---|---|---:|---:|---|")
    for item in final_checks:
        verdict = "通过" if item["pass"] else "未通过"
        lines.append(
            f"| {item['metric']} | fw{prev_primary['fw']} vs fw{comparable_ref['fw']} | "
            f"{fmt(item['diff_pct'], 4)} | {fmt(item['threshold_pct'], 3)} | {verdict} |"
        )
    lines.append("")

    lines.append("## 汇总指标")
    lines.append("")
    lines.append("| fw | 状态 | 来源 | cells | fuel-wall cells | area m2 | burn mm/s | Tsurf K | Gf kg/m2/s | wall T K | cont. final |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(m["fw"]),
                    str(m.get("analysis_status")),
                    str(m["setup"]),
                    str(m["cell_count"]),
                    str(m["fuelwall_cell_udm_count"]),
                    fmt(m.get("area_sum_m2"), 6),
                    fmt(m.get("r_total_area_mean_mm_s"), 6),
                    fmt(m.get("t_surf_area_mean_K"), 3),
                    fmt(m.get("gf_total_area_mean_kg_m2_s"), 6),
                    fmt(m.get("sv_wall_t_inner_area_mean_K"), 3),
                    fmt(m.get("res_continuity_final"), 3),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(f"## 相对最细网格 `fw{ref['fw']}` 的差异")
    lines.append("")
    lines.append("| fw | burn diff % | Tsurf diff % | Gf diff % | wall T diff % |")
    lines.append("|---:|---:|---:|---:|---:|")
    for row in convergence:
        fields = [
            "fuel-wall area mean burn rate (mm/s) diff to fw2000 (%)",
            "fuel-wall area mean Tsurf (K) diff to fw2000 (%)",
            "fuel-wall area mean Gf_total (kg/m2/s) diff to fw2000 (%)",
            "fuel-wall face SV_WALL_T_INNER (K) diff to fw2000 (%)",
        ]
        lines.append(
            f"| {row['fw']} | {fmt(row.get(fields[0]), 4)} | {fmt(row.get(fields[1]), 4)} | "
            f"{fmt(row.get(fields[2]), 4)} | {fmt(row.get(fields[3]), 4)} |"
        )
    lines.append("")
    lines.append("## 相邻网格变化")
    lines.append("")
    lines.append("| pair | status | mixed setup | burn change % | Tsurf change % | Gf change % | wall T change % |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for row in adjacent:
        fields = [
            "fuel-wall area mean burn rate (mm/s) adjacent change (%)",
            "fuel-wall area mean Tsurf (K) adjacent change (%)",
            "fuel-wall area mean Gf_total (kg/m2/s) adjacent change (%)",
            "fuel-wall face SV_WALL_T_INNER (K) adjacent change (%)",
        ]
        lines.append(
            f"| fw{row['from_fw']} -> fw{row['to_fw']} | {row['from_status']} -> {row['to_status']} | {row['mixed_setup']} | "
            f"{fmt(row.get(fields[0]), 4)} | {fmt(row.get(fields[1]), 4)} | "
            f"{fmt(row.get(fields[2]), 4)} | {fmt(row.get(fields[3]), 4)} |"
        )
    lines.append("")
    lines.append("## 图件")
    lines.append("")
    for plot in plot_paths:
        rel = plot.relative_to(outdir)
        lines.append(f"- [{rel.as_posix()}]({rel.as_posix()})")
    lines.append("")
    lines.append("## 输出文件")
    lines.append("")
    lines.append("- `mesh_independence_metrics.csv`：每个 DAT 的 fuel-wall 面积加权指标。")
    lines.append("- `mesh_independence_convergence.csv`：相对 `fw2000` 的偏差。")
    lines.append("- `mesh_independence_adjacent.csv`：相邻网格之间的变化。")
    lines.append("- `fuelwall_profiles_binned.csv`：沿 fuel-wall 归一化轴向位置的分箱剖面。")
    lines.append("- `residual_summary.csv`：残差最终值和迭代步数。")
    lines.append("- `post_summary.json`：后处理元数据和判定结果。")
    (outdir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "passed_strict_primary_sequence": passed,
        "reference": {"tag": ref["tag"], "fw": ref["fw"], "setup": ref["setup"]},
        "strict_reference": {
            "tag": comparable_ref["tag"],
            "fw": comparable_ref["fw"],
            "setup": comparable_ref["setup"],
        },
        "strict_previous": None if prev_primary is None else {"tag": prev_primary["tag"], "fw": prev_primary["fw"]},
        "strict_checks": final_checks,
        "failed_physical_validation": [
            {"tag": m["tag"], "fw": m["fw"], "notes": m.get("analysis_notes")} for m in failed
        ],
        "excluded_records": excluded_records,
        "warnings": [
            "fw1250 is a standard-case 8-core rerun and fw1500 is a flowsoft-lr 8-core recovery; they are not strict same-setup points in the mesh-independence sequence."
        ],
        "plots": [str(path) for path in plot_paths],
    }
    (outdir / "post_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report_v2(
    outdir: Path,
    cas_dat: Path,
    metrics: list[dict[str, Any]],
    convergence: list[dict[str, Any]],
    adjacent: list[dict[str, Any]],
    plot_paths: list[Path],
    excluded_records: list[dict[str, Any]],
    iteration_tag: str,
    expected_iterations: int,
    requested_fws: list[int],
    campaign_status: list[dict[str, Any]],
) -> None:
    rows = sorted(metrics, key=lambda m: int(m["fw"]))
    requested_fws = requested_fws or [int(m["fw"]) for m in rows]
    selected_fws = sorted({int(m["fw"]) for m in rows})
    accepted_fws = sorted({int(m["fw"]) for m in rows if m.get("analysis_status") == "accepted"})
    missing_target_fws = sorted(set(requested_fws) - set(selected_fws))
    status_by_fw = {fw: entry for entry in campaign_status if (fw := status_fw(entry)) is not None}
    campaign_status_notes = []
    for fw in sorted(set(requested_fws) | set(status_by_fw)):
        entry = status_by_fw.get(fw)
        if entry is None:
            if fw in missing_target_fws:
                campaign_status_notes.append({"fw": fw, "status": "missing", "note": "no selected DAT found"})
            continue
        status = str(entry.get("status", "")).strip()
        note = str(entry.get("note") or entry.get("last_error") or entry.get("message") or "")
        attempts = entry.get("attempts")
        if status and status.lower() not in {"complete", "accepted", "success"}:
            campaign_status_notes.append({"fw": fw, "status": status, "attempts": attempts, "note": note})
    failed_status_fws = {int(item["fw"]) for item in campaign_status_notes}
    ref_pool = [m for m in rows if m.get("analysis_status") == "accepted"]
    ref = max(ref_pool, key=lambda m: int(m["fw"])) if ref_pool else rows[-1]
    failed = [m for m in rows if m.get("analysis_status") != "accepted"]
    comparable_rows = [
        m for m in rows if "primary standard" in str(m["setup"]) and m.get("analysis_status") == "accepted"
    ]
    comparable_ref = max(comparable_rows, key=lambda m: int(m["fw"])) if comparable_rows else ref
    prev_primary = sorted(comparable_rows, key=lambda m: int(m["fw"]))[-2] if len(comparable_rows) >= 2 else None

    final_checks: list[dict[str, Any]] = []
    if prev_primary is not None:
        for key, label, threshold in CONVERGENCE_METRICS:
            diff = percent_diff(prev_primary.get(key), comparable_ref.get(key))
            final_checks.append(
                {
                    "metric": label,
                    "comparison": f"fw{prev_primary['fw']} vs fw{comparable_ref['fw']}",
                    "diff_pct": diff,
                    "threshold_pct": threshold,
                    "pass": safe_float(diff) is not None and abs(float(diff)) <= threshold,
                }
            )
    passed = bool(final_checks) and all(item["pass"] for item in final_checks)
    campaign_complete = (
        bool(requested_fws)
        and set(requested_fws).issubset(set(selected_fws))
        and not failed
        and not missing_target_fws
        and not failed_status_fws
    )

    ref_fw = int(ref["fw"])
    diff_fields = [
        f"{label} diff to fw{ref_fw} (%)" for _key, label, _threshold in CONVERGENCE_METRICS
    ]

    lines: list[str] = [
        "# nofuel standard-v2 four-grid 16-core post-processing and mesh independence",
        "",
        "## Data range",
        "",
        f"- Post directory: `{outdir}`",
        f"- DAT source: `{cas_dat}`",
        f"- Selected DAT files: `{len(rows)}`; all selected records match `{iteration_tag}` and are checked against `{expected_iterations}` residual iterations.",
        f"- Requested target grids: `{', '.join(f'fw{fw}' for fw in requested_fws)}`.",
        "- Metrics are computed from fuel-wall UDM rows where `udm_FuelWallFlag > 0.5`, area-weighted by `udm_FaceArea`.",
        "- Per-DAT HDF5 figures live under `dat_plots/`; aggregate mesh-independence figures live under `figures/`.",
        "",
        "## Verdict",
        "",
        f"- Physical validation accepted `{len(rows) - len(failed)}/{len(rows)}` selected DAT files.",
        f"- Finest accepted grid for this run: `fw{ref_fw}`.",
    ]
    if campaign_complete:
        lines.append("- Campaign completion: all requested grids produced accepted DAT files.")
    else:
        lines.append("- Campaign completion: incomplete or caveated; see the campaign completion caveat below.")
    if prev_primary is None:
        lines.append("- Strict same-setup adjacent-grid verdict is unavailable because fewer than two accepted 16-core primary cases were available.")
    elif passed:
        lines.append(
            f"- The strict same-setup adjacent comparison `fw{prev_primary['fw']} -> fw{comparable_ref['fw']}` is within all configured thresholds."
        )
    else:
        lines.append(
            f"- The strict same-setup adjacent comparison `fw{prev_primary['fw']} -> fw{comparable_ref['fw']}` exceeds at least one configured threshold; do not claim full grid independence yet."
        )
    lines.append("")

    if not campaign_complete:
        lines.extend(
            [
                "## Campaign Completion Caveat",
                "",
                f"- Completed selected grids: `{', '.join(f'fw{fw}' for fw in selected_fws) or 'none'}`.",
                f"- Accepted grids: `{', '.join(f'fw{fw}' for fw in accepted_fws) or 'none'}`.",
                f"- Missing target grids: `{', '.join(f'fw{fw}' for fw in missing_target_fws) or 'none'}`.",
            ]
        )
        if campaign_status_notes:
            lines.extend(["", "| fw | status | attempts | note |", "|---:|---|---:|---|"])
            for item in campaign_status_notes:
                lines.append(
                    f"| {item['fw']} | {item.get('status', '')} | {item.get('attempts') or ''} | {item.get('note') or ''} |"
                )
        lines.append("")

    if failed:
        lines.extend(
            [
                "## Physical Validation Failures",
                "",
                "| fw | setup | burn mm/s | Tsurf K | continuity final | reason |",
                "|---:|---|---:|---:|---:|---|",
            ]
        )
        for m in failed:
            lines.append(
                f"| {m['fw']} | {m['setup']} | {fmt(m.get('r_total_area_mean_mm_s'), 6)} | "
                f"{fmt(m.get('t_surf_area_mean_K'), 3)} | {fmt(m.get('res_continuity_final'), 3)} | "
                f"{m.get('analysis_notes') or ''} |"
            )
        lines.append("")

    if excluded_records:
        lines.extend(
            [
                "## Excluded DAT Files",
                "",
                "| fw | tag | setup | reason |",
                "|---:|---|---|---|",
            ]
        )
        for item in excluded_records:
            lines.append(f"| {item['fw']} | {item['tag']} | {item['setup']} | {item['reason']} |")
        lines.append("")

    lines.extend(
        [
            "## Finest Adjacent Check",
            "",
            "| metric | comparison | relative diff % | threshold % | verdict |",
            "|---|---|---:|---:|---|",
        ]
    )
    if final_checks:
        for item in final_checks:
            verdict = "pass" if item["pass"] else "fail"
            lines.append(
                f"| {item['metric']} | {item['comparison']} | {fmt(item['diff_pct'], 4)} | "
                f"{fmt(item['threshold_pct'], 3)} | {verdict} |"
            )
    else:
        lines.append("| - | - | - | - | unavailable |")
    lines.append("")

    lines.extend(
        [
            "## Summary Metrics",
            "",
            "| fw | status | setup | cells | fuel-wall cells | area m2 | burn mm/s | Tsurf K | Gf kg/m2/s | wall T K | cont. final |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for m in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(m["fw"]),
                    str(m.get("analysis_status")),
                    str(m["setup"]),
                    str(m["cell_count"]),
                    str(m["fuelwall_cell_udm_count"]),
                    fmt(m.get("area_sum_m2"), 6),
                    fmt(m.get("r_total_area_mean_mm_s"), 6),
                    fmt(m.get("t_surf_area_mean_K"), 3),
                    fmt(m.get("gf_total_area_mean_kg_m2_s"), 6),
                    fmt(m.get("sv_wall_t_inner_area_mean_K"), 3),
                    fmt(m.get("res_continuity_final"), 3),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.extend(
        [
            f"## Relative Difference To `fw{ref_fw}`",
            "",
            "| fw | burn diff % | Tsurf diff % | Gf diff % | wall T diff % |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in convergence:
        lines.append(
            f"| {row['fw']} | {fmt(row.get(diff_fields[0]), 4)} | {fmt(row.get(diff_fields[1]), 4)} | "
            f"{fmt(row.get(diff_fields[2]), 4)} | {fmt(row.get(diff_fields[3]), 4)} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Adjacent Mesh Change",
            "",
            "| pair | status | mixed setup | burn change % | Tsurf change % | Gf change % | wall T change % |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in adjacent:
        fields = [
            f"{label} adjacent change (%)" for _key, label, _threshold in CONVERGENCE_METRICS
        ]
        lines.append(
            f"| fw{row['from_fw']} -> fw{row['to_fw']} | {row['from_status']} -> {row['to_status']} | {row['mixed_setup']} | "
            f"{fmt(row.get(fields[0]), 4)} | {fmt(row.get(fields[1]), 4)} | "
            f"{fmt(row.get(fields[2]), 4)} | {fmt(row.get(fields[3]), 4)} |"
        )
    lines.append("")

    lines.extend(["## Figures", ""])
    for plot in plot_paths:
        rel = plot.relative_to(outdir)
        lines.append(f"- [{rel.as_posix()}]({rel.as_posix()})")
    lines.append("")

    lines.extend(
        [
            "## Output Files",
            "",
            "- `mesh_independence_metrics.csv`: fuel-wall area-weighted metrics for each selected DAT.",
            f"- `mesh_independence_convergence.csv`: relative differences to `fw{ref_fw}`.",
            "- `mesh_independence_adjacent.csv`: adjacent-grid changes.",
            "- `fuelwall_profiles_binned.csv`: binned fuel-wall axial profiles.",
            "- `residual_summary.csv`: residual final values and iteration counts.",
            "- `post_summary.json`: machine-readable verdict metadata.",
        ]
    )
    (outdir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "passed_strict_primary_sequence": passed,
        "campaign_complete": campaign_complete,
        "requested_fws": requested_fws,
        "completed_fws": selected_fws,
        "accepted_fws": accepted_fws,
        "missing_target_fws": missing_target_fws,
        "iteration_tag": iteration_tag,
        "expected_iterations": expected_iterations,
        "grid_independence_verdict": (
            "complete: all requested grids are accepted and the strict finest-adjacent primary sequence passed"
            if campaign_complete and passed
            else "incomplete or caveated: do not claim full four-grid independence without reviewing missing, skipped, or failed cases"
        ),
        "reference": {"tag": ref["tag"], "fw": ref["fw"], "setup": ref["setup"]},
        "strict_reference": {
            "tag": comparable_ref["tag"],
            "fw": comparable_ref["fw"],
            "setup": comparable_ref["setup"],
        },
        "strict_previous": None if prev_primary is None else {"tag": prev_primary["tag"], "fw": prev_primary["fw"]},
        "strict_checks": final_checks,
        "failed_physical_validation": [
            {"tag": m["tag"], "fw": m["fw"], "notes": m.get("analysis_notes")} for m in failed
        ],
        "excluded_records": excluded_records,
        "campaign_status_notes": campaign_status_notes,
        "warnings": [
            "Review campaign completion caveats before claiming full four-grid mesh independence."
        ]
        if not campaign_complete
        else [],
        "plots": [str(path) for path in plot_paths],
    }
    (outdir / "post_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def residual_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        series = read_residual_series(Path(metric["data_file"]))
        for name, (iters, values) in series.items():
            finite = values[np.isfinite(values)]
            rows.append(
                {
                    "tag": metric["tag"],
                    "fw": metric["fw"],
                    "setup": metric["setup"],
                    "residual": name,
                    "iterations": int(len(iters)),
                    "final_iter": int(iters[-1]) if len(iters) else None,
                    "initial": float(finite[0]) if finite.size else None,
                    "final": float(finite[-1]) if finite.size else None,
                    "min": float(np.min(finite)) if finite.size else None,
                    "max": float(np.max(finite)) if finite.size else None,
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-process nofuel standard-v2 DAT files.")
    parser.add_argument("--cas-dat", type=Path, default=DEFAULT_CAS_DAT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_POST)
    parser.add_argument("--iteration-tag", default="iter700", help="DAT filename tag to include, e.g. iter700 or iter1300.")
    parser.add_argument("--expected-iterations", type=int, default=700, help="Minimum residual iteration count for acceptance.")
    parser.add_argument(
        "--requested-fws",
        type=parse_fw_list,
        default=parse_fw_list("750,1000,1250,1500"),
        help="Comma/space separated target fw values for completion reporting.",
    )
    parser.add_argument("--campaign-status-json", type=Path, default=None, help="Optional run-status JSON to include failure notes.")
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    records, excluded_records = discover_dat_cases(args.cas_dat, args.iteration_tag, args.requested_fws)
    if not records:
        raise SystemExit(f"No .dat.h5 files found under {args.cas_dat}")
    campaign_status = load_campaign_status(args.campaign_status_json)

    metrics: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    profiles: list[dict[str, Any]] = []
    for record in records:
        print(f"Analyzing {record['tag']} ...", flush=True)
        metric, detail, profile_rows = analyze_record(record, args.expected_iterations)
        metrics.append(metric)
        details[metric["tag"]] = detail
        profiles.extend(profile_rows)

    metrics = sorted(metrics, key=lambda m: int(m["fw"]))
    convergence, adjacent = build_convergence(metrics)
    plots = make_plots(metrics, convergence, adjacent, profiles, args.outdir)

    csv_write(args.outdir / "mesh_independence_metrics.csv", metrics)
    csv_write(args.outdir / "mesh_independence_convergence.csv", convergence)
    csv_write(args.outdir / "mesh_independence_adjacent.csv", adjacent)
    csv_write(args.outdir / "fuelwall_profiles_binned.csv", profiles)
    csv_write(args.outdir / "residual_summary.csv", residual_rows(metrics))
    (args.outdir / "mesh_independence_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.outdir / "mesh_independence_details.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report_v2(
        args.outdir,
        args.cas_dat,
        metrics,
        convergence,
        adjacent,
        plots,
        excluded_records,
        args.iteration_tag,
        args.expected_iterations,
        args.requested_fws,
        campaign_status,
    )
    print(f"Wrote post-processing outputs to {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
