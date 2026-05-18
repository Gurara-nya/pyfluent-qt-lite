from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .builder import MANIFEST_NAME, build, clean_build_root, discover_toolchain
from .discovery import scan_local_toolchains
from .models import BuildSpec


def _split_targets(value: str | list[str] | None) -> tuple[str, ...]:
    if value is None:
        return ("host", "node")
    if isinstance(value, list):
        items = value
    else:
        items = [item.strip() for item in value.split(",")]
    return tuple(str(item).strip().lower() for item in items if str(item).strip())


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_path(value: str | None, base_dir: Path | None = None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def _resolve_path_list(values: list[str] | None, base_dir: Path | None = None) -> list[Path]:
    if not values:
        return []
    return [path for value in values if (path := _resolve_path(value, base_dir)) is not None]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_spec_from_args(args: argparse.Namespace) -> BuildSpec:
    config_data: dict[str, Any] = {}
    config_path: Path | None = None
    config_base: Path | None = None

    if args.config:
        config_path = Path(args.config).expanduser().resolve()
        config_base = config_path.parent
        config_data = _load_json(config_path)

    def pick(name: str, default: Any = None) -> Any:
        value = getattr(args, name, None)
        if value is None:
            return config_data.get(name, default)
        return value

    project_dir = _resolve_path(pick("project_dir"), config_base) or Path.cwd().resolve()
    source_dir = _resolve_path(pick("source_dir"), config_base) or project_dir
    build_root = _resolve_path(pick("build_root"), config_base) or (project_dir / "libudf")

    return BuildSpec(
        project_dir=project_dir,
        build_root=build_root,
        source_dir=source_dir,
        c_files=_resolve_path_list(pick("c_files", []), config_base),
        header_files=_resolve_path_list(pick("header_files", []), config_base),
        solver=str(pick("solver", os.environ.get("PYFLUENT_LITE_UDF_SOLVER", "2ddp"))),
        targets=_split_targets(pick("targets", os.environ.get("PYFLUENT_LITE_UDF_TARGETS"))),
        parallel_node=str(pick("parallel_node", os.environ.get("PYFLUENT_LITE_UDF_PARALLEL_NODE", "auto"))),
        arch=str(pick("arch", os.environ.get("PYFLUENT_LITE_UDF_ARCH", "win64"))),
        recursive=_coerce_bool(pick("recursive", False), False),
        fresh=_coerce_bool(pick("fresh", True), True),
        dry_run=_coerce_bool(pick("dry_run", False), False),
        json_output=_coerce_bool(pick("json_output", False), False)
        or _coerce_bool(getattr(args, "json_output", False), False),
        fluent_root=_resolve_path(pick("fluent_root", os.environ.get("PYFLUENT_LITE_FLUENT_ROOT")), config_base),
        release_dir=_resolve_path(pick("release_dir", os.environ.get("PYFLUENT_LITE_FLUENT_RELEASE")), config_base),
        vsdevcmd=_resolve_path(pick("vsdevcmd", os.environ.get("PYFLUENT_LITE_VSDEVCMD")), config_base),
        config_path=config_path,
    )


def _print_json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def _render_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"ok: {summary['ok']}")
    lines.append(f"project_dir: {summary['spec']['project_dir']}")
    lines.append(f"build_root: {summary['spec']['build_root']}")
    lines.append(f"solver: {summary['spec']['solver']}")
    lines.append(f"targets: {', '.join(summary['spec']['targets'])}")
    lines.append(f"fluent_root: {summary['toolchain']['fluent_root']}")
    lines.append(f"release_dir: {summary['toolchain']['release_dir']}")
    lines.append(f"vsdevcmd: {summary['toolchain']['vsdevcmd']}")
    if manifest := summary.get("manifest_path"):
        lines.append(f"manifest: {manifest}")

    for result in summary["target_results"]:
        lines.append("")
        lines.append(
            f"[{result['target']}] version={result['version']} "
            f"success={result['success']} returncode={result['returncode']}"
        )
        lines.append(f"target_dir: {result['target_dir']}")
        lines.append(f"log: {result['log_path']}")
        if result.get("dll_path"):
            lines.append(f"dll: {result['dll_path']}")
        if result["error_lines"]:
            lines.append("errors:")
            lines.extend(f"  {line}" for line in result["error_lines"][:10])
        if result["warning_lines"]:
            lines.append("warnings:")
            lines.extend(f"  {line}" for line in result["warning_lines"][:10])
        if result["command"] and summary["spec"]["dry_run"]:
            lines.append(f"command: {result['command']}")
    return "\n".join(lines)


