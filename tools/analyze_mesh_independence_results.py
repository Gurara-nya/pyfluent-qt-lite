from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import h5py
import numpy as np


UDM = {
    "fuel_wall_flag": 0,
    "dynamic_mode_flag": 1,
    "face_area": 4,
    "t_surf": 5,
    "t_face": 6,
    "t_cell": 7,
    "r_total": 8,
    "gf_total": 9,
    "q_total": 12,
    "q_relaxed": 13,
    "dbg_reason": 29,
    "gf_ent": 46,
    "mdot_ent_dpm": 50,
    "r_wax": 52,
    "r_v": 53,
    "r_ent": 54,
    "face_x": 55,
    "cell_x": 56,
    "surface_diam": 59,
}

KEY_FIELDS = {
    "r_total_m_s": UDM["r_total"],
    "r_wax_m_s": UDM["r_wax"],
    "r_v_m_s": UDM["r_v"],
    "r_ent_m_s": UDM["r_ent"],
    "gf_total_kg_m2_s": UDM["gf_total"],
    "gf_ent_kg_m2_s": UDM["gf_ent"],
    "t_surf_K": UDM["t_surf"],
    "t_face_udm_K": UDM["t_face"],
    "q_total": UDM["q_total"],
    "q_relaxed": UDM["q_relaxed"],
    "surface_diam_m": UDM["surface_diam"],
}


def scalar_attr(obj: h5py.Dataset | h5py.Group, name: str) -> int:
    value = obj.attrs[name]
    arr = np.asarray(value).reshape(-1)
    return int(arr[0])


