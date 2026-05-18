from __future__ import annotations

import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _check_existing_dir(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path.resolve()


def _check_existing_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path.resolve()


def _version_key(path: Path) -> tuple[int, ...]:
    match = re.search(r"fluent(\d+(?:\.\d+)*)", path.name.lower())
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def _stable_unique_candidates(items: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    unique: list[tuple[Path, str]] = []
    for path, source in items:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        duplicate = False
        for existing_path, _ in unique:
            if resolved == existing_path:
                duplicate = True
                break
            try:
                if resolved.exists() and existing_path.exists() and resolved.samefile(existing_path):
                    duplicate = True
                    break
            except OSError:
                pass
        if not duplicate:
            unique.append((resolved, source))
    return unique


def _scan_awp_roots() -> list[tuple[Path, str]]:
    matches: list[tuple[int, str, str]] = []
    for key, value in os.environ.items():
        match = re.fullmatch(r"AWP_ROOT(\d+)", key)
        if match and value:
            matches.append((int(match.group(1)), key, value))
    return [(Path(value) / "fluent", f"env:{key}") for _, key, value in sorted(matches, reverse=True)]


def _scan_common_fluent_roots() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    base_values = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        r"C:\ANSYS Inc",
        r"D:\ANSYS Inc",
        r"F:\ANSYS Inc",
    ]
    for raw_base in base_values:
        if not raw_base:
            continue
        base = Path(raw_base)
        if base.name.lower() != "ansys inc":
            base = base / "ANSYS Inc"
        if not base.is_dir():
            continue
        direct = base / "fluent"
        if direct.is_dir():
            candidates.append((direct, f"default:{base}"))
        for child in base.iterdir():
            if not child.is_dir():
                continue
            fluent_dir = child / "fluent"
            if fluent_dir.is_dir():
                candidates.append((fluent_dir, f"default:{child}"))
    return candidates


def scan_fluent_root_candidates(override: str | None = None) -> list[dict[str, str | bool]]:
    candidates: list[tuple[Path, str]] = []
    if override:
        candidates.append((Path(override), "override"))

    app_override = os.environ.get("PYFLUENT_LITE_FLUENT_ROOT")
    if app_override:
        candidates.append((Path(app_override), "env:PYFLUENT_LITE_FLUENT_ROOT"))

    fluent_inc = os.environ.get("FLUENT_INC")
    if fluent_inc:
        candidates.append((Path(fluent_inc), "env:FLUENT_INC"))

    candidates.extend(_scan_awp_roots())

    for env_key, env_value in os.environ.items():
        if re.fullmatch(r"ANSYS\d+_DIR", env_key) and env_value:
            candidates.append((Path(env_value).parent / "fluent", f"env:{env_key}"))

    candidates.extend(_scan_common_fluent_roots())

    return [
        {
            "path": str(path),
            "source": source,
            "exists": path.is_dir(),
        }
        for path, source in _stable_unique_candidates(candidates)
    ]


def scan_release_candidates(fluent_root: Path | str | None = None) -> list[dict[str, str | bool]]:
    roots: list[Path] = []
    if fluent_root:
        roots.append(Path(fluent_root))
    else:
        for item in scan_fluent_root_candidates():
            if item["exists"]:
                roots.append(Path(str(item["path"])))

    candidates: list[tuple[Path, str]] = []
    for root in roots:
        try:
            resolved_root = root.expanduser().resolve()
        except OSError:
            continue
        if not resolved_root.is_dir():
            continue
        for child in resolved_root.iterdir():
            has_templates = (child / "src" / "udf" / "makefile_nt.udf").is_file()
            if child.is_dir() and (child.name.lower().startswith("fluent") or has_templates):
                candidates.append((child, f"release-under:{resolved_root}"))

    results: list[dict[str, str | bool]] = []
    for path, source in sorted(
        _stable_unique_candidates(candidates),
        key=lambda item: _version_key(item[0]),
        reverse=True,
    ):
        results.append(
            {
                "path": str(path),
                "source": source,
                "exists": path.is_dir(),
                "has_udf_templates": (path / "src" / "udf" / "makefile_nt.udf").is_file(),
            }
        )
    return results


def _vswhere_candidates() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if vswhere.is_file():
        try:
            result = subprocess.run(
                [
                    str(vswhere),
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-format",
                    "value",
                    "-property",
                    "installationPath",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            for install_path in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
                candidates.append((Path(install_path) / "Common7" / "Tools" / "VsDevCmd.bat", "vswhere"))
        except OSError:
            pass
    return candidates


def _python_package_item(package_name: str) -> dict[str, str | bool]:
    try:
        version = importlib.metadata.version(package_name)
        metadata_path = importlib.metadata.distribution(package_name).locate_file("")
        return {
            "name": package_name,
            "path": str(Path(metadata_path).resolve()),
            "source": "python-package",
            "exists": True,
            "detail": f"version {version}",
        }
    except importlib.metadata.PackageNotFoundError:
        return {
            "name": package_name,
            "path": "",
            "source": "python-package",
            "exists": False,
            "detail": "not installed",
        }


def scan_related_tools() -> list[dict[str, str | bool]]:
    python_path = Path(sys.executable).resolve()
    items: list[dict[str, str | bool]] = [
        {
            "name": "python",
            "path": str(python_path),
            "source": "sys.executable",
            "exists": python_path.is_file(),
            "detail": f"version {sys.version.split()[0]}",
        },
        _python_package_item("PySide6"),
    ]

    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    items.append(
        {
            "name": "vswhere",
            "path": str(vswhere),
            "source": "default",
            "exists": vswhere.is_file(),
            "detail": "Visual Studio locator",
        }
    )

    for tool_name in ("cmake", "nmake"):
        command_path = shutil.which(tool_name)
        path = Path(command_path).resolve() if command_path else None
        items.append(
            {
                "name": tool_name,
                "path": str(path) if path else "",
                "source": "PATH",
                "exists": bool(path and path.is_file()),
                "detail": "available in current shell" if path else "not in current shell PATH",
            }
        )

    return items


def _scan_release_metadata(release_dir: Path, fluent_root: Path | None = None) -> dict[str, object]:
    makefile_template = release_dir / "src" / "udf" / "makefile_nt.udf"
    user_template = release_dir / "src" / "udf" / "user_nt.udf"
    parallel_modes: dict[str, list[str]] = {}
    for solver in ("2d", "2ddp", "3d", "3ddp"):
        node_dir = release_dir / "win64" / f"{solver}_node"
        if not node_dir.is_dir():
            continue
        names = {path.name.lower() for path in node_dir.iterdir() if path.is_file()}
        modes: list[str] = []
        if any(name.startswith("fl_net") and name.endswith(".lib") for name in names):
            modes.append("net")
        if any(name.startswith("fl_mpi") and name.endswith(".lib") for name in names):
            modes.append("mpi")
        parallel_modes[solver] = modes

    ntbin_dir = (fluent_root / "ntbin" / "win64") if fluent_root else None
    return {
        "makefile_template": str(makefile_template) if makefile_template.is_file() else None,
        "user_template": str(user_template) if user_template.is_file() else None,
        "ntbin_dir": str(ntbin_dir) if ntbin_dir and ntbin_dir.is_dir() else None,
        "parallel_modes": parallel_modes,
    }


def _health_report(
    selected_fluent_root: str | None,
    selected_release: str | None,
    selected_vsdevcmd: str | None,
    release_metadata: dict[str, object],
    related_tools: list[dict[str, str | bool]],
) -> dict[str, object]:
    checks: list[dict[str, object]] = [
        {
            "name": "Fluent root",
            "ok": bool(selected_fluent_root),
            "detail": selected_fluent_root or "not found",
        },
        {
            "name": "Fluent release",
            "ok": bool(selected_release),
            "detail": selected_release or "not found",
        },
        {
            "name": "UDF templates",
            "ok": bool(release_metadata.get("makefile_template") and release_metadata.get("user_template")),
            "detail": "makefile_nt.udf + user_nt.udf"
            if release_metadata.get("makefile_template") and release_metadata.get("user_template")
            else "missing template files",
        },
        {
            "name": "VsDevCmd",
            "ok": bool(selected_vsdevcmd),
            "detail": selected_vsdevcmd or "not found",
        },
    ]
    checks.extend(
        {
            "name": str(item["name"]),
            "ok": bool(item["exists"]),
            "detail": item.get("detail", ""),
        }
        for item in related_tools
        if item["name"] in {"python", "PySide6"}
    )

    missing = [check["name"] for check in checks if not check["ok"]]
    warnings: list[str] = []
    if not selected_vsdevcmd:
        warnings.append("Visual Studio Build Tools environment was not located.")
    if not release_metadata.get("parallel_modes"):
        warnings.append("No Fluent node library modes were detected under the selected release.")
    if not any(item["name"] == "nmake" and item["exists"] for item in related_tools):
        warnings.append("nmake is not visible in the current shell, but VsDevCmd can still provision it during build.")

    return {
        "ready": not missing,
        "missing": missing,
        "warnings": warnings,
        "checks": checks,
    }


def scan_vsdevcmd_candidates(override: str | None = None) -> list[dict[str, str | bool]]:
    candidates: list[tuple[Path, str]] = []

    if override:
        candidates.append((Path(override), "override"))

    app_override = os.environ.get("PYFLUENT_LITE_VSDEVCMD")
    if app_override:
        candidates.append((Path(app_override), "env:PYFLUENT_LITE_VSDEVCMD"))

    env_value = os.environ.get("VSDEVCMD")
    if env_value:
        candidates.append((Path(env_value), "env:VSDEVCMD"))

    candidates.extend(_vswhere_candidates())
    candidates.extend(
        [
            (
                Path(r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"),
                "default:vs2022-buildtools",
            ),
            (
                Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"),
                "default:vs2022-community",
            ),
            (
                Path(r"C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\VsDevCmd.bat"),
                "default:vs2022-professional",
            ),
            (
                Path(r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat"),
                "default:vs2022-enterprise",
            ),
            (
                Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\Common7\Tools\VsDevCmd.bat"),
                "default:vs2019-buildtools",
            ),
            (
                Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\Common7\Tools\VsDevCmd.bat"),
                "default:vs2019-community",
            ),
            (
                Path(r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\Tools\VsDevCmd.bat"),
                "default:vs18-buildtools",
            ),
            (
                Path(r"C:\Program Files (x86)\Microsoft Visual Studio\17\BuildTools\Common7\Tools\VsDevCmd.bat"),
                "default:vs17-buildtools",
            ),
        ]
    )

    return [
        {
            "path": str(path),
            "source": source,
            "exists": path.is_file(),
        }
        for path, source in _stable_unique_candidates(candidates)
    ]


def scan_local_toolchains(
    fluent_override: str | None = None,
    release_override: str | None = None,
    vsdevcmd_override: str | None = None,
) -> dict[str, object]:
    fluent_override = fluent_override or os.environ.get("PYFLUENT_LITE_FLUENT_ROOT")
    release_override = release_override or os.environ.get("PYFLUENT_LITE_FLUENT_RELEASE")
    vsdevcmd_override = vsdevcmd_override or os.environ.get("PYFLUENT_LITE_VSDEVCMD")
    fluent_roots = scan_fluent_root_candidates(fluent_override)
    if release_override:
        explicit_release = Path(release_override).expanduser().resolve()
        release_candidates = [
            {
                "path": str(explicit_release),
                "source": "override",
                "exists": explicit_release.is_dir(),
                "has_udf_templates": (explicit_release / "src" / "udf" / "makefile_nt.udf").is_file(),
            }
        ]
        release_candidates.extend(
            item
            for item in scan_release_candidates(explicit_release.parent)
            if str(item["path"]) != str(explicit_release)
        )
    else:
        release_candidates = scan_release_candidates(None)
    vsdevcmd_candidates = scan_vsdevcmd_candidates(vsdevcmd_override)
    related_tools = scan_related_tools()

    selected_fluent_root = next((item["path"] for item in fluent_roots if item["exists"]), None)
    selected_release = next((item["path"] for item in release_candidates if item.get("has_udf_templates")), None)
    selected_vsdevcmd = next((item["path"] for item in vsdevcmd_candidates if item["exists"]), None)
    release_metadata = (
        _scan_release_metadata(Path(selected_release), Path(selected_fluent_root))
        if selected_release and selected_fluent_root
        else {
            "makefile_template": None,
            "user_template": None,
            "ntbin_dir": None,
            "parallel_modes": {},
        }
    )
    node_parallel_mode = None
    if selected_release:
        try:
            node_parallel_mode = detect_parallel_node(Path(selected_release), "win64", "2ddp", "auto")
        except OSError:
            node_parallel_mode = None
    health = _health_report(
        selected_fluent_root,
        selected_release,
        selected_vsdevcmd,
        release_metadata,
        related_tools,
    )

    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "fluent_roots": fluent_roots,
        "release_dirs": release_candidates,
        "vsdevcmd_candidates": vsdevcmd_candidates,
        "related_tools": related_tools,
        "health": health,
        "selected": {
            "fluent_root": selected_fluent_root,
            "release_dir": selected_release,
            "vsdevcmd": selected_vsdevcmd,
            "makefile_template": release_metadata.get("makefile_template"),
            "user_template": release_metadata.get("user_template"),
            "ntbin_dir": release_metadata.get("ntbin_dir"),
            "parallel_modes": release_metadata.get("parallel_modes"),
            "node_parallel_mode": node_parallel_mode,
        },
    }


def find_fluent_root(override: str | None = None) -> Path:
    for item in scan_fluent_root_candidates(override):
        if item["exists"]:
            return Path(str(item["path"]))

    raise FileNotFoundError(
        "Unable to discover Fluent root. Pass --fluent-root or define FLUENT_INC / AWP_ROOT###."
    )


def find_release_dir(fluent_root: Path, override: str | None = None) -> Path:
    override = override or os.environ.get("PYFLUENT_LITE_FLUENT_RELEASE")
    if override:
        candidate = Path(override).expanduser()
        candidate = _check_existing_dir(candidate, "Fluent release directory")
        if not (candidate / "src" / "udf" / "makefile_nt.udf").is_file():
            raise FileNotFoundError(
                f"Fluent release directory does not contain src/udf/makefile_nt.udf: {candidate}"
            )
        return candidate

    candidates = [
        Path(str(item["path"]))
        for item in scan_release_candidates(fluent_root)
        if item.get("has_udf_templates")
    ]
    if not candidates:
        raise FileNotFoundError(f"No Fluent release directory with src/udf templates found under: {fluent_root}")

    return sorted(candidates, key=_version_key, reverse=True)[0].resolve()


def find_template_paths(release_dir: Path) -> tuple[Path, Path]:
    udf_dir = release_dir / "src" / "udf"
    makefile_template = _check_existing_file(udf_dir / "makefile_nt.udf", "Fluent makefile template")
    user_template = _check_existing_file(udf_dir / "user_nt.udf", "Fluent user_nt.udf template")
    return makefile_template, user_template


def find_ntbin_dir(fluent_root: Path, arch: str) -> Path:
    return _check_existing_dir(fluent_root / "ntbin" / arch, "Fluent ntbin directory")


def find_vsdevcmd(override: str | None = None) -> Path:
    for item in scan_vsdevcmd_candidates(override):
        if item["exists"]:
            return Path(str(item["path"]))

    raise FileNotFoundError("Unable to discover VsDevCmd.bat. Pass --vsdevcmd explicitly.")


def detect_parallel_node(release_dir: Path, arch: str, solver: str, explicit_value: str) -> str:
    if explicit_value and explicit_value.lower() != "auto":
        value = explicit_value.lower()
        if value not in {"none", "net", "mpi", "smpi", "vmpi", "nmpi"}:
            raise ValueError(f"Unsupported PARALLEL_NODE value: {explicit_value}")
        return value

    node_dir = release_dir / arch / f"{solver}_node"
    if node_dir.is_dir():
        libs = {path.name.lower() for path in node_dir.iterdir() if path.is_file()}
        if any(name.startswith("fl_net") and name.endswith(".lib") for name in libs):
            return "net"
        if any(name.startswith("fl_mpi") and name.endswith(".lib") for name in libs):
            return "mpi"

    return "mpi"