def _cmd_build(args: argparse.Namespace) -> int:
    spec = _build_spec_from_args(args)
    summary = build(spec)
    payload = summary.to_dict()
    if spec.json_output:
        return _print_json(payload)
    print(_render_summary_text(payload))
    return 0 if summary.ok else 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    project_dir = _resolve_path(args.project_dir) or Path.cwd().resolve()
    spec = BuildSpec(
        project_dir=project_dir,
        build_root=_resolve_path(args.build_root) or (project_dir / "libudf"),
        source_dir=_resolve_path(args.source_dir) or project_dir,
        c_files=[],
        header_files=[],
        solver=args.solver,
        targets=("host", "node"),
        parallel_node=args.parallel_node,
        arch=args.arch,
        fluent_root=_resolve_path(args.fluent_root),
        release_dir=_resolve_path(args.release_dir),
        vsdevcmd=_resolve_path(args.vsdevcmd),
    )
    payload = discover_toolchain(spec).to_dict()
    if args.json_output:
        return _print_json(payload)
    for key, value in payload.items():
        print(f"{key}: {value}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    payload = scan_local_toolchains(args.fluent_root, args.release_dir, args.vsdevcmd)
    if args.json_output:
        return _print_json(payload)

    print(f"python: {payload['python_executable']} ({payload['python_version']})")
    print("")
    print("selected:")
    for key, value in payload["selected"].items():
        print(f"  {key}: {value}")
    print("")
    for title, items_key in [
        ("fluent_roots", "fluent_roots"),
        ("release_dirs", "release_dirs"),
        ("vsdevcmd_candidates", "vsdevcmd_candidates"),
    ]:
        print(f"{title}:")
        for item in payload[items_key]:
            detail = f"exists={item.get('exists')}"
            if "has_udf_templates" in item:
                detail += f", has_udf_templates={item.get('has_udf_templates')}"
            print(f"  - {item['path']} | {item['source']} | {detail}")
        print("")

    print("health:")
    print(f"  ready: {payload['health'].get('ready')}")
    for check in payload["health"].get("checks", []):
        print(f"  - {check['name']}: ok={check['ok']} | {check['detail']}")
    for warning in payload["health"].get("warnings", []):
        print(f"  warning: {warning}")
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    project_dir = _resolve_path(args.project_dir) or Path.cwd().resolve()
    build_root = _resolve_path(args.build_root) or (project_dir / "libudf")
    removed = clean_build_root(build_root, args.arch)
    payload = {
        "ok": True,
        "build_root": str(build_root),
        "removed": [str(path) for path in removed],
        "manifest_path": str(build_root / MANIFEST_NAME),
    }
    if args.json_output:
        return _print_json(payload)
    print(f"build_root: {build_root}")
    if removed:
        for path in removed:
            print(f"removed: {path}")
    else:
        print("removed: nothing")
    return 0


def _cmd_init_config(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    project_dir = _resolve_path(args.project_dir) or Path.cwd().resolve()
    source_dir = _resolve_path(args.source_dir) or project_dir
    build_root = _resolve_path(args.build_root) or (project_dir / "libudf")
    payload = {
        "project_dir": str(project_dir),
        "source_dir": str(source_dir),
        "build_root": str(build_root),
        "solver": args.solver,
        "targets": ["host", "node"],
        "parallel_node": "auto",
        "arch": args.arch,
        "recursive": False,
        "fresh": True,
        "dry_run": False,
        "json_output": False,
        "fluent_root": None,
        "release_dir": None,
        "vsdevcmd": None,
        "c_files": [],
        "header_files": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(output)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyfluent-lite-udf",
        description="Compile Fluent UDFs with the official Windows libudf makefile flow.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a UDF project.")
    build_parser.add_argument("--config", help="Path to a JSON config file.")
    build_parser.add_argument("--project-dir")
    build_parser.add_argument("--source-dir")
    build_parser.add_argument("--build-root")
    build_parser.add_argument("--c-files", nargs="*")
    build_parser.add_argument("--header-files", nargs="*")
    build_parser.add_argument("--solver")
    build_parser.add_argument("--targets", help="Comma-separated targets: serial,host,node")
    build_parser.add_argument("--parallel-node")
    build_parser.add_argument("--arch")
    build_parser.add_argument("--fluent-root")
    build_parser.add_argument("--release-dir")
    build_parser.add_argument("--vsdevcmd")
    build_parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None)
    build_parser.add_argument("--fresh", action=argparse.BooleanOptionalAction, default=None)
    build_parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=None)
    build_parser.add_argument("--json-output", action=argparse.BooleanOptionalAction, default=None)
    build_parser.set_defaults(func=_cmd_build)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect selected toolchain.")
    inspect_parser.add_argument("--project-dir")
    inspect_parser.add_argument("--source-dir")
    inspect_parser.add_argument("--build-root")
    inspect_parser.add_argument("--solver", default="2ddp")
    inspect_parser.add_argument("--parallel-node", default="auto")
    inspect_parser.add_argument("--arch", default="win64")
    inspect_parser.add_argument("--fluent-root")
    inspect_parser.add_argument("--release-dir")
    inspect_parser.add_argument("--vsdevcmd")
    inspect_parser.add_argument("--json-output", action="store_true")
    inspect_parser.set_defaults(func=_cmd_inspect)

    scan_parser = subparsers.add_parser("scan", help="Scan local Fluent and Visual Studio toolchains.")
    scan_parser.add_argument("--fluent-root")
    scan_parser.add_argument("--release-dir")
    scan_parser.add_argument("--vsdevcmd")
    scan_parser.add_argument("--json-output", action="store_true")
    scan_parser.set_defaults(func=_cmd_scan)

    clean_parser = subparsers.add_parser("clean", help="Remove managed build artifacts.")
    clean_parser.add_argument("--project-dir")
    clean_parser.add_argument("--build-root")
    clean_parser.add_argument("--arch", default="win64")
    clean_parser.add_argument("--json-output", action="store_true")
    clean_parser.set_defaults(func=_cmd_clean)

    init_parser = subparsers.add_parser("init-config", help="Write a starter JSON config file.")
    init_parser.add_argument("--output", required=True)
    init_parser.add_argument("--project-dir")
    init_parser.add_argument("--source-dir")
    init_parser.add_argument("--build-root")
    init_parser.add_argument("--solver", default="2ddp")
    init_parser.add_argument("--arch", default="win64")
    init_parser.set_defaults(func=_cmd_init_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        message = {"ok": False, "error": str(exc)}
        if getattr(args, "json_output", False):
            _print_json(message)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