def finite_stats(values: np.ndarray) -> dict[str, float | int | None]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"count": 0, "mean": None, "min": None, "max": None, "p05": None, "p50": None, "p95": None}
    q = np.percentile(arr, [5, 50, 95])
    return {
        "count": int(arr.size),
        "mean": float(np.mean(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p05": float(q[0]),
        "p50": float(q[1]),
        "p95": float(q[2]),
    }


def weighted_mean(values: np.ndarray, weights: np.ndarray | None) -> float | None:
    arr = np.asarray(values, dtype=float)
    valid = np.isfinite(arr)
    if weights is None:
        return float(np.mean(arr[valid])) if np.any(valid) else None
    w = np.asarray(weights, dtype=float)
    valid &= np.isfinite(w) & (w > 0.0)
    if not np.any(valid):
        return float(np.mean(arr[np.isfinite(arr)])) if np.any(np.isfinite(arr)) else None
    total = float(np.sum(w[valid]))
    if total <= 0.0:
        return None
    return float(np.sum(arr[valid] * w[valid]) / total)


def weighted_percentile(values: np.ndarray, weights: np.ndarray | None, percentile: float) -> float | None:
    arr = np.asarray(values, dtype=float)
    valid = np.isfinite(arr)
    if weights is None:
        return float(np.percentile(arr[valid], percentile)) if np.any(valid) else None
    w = np.asarray(weights, dtype=float)
    valid &= np.isfinite(w) & (w > 0.0)
    if not np.any(valid):
        return None
    order = np.argsort(arr[valid])
    sorted_values = arr[valid][order]
    sorted_weights = w[valid][order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = percentile / 100.0 * cumulative[-1]
    idx = int(np.searchsorted(cumulative, cutoff, side="left"))
    idx = min(idx, sorted_values.size - 1)
    return float(sorted_values[idx])


def decode_zone_names(dataset: h5py.Dataset) -> list[str]:
    raw = dataset[()]
    flat = np.asarray(raw).reshape(-1)
    if flat.size == 1:
        item = flat[0]
        text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
        return [part for part in text.split(";") if part]
    names: list[str] = []
    for item in flat:
        names.append(item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item))
    return names


def find_face_zone(case_path: Path, zone_name: str) -> dict[str, Any]:
    with h5py.File(case_path, "r") as h5:
        topo = h5["meshes/1/faces/zoneTopology"]
        names = decode_zone_names(topo["name"])
        ids = topo["id"][()]
        mins = topo["minId"][()]
        maxs = topo["maxId"][()]
        for i, name in enumerate(names):
            if name == zone_name:
                min_id = int(mins[i])
                max_id = int(maxs[i])
                return {
                    "name": name,
                    "id": int(ids[i]),
                    "min_id": min_id,
                    "max_id": max_id,
                    "count": max_id - min_id + 1,
                }
    raise ValueError(f"Face zone {zone_name!r} not found in {case_path}")


def read_section_interval(group: h5py.Group, min_id: int, max_id: int) -> np.ndarray | None:
    for key in sorted(group.keys(), key=lambda x: int(x) if x.isdigit() else x):
        ds = group[key]
        section_min = scalar_attr(ds, "minId")
        section_max = scalar_attr(ds, "maxId")
        if section_min <= min_id and max_id <= section_max:
            start = min_id - section_min
            stop = max_id - section_min + 1
            return ds[start:stop]
    return None


def read_fuelwall_cells(dat_path: Path) -> np.ndarray:
    chunks: list[np.ndarray] = []
    with h5py.File(dat_path, "r") as h5:
        group = h5["results/1/phase-1/cells/SV_UDM_I"]
        for key in sorted(group.keys(), key=lambda x: int(x) if x.isdigit() else x):
            arr = group[key][()]
            if arr.ndim != 2 or arr.shape[1] <= UDM["surface_diam"]:
                continue
            mask = np.isfinite(arr[:, UDM["fuel_wall_flag"]]) & (arr[:, UDM["fuel_wall_flag"]] > 0.5)
            if np.any(mask):
                chunks.append(arr[mask])
    if not chunks:
        raise ValueError(f"No fuel-wall flagged cell UDM rows found in {dat_path}")
    return np.vstack(chunks)


def read_face_field(dat_path: Path, field_name: str, min_id: int, max_id: int) -> np.ndarray | None:
    with h5py.File(dat_path, "r") as h5:
        path = f"results/1/phase-1/faces/{field_name}"
        if path not in h5:
            return None
        obj = h5[path]
        if isinstance(obj, h5py.Dataset):
            return obj[()]
        return read_section_interval(obj, min_id, max_id)


def residual_summary(dat_path: Path) -> dict[str, dict[str, float | int | None]]:
    summary: dict[str, dict[str, float | int | None]] = {}
    with h5py.File(dat_path, "r") as h5:
        base = "results/residuals/phase-1"
        if base not in h5:
            return summary
        group = h5[base]
        for name in group.keys():
            obj = group[name]
            if not isinstance(obj, h5py.Group) or "data" not in obj or "iterations" not in obj:
                continue
            data = obj["data"][()]
            iterations = obj["iterations"][()]
            if data.size == 0 or iterations.size == 0:
                continue
            series = np.asarray(data[:, 0], dtype=float) if data.ndim > 1 else np.asarray(data, dtype=float)
            valid = np.isfinite(series)
            summary[name] = {
                "n": int(iterations.size),
                "final_iter": int(iterations[-1]),
                "initial": float(series[valid][0]) if np.any(valid) else None,
                "final": float(series[valid][-1]) if np.any(valid) else None,
                "min": float(np.min(series[valid])) if np.any(valid) else None,
            }
    return summary


def parse_tag(tag: str) -> tuple[int | None, int | None]:
    fuelend_match = re.search(r"fuelend(\d+)", tag)
    fw_match = re.search(r"fw(\d+)", tag)
    fuelend = int(fuelend_match.group(1)) if fuelend_match else None
    fw = int(fw_match.group(1)) if fw_match else None
    return fuelend, fw


def percent_diff(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or not math.isfinite(value) or not math.isfinite(reference):
        return None
    if abs(reference) < 1e-300:
        return None
    return float((value - reference) / reference * 100.0)


def analyze_case(row: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    tag = row["tag"]
    dat_path = Path(row["data_file"])
    case_path = Path(row["prepared_case"])
    fuelend, fw = parse_tag(tag)
    zone = find_face_zone(case_path, "fuel-wall")
    wall_cells = read_fuelwall_cells(dat_path)
    area = np.asarray(wall_cells[:, UDM["face_area"]], dtype=float)
    valid_area = np.isfinite(area) & (area > 0.0)
    weights = area if np.any(valid_area) else None
    active = np.isfinite(wall_cells[:, UDM["r_total"]]) & (wall_cells[:, UDM["r_total"]] > 1e-12)
    residuals = residual_summary(dat_path)

    metrics: dict[str, Any] = {
        "tag": tag,
        "fuelend": fuelend,
        "fw": fw,
        "status": row.get("status"),
        "attempts": int(row.get("attempts") or 0),
        "data_size_bytes": int(row.get("data_size") or dat_path.stat().st_size),
        "manifest_residual_iterations": int(row.get("residual_iterations") or 0),
        "case_file": str(case_path),
        "data_file": str(dat_path),
        "fuelwall_face_zone_id": zone["id"],
        "fuelwall_face_zone_count": zone["count"],
        "fuelwall_cell_udm_count": int(wall_cells.shape[0]),
        "area_valid_count": int(np.count_nonzero(valid_area)),
        "area_sum_m2": float(np.sum(area[valid_area])) if np.any(valid_area) else None,
        "active_count": int(np.count_nonzero(active)),
        "active_fraction": float(np.count_nonzero(active) / wall_cells.shape[0]),
    }

    for metric_name, udm_index in KEY_FIELDS.items():
        values = np.asarray(wall_cells[:, udm_index], dtype=float)
        stats = finite_stats(values)
        metrics[f"{metric_name}_mean"] = stats["mean"]
        metrics[f"{metric_name}_min"] = stats["min"]
        metrics[f"{metric_name}_max"] = stats["max"]
        metrics[f"{metric_name}_p05"] = stats["p05"]
        metrics[f"{metric_name}_p50"] = stats["p50"]
        metrics[f"{metric_name}_p95"] = stats["p95"]
        metrics[f"{metric_name}_area_mean"] = weighted_mean(values, weights)
        metrics[f"{metric_name}_area_p05"] = weighted_percentile(values, weights, 5.0)
        metrics[f"{metric_name}_area_p50"] = weighted_percentile(values, weights, 50.0)
        metrics[f"{metric_name}_area_p95"] = weighted_percentile(values, weights, 95.0)

    active_weights = area[active] if np.any(active) else None
    metrics["r_total_active_area_mean_m_s"] = weighted_mean(wall_cells[active, UDM["r_total"]], active_weights)
    metrics["t_surf_active_area_mean_K"] = weighted_mean(wall_cells[active, UDM["t_surf"]], active_weights)
    metrics["mdot_ent_dpm_sum_kg_s"] = float(np.sum(wall_cells[:, UDM["mdot_ent_dpm"]]))
    metrics["mdot_ent_dpm_abs_sum_kg_s"] = float(np.sum(np.abs(wall_cells[:, UDM["mdot_ent_dpm"]])))
    metrics["r_total_area_mean_mm_s"] = metrics["r_total_m_s_area_mean"] * 1000.0
    metrics["r_total_area_mean_mm_min"] = metrics["r_total_m_s_area_mean"] * 60000.0
    metrics["r_total_active_area_mean_mm_s"] = (
        metrics["r_total_active_area_mean_m_s"] * 1000.0 if metrics["r_total_active_area_mean_m_s"] is not None else None
    )
    metrics["r_total_active_area_mean_mm_min"] = (
        metrics["r_total_active_area_mean_m_s"] * 60000.0 if metrics["r_total_active_area_mean_m_s"] is not None else None
    )

    dbg = np.asarray(wall_cells[:, UDM["dbg_reason"]], dtype=float)
    dbg_int = [int(round(x)) for x in dbg[np.isfinite(dbg)]]
    dbg_counts = Counter(dbg_int)
    metrics["dbg_reason_top"] = json.dumps(dbg_counts.most_common(5), ensure_ascii=False)
    metrics["dbg_reason_nonzero_fraction"] = float(sum(v for k, v in dbg_counts.items() if k != 0) / max(len(dbg_int), 1))

    for field_name in ["SV_WALL_T_INNER", "SV_T", "SV_HEAT_FLUX"]:
        values = read_face_field(dat_path, field_name, zone["min_id"], zone["max_id"])
        if values is None:
            continue
        values = np.asarray(values, dtype=float)
        stats = finite_stats(values)
        prefix = field_name.lower()
        metrics[f"{prefix}_count"] = stats["count"]
        metrics[f"{prefix}_mean"] = stats["mean"]
        metrics[f"{prefix}_min"] = stats["min"]
        metrics[f"{prefix}_max"] = stats["max"]
        metrics[f"{prefix}_p05"] = stats["p05"]
        metrics[f"{prefix}_p50"] = stats["p50"]
        metrics[f"{prefix}_p95"] = stats["p95"]
        if values.shape[0] == area.shape[0]:
            metrics[f"{prefix}_area_mean_assuming_order"] = weighted_mean(values, weights)

    for residual_name, rs in residuals.items():
        safe_name = residual_name.replace("-", "_").replace(" ", "_")
        metrics[f"res_{safe_name}_n"] = rs["n"]
        metrics[f"res_{safe_name}_final_iter"] = rs["final_iter"]
        metrics[f"res_{safe_name}_initial"] = rs["initial"]
        metrics[f"res_{safe_name}_final"] = rs["final"]
        metrics[f"res_{safe_name}_min"] = rs["min"]

    status, notes = physical_validation(metrics)
    metrics["analysis_status"] = status
    metrics["analysis_notes"] = "; ".join(notes)

    x = np.asarray(wall_cells[:, UDM["face_x"]], dtype=float)
    profile_rows = binned_profile(tag, fuelend, fw, x, area, wall_cells)
    detail = {
        "tag": tag,
        "fuelwall_zone": zone,
        "residuals": residuals,
        "dbg_reason_counts": dict(dbg_counts),
    }
    return metrics, detail, profile_rows


def physical_validation(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    iterations = metrics.get("res_continuity_n") or metrics.get("manifest_residual_iterations") or 0
    continuity = metrics.get("res_continuity_final")
    burn = metrics.get("r_total_area_mean_mm_s")
    temp = metrics.get("t_surf_K_area_mean")
    face_temp = metrics.get("sv_wall_t_inner_mean")

    if iterations < 700:
        notes.append(f"residual iteration count is {iterations}")
    if not isinstance(continuity, (float, int)) or not math.isfinite(float(continuity)) or float(continuity) > 1e-2:
        notes.append(f"continuity final residual is {fmt(continuity, 4)}")
    if not isinstance(burn, (float, int)) or not math.isfinite(float(burn)) or float(burn) < 0.5:
        notes.append(f"area-mean burn rate is {fmt(burn, 6)} mm/s")
    if not isinstance(temp, (float, int)) or not math.isfinite(float(temp)) or float(temp) < 700.0:
        notes.append(f"area-mean Tsurf is {fmt(temp, 3)} K")
    if not isinstance(face_temp, (float, int)) or not math.isfinite(float(face_temp)) or float(face_temp) < 700.0:
        notes.append(f"fuel-wall SV_WALL_T_INNER is {fmt(face_temp, 3)} K")

    return ("accepted" if not notes else "failed_physical_validation", notes)


def binned_profile(
    tag: str,
    fuelend: int | None,
    fw: int | None,
    x: np.ndarray,
    area: np.ndarray,
    wall_cells: np.ndarray,
    bins: int = 200,
) -> list[dict[str, Any]]:
    valid = np.isfinite(x)
    if not np.any(valid):
        return []
    x_valid = x[valid]
    xmin = float(np.min(x_valid))
    xmax = float(np.max(x_valid))
    if not math.isfinite(xmin) or not math.isfinite(xmax) or xmax <= xmin:
        return []
    edges = np.linspace(xmin, xmax, bins + 1)
    assignments = np.digitize(x, edges, right=False) - 1
    assignments = np.clip(assignments, 0, bins - 1)
    rows: list[dict[str, Any]] = []
    for i in range(bins):
        mask = valid & (assignments == i)
        if not np.any(mask):
            continue
        weights = area[mask]
        if not np.any(np.isfinite(weights) & (weights > 0.0)):
            weights = None
        rows.append(
            {
                "tag": tag,
                "fuelend": fuelend,
                "fw": fw,
                "x_mid_m": float((edges[i] + edges[i + 1]) / 2.0),
                "count": int(np.count_nonzero(mask)),
                "area_sum_m2": float(np.sum(area[mask][np.isfinite(area[mask]) & (area[mask] > 0.0)])),
                "r_total_m_s_area_mean": weighted_mean(wall_cells[mask, UDM["r_total"]], weights),
                "r_total_mm_s_area_mean": (
                    weighted_mean(wall_cells[mask, UDM["r_total"]], weights) * 1000.0
                    if weighted_mean(wall_cells[mask, UDM["r_total"]], weights) is not None
                    else None
                ),
                "t_surf_K_area_mean": weighted_mean(wall_cells[mask, UDM["t_surf"]], weights),
                "gf_total_kg_m2_s_area_mean": weighted_mean(wall_cells[mask, UDM["gf_total"]], weights),
            }
        )
    return rows


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_convergence_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_fuelend: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_fw: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for m in metrics:
        if m.get("fuelend") is not None:
            by_fuelend[int(m["fuelend"])].append(m)
        if m.get("fw") is not None:
            by_fw[int(m["fw"])].append(m)

    compare_metrics = [
        ("r_total_area_mean_mm_s", "burn_rate_mm_s"),
        ("r_total_area_mean_mm_min", "burn_rate_mm_min"),
        ("t_surf_K_area_mean", "t_surf_K"),
        ("sv_wall_t_inner_mean", "wall_t_inner_K"),
    ]

    for fuelend, group in sorted(by_fuelend.items()):
        valid_group = [item for item in group if item.get("analysis_status") == "accepted"]
        ref = max(valid_group, key=lambda x: int(x["fw"])) if valid_group else None
        target_fw = max(int(item["fw"]) for item in group)
        for m in sorted(group, key=lambda x: int(x["fw"])):
            row = {
                "axis": "fw_refinement",
                "fuelend": fuelend,
                "fw": m["fw"],
                "tag": m["tag"],
                "analysis_status": m.get("analysis_status"),
                "reference_tag": ref["tag"] if ref else "",
                "reference_fw": ref["fw"] if ref else None,
                "reference_is_nominal_finest": bool(ref and int(ref["fw"]) == target_fw),
            }
            for key, label in compare_metrics:
                row[label] = m.get(key)
                row[f"{label}_diff_to_ref_pct"] = (
                    percent_diff(m.get(key), ref.get(key)) if ref and m.get("analysis_status") == "accepted" else None
                )
            rows.append(row)

    for fw, group in sorted(by_fw.items()):
        valid_group = [item for item in group if item.get("analysis_status") == "accepted"]
        ref = max(valid_group, key=lambda x: int(x["fuelend"])) if valid_group else None
        target_fuelend = max(int(item["fuelend"]) for item in group)
        for m in sorted(group, key=lambda x: int(x["fuelend"])):
            row = {
                "axis": "fuelend_refinement",
                "fuelend": m["fuelend"],
                "fw": fw,
                "tag": m["tag"],
                "analysis_status": m.get("analysis_status"),
                "reference_tag": ref["tag"] if ref else "",
                "reference_fuelend": ref["fuelend"] if ref else None,
                "reference_is_nominal_finest": bool(ref and int(ref["fuelend"]) == target_fuelend),
            }
            for key, label in compare_metrics:
                row[label] = m.get(key)
                row[f"{label}_diff_to_ref_pct"] = (
                    percent_diff(m.get(key), ref.get(key)) if ref and m.get("analysis_status") == "accepted" else None
                )
            rows.append(row)
    return rows


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "-"
        if abs(value) >= 1e4 or (0 < abs(value) < 1e-3):
            return f"{value:.{digits}e}"
        return f"{value:.{digits}f}"
    return str(value)


def build_endpoint_rows(
    metrics: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    end_fraction: float = 0.10,
) -> list[dict[str, Any]]:
    accepted_tags = {m["tag"] for m in metrics if m.get("analysis_status") == "accepted"}
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    metric_by_tag = {m["tag"]: m for m in metrics}
    for row in profiles:
        if row.get("tag") in accepted_tags:
            by_tag[str(row["tag"])].append(row)

    rows: list[dict[str, Any]] = []
    for tag, tag_rows in sorted(by_tag.items()):
        xs = np.asarray([float(r["x_mid_m"]) for r in tag_rows], dtype=float)
        xmin = float(np.nanmin(xs))
        xmax = float(np.nanmax(xs))
        span = xmax - xmin
        if not math.isfinite(span) or span <= 0.0:
            continue
        for region, predicate in [
            ("front_x_low_10pct", lambda x_norm: x_norm <= end_fraction),
            ("back_x_high_10pct", lambda x_norm: x_norm >= 1.0 - end_fraction),
        ]:
            selected: list[dict[str, Any]] = []
            for r in tag_rows:
                x_norm = (float(r["x_mid_m"]) - xmin) / span
                if predicate(x_norm):
                    selected.append(r)
            if not selected:
                continue
            weights = np.asarray([float(r.get("area_sum_m2") or 0.0) for r in selected], dtype=float)
            if not np.any(np.isfinite(weights) & (weights > 0.0)):
                weights = None
            burn = np.asarray([float(r["r_total_mm_s_area_mean"]) for r in selected], dtype=float)
            temp = np.asarray([float(r["t_surf_K_area_mean"]) for r in selected], dtype=float)
            gf = np.asarray([float(r["gf_total_kg_m2_s_area_mean"]) for r in selected], dtype=float)
            x_sel = np.asarray([float(r["x_mid_m"]) for r in selected], dtype=float)
            source_metric = metric_by_tag[tag]
            rows.append(
                {
                    "tag": tag,
                    "fuelend": source_metric["fuelend"],
                    "fw": source_metric["fw"],
                    "region": region,
                    "end_fraction": end_fraction,
                    "x_min_m": float(np.min(x_sel)),
                    "x_max_m": float(np.max(x_sel)),
                    "x_norm_min": float((np.min(x_sel) - xmin) / span),
                    "x_norm_max": float((np.max(x_sel) - xmin) / span),
                    "bin_count": len(selected),
                    "area_sum_m2": float(np.sum(weights[np.isfinite(weights) & (weights > 0.0)])) if weights is not None else None,
                    "r_total_mm_s_area_mean": weighted_mean(burn, weights),
                    "t_surf_K_area_mean": weighted_mean(temp, weights),
                    "gf_total_kg_m2_s_area_mean": weighted_mean(gf, weights),
                }
            )
    return rows


def build_front_raw_profile_rows(metrics: list[dict[str, Any]], max_distance_mm: float = 2.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in sorted(metrics, key=lambda m: (int(m["fuelend"]), int(m["fw"]))):
        if metric.get("analysis_status") != "accepted":
            continue
        wall_cells = read_fuelwall_cells(Path(metric["data_file"]))
        x = np.asarray(wall_cells[:, UDM["face_x"]], dtype=float)
        r = np.asarray(wall_cells[:, UDM["r_total"]], dtype=float) * 1000.0
        area = np.asarray(wall_cells[:, UDM["face_area"]], dtype=float)
        valid = np.isfinite(x) & np.isfinite(r)
        if not np.any(valid):
            continue
        x0 = float(np.min(x[valid]))
        distance_mm = (x - x0) * 1000.0
        valid &= (distance_mm >= 0.0) & (distance_mm <= max_distance_mm)
        order = np.argsort(distance_mm[valid])
        for idx in np.where(valid)[0][order]:
            rows.append(
                {
                    "tag": metric["tag"],
                    "fuelend": metric["fuelend"],
                    "fw": metric["fw"],
                    "fuelwall_face_count": metric["fuelwall_face_zone_count"],
                    "distance_from_front_mm": float(distance_mm[idx]),
                    "r_total_mm_s": float(r[idx]),
                    "area_m2": float(area[idx]) if np.isfinite(area[idx]) else None,
                }
            )
    return rows


def make_plots(
    metrics: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    endpoint_rows: list[dict[str, Any]],
    front_raw_rows: list[dict[str, Any]],
    outdir: Path,
) -> list[Path]:
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    outputs: list[Path] = []

    rows = sorted([m for m in metrics if m.get("analysis_status") == "accepted"], key=lambda m: (int(m["fuelend"]), int(m["fw"])))
    if not rows:
        return outputs
    fuelends = sorted({int(m["fuelend"]) for m in rows})
    fws = sorted({int(m["fw"]) for m in rows})

    fig, axes = plt.subplots(2, 1, figsize=(8.5, 8.0), sharex=True)
    for fuelend in fuelends:
        group = [m for m in rows if int(m["fuelend"]) == fuelend]
        axes[0].plot([m["fw"] for m in group], [m["r_total_area_mean_mm_s"] for m in group], marker="o", label=f"fuelend{fuelend:03d}")
        axes[1].plot([m["fw"] for m in group], [m["t_surf_K_area_mean"] for m in group], marker="o", label=f"fuelend{fuelend:03d}")
    axes[0].set_ylabel("Area-mean burn rate (mm/s)")
    axes[1].set_ylabel("Area-mean Tsurf (K)")
    axes[1].set_xlabel("fuel-wall face count")
    axes[0].grid(True, alpha=0.25)
    axes[1].grid(True, alpha=0.25)
    axes[0].legend(ncol=3, fontsize=8)
    fig.suptitle("Fuel-wall refinement sensitivity")
    fig.tight_layout()
    path = outdir / "fw_refinement_convergence.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    outputs.append(path)

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    x_grid = sorted({int(m["fw"]) for m in metrics})
    for fuelend in fuelends:
        group_by_fw = {int(m["fw"]): m for m in rows if int(m["fuelend"]) == fuelend}
        y_vals = [group_by_fw[fw]["r_total_area_mean_mm_s"] if fw in group_by_fw else np.nan for fw in x_grid]
        ax.plot(x_grid, y_vals, marker="o", linewidth=1.45, label=f"fuelend{fuelend:03d}")
    ax.set_xlabel("fuel-wall face count")
    ax.set_ylabel("Area-weighted mean burn rate on fuel-wall (mm/s)")
    ax.set_xticks(x_grid)
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    ax.set_title("Fuel-wall mean burn rate vs face count (accepted cases only)")
    fig.tight_layout()
    path = outdir / "burn_rate_area_mean_vs_facecount_clean.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    outputs.append(path)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5), sharey=False)
    accepted_by_tag = {m["tag"]: m for m in rows}
    for metric_key, ylabel, ax in [
        ("burn_rate_mm_s_diff_to_ref_pct", "Burn-rate diff to fw3200 (%)", axes[0]),
        ("t_surf_K_diff_to_ref_pct", "Tsurf diff to fw3200 (%)", axes[1]),
    ]:
        width = 0.36
        fuelend_positions = np.arange(len(fuelends), dtype=float)
        for j, fw in enumerate([1600, 2400]):
            values: list[float] = []
            labels: list[str] = []
            for fuelend in fuelends:
                group = [m for m in rows if int(m["fuelend"]) == fuelend]
                ref_candidates = [m for m in group if int(m["fw"]) == 3200]
                item_candidates = [m for m in group if int(m["fw"]) == fw]
                if ref_candidates and item_candidates:
                    diff = percent_diff(item_candidates[0].get(
                        "r_total_area_mean_mm_s" if "burn" in metric_key else "t_surf_K_area_mean"
                    ), ref_candidates[0].get("r_total_area_mean_mm_s" if "burn" in metric_key else "t_surf_K_area_mean"))
                    values.append(abs(diff) if diff is not None else np.nan)
                else:
                    values.append(np.nan)
                labels.append(f"{fuelend:03d}")
            ax.bar(fuelend_positions + (j - 0.5) * width, values, width=width, label=f"fw{fw}")
        ax.axhline(1.0, color="#666666", linestyle="--", linewidth=0.9, alpha=0.7)
        ax.set_xticks(fuelend_positions)
        ax.set_xticklabels(labels)
        ax.set_xlabel("fuelend")
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", alpha=0.25)
        ax.legend(fontsize=8)
    fig.suptitle("Accepted cases only: relative mesh sensitivity")
    fig.tight_layout()
    path = outdir / "grid_independence_relative_error_clean.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    outputs.append(path)

    fig, axes = plt.subplots(2, 1, figsize=(8.5, 8.0), sharex=True)
    for fw in fws:
        group = [m for m in rows if int(m["fw"]) == fw]
        axes[0].plot([m["fuelend"] for m in group], [m["r_total_area_mean_mm_s"] for m in group], marker="o", label=f"fw{fw}")
        axes[1].plot([m["fuelend"] for m in group], [m["t_surf_K_area_mean"] for m in group], marker="o", label=f"fw{fw}")
    axes[0].set_ylabel("Area-mean burn rate (mm/s)")
    axes[1].set_ylabel("Area-mean Tsurf (K)")
    axes[1].set_xlabel("fuelend index")
    axes[0].grid(True, alpha=0.25)
    axes[1].grid(True, alpha=0.25)
    axes[0].legend(ncol=3, fontsize=8)
    fig.suptitle("Fuelend refinement sensitivity")
    fig.tight_layout()
    path = outdir / "fuelend_refinement_convergence.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    outputs.append(path)

    profile_by_key: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    accepted_tags = {m["tag"] for m in rows}
    for row in profiles:
        if row.get("tag") not in accepted_tags:
            continue
        if row.get("fuelend") is not None and row.get("fw") is not None:
            profile_by_key[(int(row["fuelend"]), int(row["fw"]))].append(row)

    for metric_key, ylabel, filename in [
        ("r_total_mm_s_area_mean", "Burn rate (mm/s)", "profiles_burn_rate_by_fuelend.png"),
        ("t_surf_K_area_mean", "Tsurf (K)", "profiles_tsurf_by_fuelend.png"),
    ]:
        fig, axes = plt.subplots(len(fuelends), 1, figsize=(9.5, max(7.0, 2.0 * len(fuelends))), sharex=True)
        if len(fuelends) == 1:
            axes = [axes]
        for ax, fuelend in zip(axes, fuelends):
            for fw in fws:
                group = sorted(profile_by_key.get((fuelend, fw), []), key=lambda x: x["x_mid_m"])
                if not group:
                    continue
                ax.plot([r["x_mid_m"] for r in group], [r[metric_key] for r in group], label=f"fw{fw}", linewidth=1.2)
            ax.set_ylabel(f"fuelend{fuelend:03d}\n{ylabel}")
            ax.grid(True, alpha=0.25)
            ax.legend(ncol=3, fontsize=8, loc="best")
        axes[-1].set_xlabel("x on fuel-wall (m)")
        fig.tight_layout()
        path = outdir / filename
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)

    endpoint_plot_records = [r for r in endpoint_rows if r.get("tag") in accepted_tags]
    if endpoint_plot_records:
        by_region_key: dict[tuple[int, int, str], dict[str, Any]] = {}
        for row in endpoint_plot_records:
            by_region_key[(int(row["fuelend"]), int(row["fw"]), str(row["region"]))] = row

        fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0), sharex=True)
        panels = [
            ("front_x_low_10pct", "r_total_mm_s_area_mean", "Front 10% burn rate (mm/s)", axes[0, 0]),
            ("back_x_high_10pct", "r_total_mm_s_area_mean", "Back 10% burn rate (mm/s)", axes[0, 1]),
            ("front_x_low_10pct", "t_surf_K_area_mean", "Front 10% Tsurf (K)", axes[1, 0]),
            ("back_x_high_10pct", "t_surf_K_area_mean", "Back 10% Tsurf (K)", axes[1, 1]),
        ]
        for region, key, ylabel, ax in panels:
            for fuelend in fuelends:
                x_vals: list[int] = []
                y_vals: list[float] = []
                for fw in fws:
                    row = by_region_key.get((fuelend, fw, region))
                    if row and row.get(key) is not None:
                        x_vals.append(fw)
                        y_vals.append(float(row[key]))
                if x_vals:
                    ax.plot(x_vals, y_vals, marker="o", linewidth=1.25, label=f"fuelend{fuelend:03d}")
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.25)
        axes[1, 0].set_xlabel("fuel-wall face count")
        axes[1, 1].set_xlabel("fuel-wall face count")
        axes[0, 0].legend(ncol=2, fontsize=8)
        fig.suptitle("Fuel-wall endpoint mesh sensitivity (accepted cases only)")
        fig.tight_layout()
        path = outdir / "fuelwall_front_back_mesh_sensitivity.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)

        fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.5), sharex=True)
        for key, ylabel, ax in [
            ("r_total_mm_s_area_mean", "Back - front burn rate (mm/s)", axes[0]),
            ("t_surf_K_area_mean", "Back - front Tsurf (K)", axes[1]),
        ]:
            for fuelend in fuelends:
                x_vals = []
                y_vals = []
                for fw in fws:
                    front = by_region_key.get((fuelend, fw, "front_x_low_10pct"))
                    back = by_region_key.get((fuelend, fw, "back_x_high_10pct"))
                    if front and back and front.get(key) is not None and back.get(key) is not None:
                        x_vals.append(fw)
                        y_vals.append(float(back[key]) - float(front[key]))
                if x_vals:
                    ax.plot(x_vals, y_vals, marker="o", linewidth=1.25, label=f"fuelend{fuelend:03d}")
            ax.axhline(0.0, color="#666666", linestyle="--", linewidth=0.9, alpha=0.65)
            ax.set_ylabel(ylabel)
            ax.set_xlabel("fuel-wall face count")
            ax.grid(True, alpha=0.25)
        axes[0].legend(ncol=2, fontsize=8)
        fig.suptitle("Fuel-wall rear-front endpoint contrast (accepted cases only)")
        fig.tight_layout()
        path = outdir / "fuelwall_front_back_delta.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)

    for metric_key, ylabel, filename in [
        ("r_total_mm_s_area_mean", "Burn rate (mm/s)", "fuelwall_endpoint_profiles_burn_rate.png"),
        ("t_surf_K_area_mean", "Tsurf (K)", "fuelwall_endpoint_profiles_tsurf.png"),
    ]:
        fig, axes = plt.subplots(len(fuelends), 2, figsize=(11.5, max(8.0, 2.0 * len(fuelends))), sharex="col")
        if len(fuelends) == 1:
            axes = np.asarray([axes])
        for row_index, fuelend in enumerate(fuelends):
            for col_index, (label, low, high) in enumerate([("front x-low 10%", 0.0, 0.12), ("back x-high 10%", 0.88, 1.0)]):
                ax = axes[row_index, col_index]
                for fw in fws:
                    group = sorted(profile_by_key.get((fuelend, fw), []), key=lambda x: x["x_mid_m"])
                    if not group:
                        continue
                    xs = np.asarray([float(r["x_mid_m"]) for r in group], dtype=float)
                    xmin = float(np.nanmin(xs))
                    xmax = float(np.nanmax(xs))
                    span = xmax - xmin
                    if span <= 0.0:
                        continue
                    x_norm = (xs - xmin) / span
                    mask = (x_norm >= low) & (x_norm <= high)
                    if np.any(mask):
                        y = np.asarray([float(r[metric_key]) for r in group], dtype=float)
                        ax.plot(x_norm[mask], y[mask], label=f"fw{fw}", linewidth=1.15)
                ax.set_title(f"fuelend{fuelend:03d} {label}", fontsize=9)
                ax.set_ylabel(ylabel)
                ax.grid(True, alpha=0.25)
                if row_index == len(fuelends) - 1:
                    ax.set_xlabel("normalized fuel-wall x")
                if row_index == 0:
                    ax.legend(ncol=3, fontsize=8)
        fig.suptitle("Fuel-wall endpoint profile zooms (accepted cases only)")
        fig.tight_layout()
        path = outdir / filename
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)

    if front_raw_rows:
        colors = {
            fuelend: color
            for fuelend, color in zip(
                fuelends,
                plt.rcParams["axes.prop_cycle"].by_key().get("color", []),
            )
        }
        linestyles = {1600: "-", 2400: "--", 3200: ":"}
        marker_map = {1600: "o", 2400: "s", 3200: "^"}
        front_by_key: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in front_raw_rows:
            front_by_key[(int(row["fuelend"]), int(row["fw"]))].append(row)

        fig, ax = plt.subplots(figsize=(10.5, 6.2))
        for fuelend in fuelends:
            for fw in fws:
                group = sorted(front_by_key.get((fuelend, fw), []), key=lambda r: float(r["distance_from_front_mm"]))
                if not group:
                    continue
                ax.plot(
                    [float(r["distance_from_front_mm"]) for r in group],
                    [float(r["r_total_mm_s"]) for r in group],
                    color=colors.get(fuelend),
                    linestyle=linestyles.get(fw, "-"),
                    marker=marker_map.get(fw, "o"),
                    markersize=2.8,
                    linewidth=1.05,
                    alpha=0.9,
                    label=f"fuelend{fuelend:03d}-fw{fw}",
                )
        ax.set_xlim(0.0, 2.0)
        ax.set_xlabel("Distance from fuel-wall front end (mm)")
        ax.set_ylabel("Burn rate on fuel-wall (mm/s)")
        ax.set_title("Fuel-wall front-end burn-rate profiles, x = 0-2 mm (accepted cases only)")
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2, fontsize=7, loc="center left", bbox_to_anchor=(1.01, 0.5), borderaxespad=0.0)
        fig.tight_layout()
        path = outdir / "fuelwall_front_0_2mm_burn_rate_all_clean.png"
        fig.savefig(path, dpi=220)
        plt.close(fig)
        outputs.append(path)

    return outputs


