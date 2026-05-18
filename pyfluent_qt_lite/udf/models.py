from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_SOLVERS = {"2d", "2ddp", "3d", "3ddp"}
VALID_TARGETS = {"serial", "host", "node"}


@dataclass(slots=True)
class BuildSpec:
    project_dir: Path
    build_root: Path
    source_dir: Path
    c_files: list[Path]
    header_files: list[Path]
    solver: str = "2ddp"
    targets: tuple[str, ...] = ("host", "node")
    parallel_node: str = "auto"
    arch: str = "win64"
    recursive: bool = False
    fresh: bool = True
    dry_run: bool = False
    json_output: bool = False
    fluent_root: Path | None = None
    release_dir: Path | None = None
    vsdevcmd: Path | None = None
    config_path: Path | None = None

    def validate(self) -> None:
        if self.solver not in VALID_SOLVERS:
            raise ValueError(
                f"Unsupported solver '{self.solver}'. Expected one of: {sorted(VALID_SOLVERS)}"
            )
        bad_targets = [target for target in self.targets if target not in VALID_TARGETS]
        if bad_targets:
            raise ValueError(
                f"Unsupported targets: {bad_targets}. Expected any of: {sorted(VALID_TARGETS)}"
            )
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("Duplicate targets are not allowed.")


@dataclass(slots=True)
class ToolchainInfo:
    fluent_root: Path
    release_dir: Path
    makefile_template: Path
    user_template: Path
    ntbin_dir: Path
    vsdevcmd: Path
    node_parallel_mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fluent_root": str(self.fluent_root),
            "release_dir": str(self.release_dir),
            "makefile_template": str(self.makefile_template),
            "user_template": str(self.user_template),
            "ntbin_dir": str(self.ntbin_dir),
            "vsdevcmd": str(self.vsdevcmd),
            "node_parallel_mode": self.node_parallel_mode,
        }


@dataclass(slots=True)
class BuildTargetResult:
    target: str
    version: str
    target_dir: Path
    user_udf_path: Path
    log_path: Path
    command: str
    returncode: int | None
    success: bool
    dll_path: Path | None = None
    error_lines: list[str] = field(default_factory=list)
    warning_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "version": self.version,
            "target_dir": str(self.target_dir),
            "user_udf_path": str(self.user_udf_path),
            "log_path": str(self.log_path),
            "command": self.command,
            "returncode": self.returncode,
            "success": self.success,
            "dll_path": str(self.dll_path) if self.dll_path else None,
            "error_lines": self.error_lines,
            "warning_lines": self.warning_lines,
        }


@dataclass(slots=True)
class BuildSummary:
    ok: bool
    spec: BuildSpec
    toolchain: ToolchainInfo
    source_files: list[Path]
    header_files: list[Path]
    manifest_path: Path | None
    target_results: list[BuildTargetResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "spec": {
                "project_dir": str(self.spec.project_dir),
                "build_root": str(self.spec.build_root),
                "source_dir": str(self.spec.source_dir),
                "c_files": [str(path) for path in self.source_files],
                "header_files": [str(path) for path in self.header_files],
                "solver": self.spec.solver,
                "targets": list(self.spec.targets),
                "parallel_node": self.spec.parallel_node,
                "arch": self.spec.arch,
                "recursive": self.spec.recursive,
                "fresh": self.spec.fresh,
                "dry_run": self.spec.dry_run,
                "json_output": self.spec.json_output,
                "config_path": str(self.spec.config_path) if self.spec.config_path else None,
            },
            "toolchain": self.toolchain.to_dict(),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "target_results": [result.to_dict() for result in self.target_results],
        }