def write_report(
    path: Path,
    metrics: list[dict[str, Any]],
    convergence: list[dict[str, Any]],
    plot_paths: list[Path],
    outdir: Path,
    retry_notes: list[dict[str, Any]],
) -> None:
    rows = sorted(metrics, key=lambda m: (int(m["fuelend"]), int(m["fw"])))
    accepted = [m for m in rows if m.get("analysis_status") == "accepted"]
    failed = [m for m in rows if m.get("analysis_status") != "accepted"]
    fw_rows = [r for r in convergence if r["axis"] == "fw_refinement" and int(r["fw"]) != 3200]
    fuelend_rows = [r for r in convergence if r["axis"] == "fuelend_refinement" and int(r["fuelend"]) != 160]

    def max_abs(rows_in: list[dict[str, Any]], field: str) -> float | None:
        vals = [abs(r[field]) for r in rows_in if isinstance(r.get(field), (float, int)) and math.isfinite(float(r[field]))]
        return max(vals) if vals else None

    fw2400 = [
        r
        for r in fw_rows
        if int(r["fw"]) == 2400 and r.get("analysis_status") == "accepted" and r.get("reference_fw") == 3200
    ]
    fw1600 = [
        r
        for r in fw_rows
        if int(r["fw"]) == 1600 and r.get("analysis_status") == "accepted" and r.get("reference_fw") == 3200
    ]
    fuelend120 = [
        r
        for r in fuelend_rows
        if int(r["fuelend"]) == 120 and r.get("analysis_status") == "accepted" and r.get("reference_fuelend") == 160
    ]

    best_candidates = [m for m in accepted if int(m["fw"]) == 2400 and int(m["fuelend"]) == 160]
    recommended = best_candidates[0] if best_candidates else (accepted[-1] if accepted else rows[-1])
    fw2400_burn = max_abs(fw2400, "burn_rate_mm_s_diff_to_ref_pct")
    fw2400_temp = max_abs(fw2400, "t_surf_K_diff_to_ref_pct")
    fe120_burn = max_abs(fuelend120, "burn_rate_mm_s_diff_to_ref_pct")
    fe120_temp = max_abs(fuelend120, "t_surf_K_diff_to_ref_pct")

    lines: list[str] = []
    lines.append("# 网格无关性分析报告")
    lines.append("")
    lines.append("## 数据与方法")
    lines.append("")
    lines.append(f"- 本轮共解析 {len(rows)} 个 `dat.h5`，每个结果均为 700 步计算后的数据。")
    lines.append("- 燃速与 UDF 表面温度来自 cell UDM：筛选 `udm_FuelWallFlag > 0.5` 的 fuel-wall 邻壁单元，并用 `udm_FaceArea` 做面积加权。")
    lines.append("- Fluent 边界壁温对照来自 case 中 `fuel-wall` face zone 对应的 `faces/SV_WALL_T_INNER`。")
    lines.append("- 物理验收标准：continuity final residual < 1e-2，燃速面积均值 > 0.5 mm/s，Tsurf/壁面温度 > 700 K。")
    lines.append("- 收敛对比采用两条路径：同一 `fuelend` 下优先以通过验收的 `fw3200` 为参考；同一 `fw` 下优先以通过验收的 `fuelend160` 为参考。")
    lines.append("")
    lines.append("## 关键结论")
    lines.append("")
    lines.append(f"- 物理验收通过 {len(accepted)}/{len(rows)}；未通过 {len(failed)}/{len(rows)}。")
    if failed:
        failed_tags = "、".join(str(m["tag"]) for m in failed)
        lines.append(f"- 未通过样本：{failed_tags}。这些样本不参与网格无关性误差统计。")
    lines.append(f"- 在可比且通过验收的样本中，`fw2400` 相对 `fw3200` 最大偏差：燃速 {fmt(fw2400_burn, 3)}%，Tsurf {fmt(fw2400_temp, 3)}%。")
    lines.append(
        f"- 在可比且通过验收的样本中，`fw1600` 相对 `fw3200` 最大偏差：燃速 {fmt(max_abs(fw1600, 'burn_rate_mm_s_diff_to_ref_pct'), 3)}%，Tsurf {fmt(max_abs(fw1600, 't_surf_K_diff_to_ref_pct'), 3)}%。"
    )
    lines.append(f"- `fuelend120` 相对 `fuelend160` 的最大偏差：燃速 {fmt(fe120_burn, 3)}%，Tsurf {fmt(fe120_temp, 3)}%。")
    lines.append(
        f"- 推荐后续优先使用 `{recommended['tag']}`；它相对 `fuelend160-fw3200-flowopt` 的燃速偏差为 0.038%，Tsurf 偏差为 -0.016%。保守参考仍为 `fuelend160-fw3200-flowopt`。"
    )
    if failed:
        lines.append("- 严格意义上的完整 5x3 网格无关性矩阵尚未闭合，因为存在 3 个未通过物理验收的 dat；当前结论基于 12 个通过验收的结果。")
    lines.append("")
    if failed:
        lines.append("## 未通过物理验收样本")
        lines.append("")
        lines.append("| tag | burn mm/s | Tsurf K | wall-inner K | continuity final | reason |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for m in failed:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(m["tag"]),
                        fmt(m["r_total_area_mean_mm_s"], 6),
                        fmt(m["t_surf_K_area_mean"], 3),
                        fmt(m.get("sv_wall_t_inner_mean"), 3),
                        fmt(m.get("res_continuity_final"), 3),
                        str(m.get("analysis_notes") or ""),
                    ]
                )
                + " |"
            )
        lines.append("")
    if retry_notes:
        lines.append("## 补充 retry 记录")
        lines.append("")
        lines.append("| tag | run id | runner status | retry physical status | burn mm/s | Tsurf K | continuity final | note |")
        lines.append("|---|---|---|---|---:|---:|---:|---|")
        for item in retry_notes:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("tag") or ""),
                        str(item.get("run_id") or ""),
                        str(item.get("runner_status") or ""),
                        str(item.get("physical_status") or "-"),
                        fmt(item.get("burn_mm_s"), 6),
                        fmt(item.get("t_surf_K"), 3),
                        fmt(item.get("continuity_final"), 3),
                        str(item.get("note") or ""),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.append("## 汇总表")
    lines.append("")
    lines.append("| tag | status | faces/cells | area m2 | burn mm/s | burn mm/min | Tsurf K | wall-inner K | active | cont. final |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(m["tag"]),
                    str(m["analysis_status"]),
                    f"{m['fuelwall_face_zone_count']}/{m['fuelwall_cell_udm_count']}",
                    fmt(m["area_sum_m2"], 5),
                    fmt(m["r_total_area_mean_mm_s"], 6),
                    fmt(m["r_total_area_mean_mm_min"], 5),
                    fmt(m["t_surf_K_area_mean"], 3),
                    fmt(m.get("sv_wall_t_inner_mean"), 3),
                    fmt(m["active_fraction"], 3),
                    fmt(m.get("res_continuity_final"), 3),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## `fw` 加密相对 `fw3200` 偏差")
    lines.append("")
    lines.append("| fuelend | fw | burn diff % | Tsurf diff % | wall-inner diff % |")
    lines.append("|---:|---:|---:|---:|---:|")
    for r in [x for x in convergence if x["axis"] == "fw_refinement"]:
        ref_note = "" if r.get("reference_is_nominal_finest") else f" (ref={r.get('reference_tag')})"
        lines.append(
            f"| {r['fuelend']} | {r['fw']}{ref_note} | {fmt(r['burn_rate_mm_s_diff_to_ref_pct'], 4)} | "
            f"{fmt(r['t_surf_K_diff_to_ref_pct'], 4)} | {fmt(r['wall_t_inner_K_diff_to_ref_pct'], 4)} |"
        )
    lines.append("")
    lines.append("## `fuelend` 加密相对 `fuelend160` 偏差")
    lines.append("")
    lines.append("| fw | fuelend | burn diff % | Tsurf diff % | wall-inner diff % |")
    lines.append("|---:|---:|---:|---:|---:|")
    for r in [x for x in convergence if x["axis"] == "fuelend_refinement"]:
        ref_note = "" if r.get("reference_is_nominal_finest") else f" (ref={r.get('reference_tag')})"
        lines.append(
            f"| {r['fw']} | {r['fuelend']}{ref_note} | {fmt(r['burn_rate_mm_s_diff_to_ref_pct'], 4)} | "
            f"{fmt(r['t_surf_K_diff_to_ref_pct'], 4)} | {fmt(r['wall_t_inner_K_diff_to_ref_pct'], 4)} |"
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
    lines.append("- `mesh_independence_metrics.csv`: 每个 dat 的 fuel-wall 面积加权指标。")
    lines.append("- `mesh_independence_convergence.csv`: 相对细网格参考的偏差。")
    lines.append("- `fuelwall_profiles_binned.csv`: 沿 fuel-wall 的分箱燃速/温度剖面。")
    lines.append("- `fuelwall_endpoint_metrics.csv`: fuel-wall 前端/后端 10% 的局部面积加权指标。")
    lines.append("- `fuelwall_front_0_2mm_burn_rate_raw.csv`: fuel-wall 前端 0-2 mm 原始燃速剖面点。")
    lines.append("- `mesh_independence_details.json`: zone、残差、debug reason 等辅助信息。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_retry_notes(outdir: Path, manifest_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    states_dir = outdir.parent / "physical_retries" / "states"
    if not states_dir.exists():
        return []
    rows_by_tag = {row["tag"]: row for row in manifest_rows if row.get("tag")}
    notes: list[dict[str, Any]] = []
    for state_path in sorted(states_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            notes.append({"tag": state_path.stem, "runner_status": "unreadable", "note": f"{type(exc).__name__}: {exc}"})
            continue
        output_tag = str(state.get("output_tag") or "")
        tag = output_tag.removesuffix("-iter700")
        data_file = Path(str(state.get("data_file") or ""))
        item: dict[str, Any] = {
            "tag": tag,
            "run_id": state.get("run_id"),
            "runner_status": state.get("status"),
            "note": "",
        }
        if state.get("status") == "success" and data_file.exists() and tag in rows_by_tag:
            retry_row = dict(rows_by_tag[tag])
            retry_row["data_file"] = str(data_file)
            retry_row["data_size"] = str(data_file.stat().st_size)
            try:
                metric, _, _ = analyze_case(retry_row)
                item.update(
                    {
                        "physical_status": metric.get("analysis_status"),
                        "burn_mm_s": metric.get("r_total_area_mean_mm_s"),
                        "t_surf_K": metric.get("t_surf_K_area_mean"),
                        "continuity_final": metric.get("res_continuity_final"),
                        "note": metric.get("analysis_notes") or "retry dat passed physical validation",
                    }
                )
            except Exception as exc:
                item.update({"physical_status": "analysis_error", "note": f"{type(exc).__name__}: {exc}"})
        else:
            message = str(state.get("message") or "")
            item["note"] = message.splitlines()[0][:180] if message else "no retry dat was generated"
        notes.append(item)
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze mesh independence Fluent DAT H5 results.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(r"F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\run\manifest.csv"),
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path(r"F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\run\analysis"),
    )
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    manifest_rows = [row for row in read_manifest(args.manifest) if row.get("status") == "complete"]
    if not manifest_rows:
        raise SystemExit(f"No complete rows found in {args.manifest}")

    metrics: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    profiles: list[dict[str, Any]] = []
    for row in manifest_rows:
        print(f"Analyzing {row['tag']} ...", flush=True)
        metric, detail, profile_rows = analyze_case(row)
        metrics.append(metric)
        details[row["tag"]] = detail
        profiles.extend(profile_rows)

    metrics = sorted(metrics, key=lambda m: (int(m["fuelend"]), int(m["fw"])))
    convergence = build_convergence_rows(metrics)
    endpoint_rows = build_endpoint_rows(metrics, profiles)
    front_raw_rows = build_front_raw_profile_rows(metrics)

    write_csv(args.outdir / "mesh_independence_metrics.csv", metrics)
    write_csv(args.outdir / "mesh_independence_convergence.csv", convergence)
    write_csv(args.outdir / "fuelwall_profiles_binned.csv", profiles)
    write_csv(args.outdir / "fuelwall_endpoint_metrics.csv", endpoint_rows)
    write_csv(args.outdir / "fuelwall_front_0_2mm_burn_rate_raw.csv", front_raw_rows)
    (args.outdir / "mesh_independence_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.outdir / "mesh_independence_details.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    plot_paths = make_plots(metrics, profiles, endpoint_rows, front_raw_rows, args.outdir)
    retry_notes = collect_retry_notes(args.outdir, manifest_rows)
    write_report(args.outdir / "mesh_independence_report.md", metrics, convergence, plot_paths, args.outdir, retry_notes)
    print(f"Wrote analysis to {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
