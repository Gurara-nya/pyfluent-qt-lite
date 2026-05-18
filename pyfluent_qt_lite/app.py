from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import traceback
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QFontDatabase,
    QPixmap,
    QShowEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyleFactory,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .udf.builder import build_with_callback
from .udf.models import BuildSpec


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOL_ROOT.parent
APP_NAME = "PyFluent Lite"
APP_VERSION = __version__
APP_AUTHOR = "LLG"
APP_GITHUB_URL = "https://github.com/LLG-P/pyfluent-lite"
DEFAULT_WORK_DIR = REPO_ROOT / "workspace"
DEFAULT_UDF_TARGETS = ("host", "node")
HISTORY_LIMIT = 12
CONSOLE_FLUSH_MS = 80
CONSOLE_FORCE_FLUSH_CHARS = 160_000
CONSOLE_FLUSH_CHUNK_CHARS = 90_000
CONSOLE_BUFFER_HARD_LIMIT = 1_000_000
CONSOLE_MAX_BLOCKS = 50_000
TRANSCRIPT_LOG_MAX_BYTES = 80 * 1024 * 1024
UI_CONTROL_HEIGHT = 36
UI_TOOL_BUTTON_SIZE = QSize(38, 36)
UI_ICON_SIZE = QSize(16, 16)
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
USER32: Any | None = None
if sys.platform.startswith("win"):
    try:
        USER32 = ctypes.WinDLL("user32", use_last_error=True)
        USER32.SetWindowPos.argtypes = (
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        )
        USER32.SetWindowPos.restype = wintypes.BOOL
    except OSError:
        USER32 = None
DEFAULT_COMMAND_PRESETS = [
    "/mesh/check",
    "/solve/initialize/hyb-initialization",
    "/solve/initialize/initialize-flow",
    "/solve/iterate 100",
    '/define/user-defined/execute-on-demand "Vari_Sources::libudf"',
    '(load "script.scm")',
    '/define/user-defined/compiled-functions load "libudf"',
    '/file/write-case-data "case-data.cas.h5"',
]
DEFAULT_PYFLUENT_PRESETS = [
    "solver.tui.mesh.check()",
    'solver.settings.solution.initialization.compute_defaults(from_zone_type="mass-flow-inlet", from_zone_name="inlet", phase="mixture")',
    "solver.settings.solution.initialization.standard_initialize()",
    'solver.tui.define.user_defined.execute_on_demand("Vari_Sources::libudf")',
    "solver.tui.solve.iterate(100)",
]
DEFAULT_COMMAND_BUTTONS = [
    {"name": "检查网格", "mode": "tui", "command": "/mesh/check"},
    {"name": "混合初始化", "mode": "tui", "command": "/solve/initialize/hyb-initialization"},
    {"name": "标准初始化", "mode": "tui", "command": "/solve/initialize/initialize-flow"},
    {"name": "计算 100 步", "mode": "tui", "command": "/solve/iterate 100"},
    {
        "name": "保存 Case/Data",
        "mode": "tui",
        "command": '/file/write-case-data "case-data.cas.h5"',
    },
    {"name": "Py 计算 100 步", "mode": "python", "command": "solver.tui.solve.iterate(100)"},
]
DEFAULT_PLOT_BUTTONS = [
    {
        "name": "后处理 API 速查",
        "code": '''# PyFluent 后处理常用入口
# solver/session/fluent 指向当前 Fluent solver session
# run_tui("/display/...")      执行 TUI 命令
# save_picture(path)           保存当前 Fluent 图形窗口
# post_path("name.png")        生成后处理输出路径
# refresh_post()               脚本结束后刷新后处理图片列表
# show_image(path)             弹出一个独立图片窗口

try:
    results = solver.settings.results
except Exception:
    results = solver.results

print("results root:", results)
print("graphics:", results.graphics)
print("plot:", results.plot)
print("report:", results.report)

print("\\n常用对象:")
for label, obj in [
    ("contour", results.graphics.contour),
    ("vector", results.graphics.vector),
    ("pathline", results.graphics.pathline),
    ("particle_track", results.graphics.particle_track),
    ("xy_plot", results.plot.xy_plot),
]:
    print(label, "->", obj)
    try:
        print("  existing:", obj.get_object_names())
    except Exception as err:
        print("  list failed:", type(err).__name__, err)
''',
    },
    {
        "name": "XY 图：变量沿面/线",
        "code": '''# XY Plot 模板：把 surfaces 和 field 改成你的边界/线面和变量
# 常见 field 示例：pressure, velocity-magnitude, temperature, wall-shear
name = "xy-pressure"
surfaces = ["wall"]          # 改成 line/rake/boundary surface 名称
y_field = "pressure"
x_field = "x-coordinate"     # 可试 x-coordinate/y-coordinate/curve-length

try:
    results = solver.settings.results
except Exception:
    results = solver.results

xy_collection = results.plot.xy_plot
try:
    if name in xy_collection.list():
        xy_collection.delete(name)
except Exception:
    pass

xy_collection[name] = {}
xy = xy_collection[name]
xy.surfaces_list = surfaces

# 新版本常用直接字段；部分版本也支持 x_axis_data/y_axis_data。
for setter in (
    lambda: setattr(xy, "y_axis_function", y_field),
    lambda: setattr(xy, "x_axis_function", x_field),
    lambda: setattr(xy.y_axis_data, "y_axis_function", y_field),
    lambda: setattr(xy.x_axis_data, "x_axis_function", x_field),
):
    try:
        setter()
    except Exception as err:
        print("skip:", type(err).__name__, err)

try:
    xy.display()
except Exception as err:
    print("display failed:", type(err).__name__, err)

data_file = post_path(f"{name}.xy")
data_name = str(data_file).replace("\\\\", "/")
write_errors = []
for label, write_call in [
    ("filename", lambda: xy.write_to_file(filename=data_name)),
    ("file_name", lambda: xy.write_to_file(file_name=data_name)),
    ("positional", lambda: xy.write_to_file(data_name)),
]:
    try:
        write_call()
        if Path(data_file).exists():
            break
    except Exception as err:
        write_errors.append(f"{label}: {type(err).__name__}: {err}")
else:
    print("write_to_file failed:", " | ".join(write_errors) or f"未生成文件：{data_file}")
print("XY data:", data_file)

image = post_path(f"{name}.png")
image = save_picture(image)
show_image(image)
refresh_post()
''',
    },
    {
        "name": "等值图：Contour 并保存",
        "code": '''# Contour 模板：显示变量等值图并保存当前窗口
name = "contour-pressure"
field = "pressure"
surfaces = ["wall"]          # 改成目标 surface；也可以用 ["symmetry", "outlet"]

try:
    results = solver.settings.results
except Exception:
    results = solver.results

contours = results.graphics.contour
try:
    if name in contours.list():
        contours.delete(name)
except Exception:
    pass

contours[name] = {}
obj = contours[name]
obj.field = field
obj.surfaces_list = surfaces
try:
    obj.filled = True
except Exception:
    pass
obj.display()

image = post_path(f"{name}.png")
image = save_picture(image)
show_image(image)
print("saved:", image)
refresh_post()
''',
    },
    {
        "name": "矢量图：Velocity Vector",
        "code": '''# Vector 模板：显示速度矢量并保存
name = "vector-velocity"
surfaces = ["wall"]

try:
    results = solver.settings.results
except Exception:
    results = solver.results

vectors = results.graphics.vector
try:
    if name in vectors.list():
        vectors.delete(name)
except Exception:
    pass

vectors[name] = {}
obj = vectors[name]
obj.surfaces_list = surfaces
try:
    obj.vector_field = "velocity"
except Exception:
    pass
try:
    obj.field = "velocity-magnitude"
except Exception:
    pass
obj.display()

image = post_path(f"{name}.png")
image = save_picture(image)
show_image(image)
print("saved:", image)
refresh_post()
''',
    },
    {
        "name": "Particle Tracks：显示并保存",
        "code": '''# Particle Tracks 模板：显示粒子轨迹并保存当前窗口
name = "particle-tracks"
injections = ["injection-0"]
field = "particle-diameter"

try:
    results = solver.settings.results
except Exception:
    results = solver.results

tracks = results.graphics.particle_track
names = tracks.get_object_names()
if name not in names:
    tracks.create(name)

obj = tracks[name]
obj.injections_list.set_state(injections)
obj.skip.set_state(50)

try:
    if field in obj.field.allowed_values():
        obj.field.set_state(field)
except Exception:
    pass

obj.color_map.visible.set_state(True)
obj.color_map.size.set_state(9)
obj.color_map.format.set_state("%0.2f")

try:
    ro = results.graphics.views.rendering_options
    if "bottom" in ro.color_map_alignment.allowed_values():
        ro.color_map_alignment.set_state("bottom")
    ro.show_colormap.set_state(True)
except Exception as err:
    print("color map alignment skipped:", type(err).__name__, err)

obj.display()

image = post_path(f"{name}.png")
image = save_picture(image)
show_image(image)
print("saved:", image)
refresh_post()
''',
    },
    {
        "name": "保存当前图形窗口",
        "code": '''# 保存当前 Fluent 图形窗口
image = post_path("current-view.png")
image = save_picture(image)
show_image(image)
print("saved:", image)
refresh_post()
''',
    },
    {
        "name": "TUI 后备：XY Plot",
        "code": '''# TUI 后备模板：当 settings API 不顺手时，可直接发送 Fluent TUI。
# 注意：XY Plot 的交互式 TUI 在不同 Fluent 版本/模型下提示项可能不同。
# 推荐先在 Fluent 控制台手动走一遍，再把 transcript 中的命令整理到这里。

run_tui("/plot/xy-plot")
# 也可以写完整命令串：
# run_tui("""
# /plot/xy-plot
# yes
# pressure
# wall
# ()
# """)

image = post_path("tui-xy-plot.png")
image = save_picture(image)
show_image(image)
refresh_post()
''',
    },
]
DEFAULT_PY_EDITOR_TEMPLATES = DEFAULT_PLOT_BUTTONS
POST_OBJECT_TYPES = [
    ("xy_plot", "XY 图", ("plot", "xy_plot")),
    ("contour", "等值图", ("graphics", "contour")),
    ("vector", "矢量图", ("graphics", "vector")),
    ("pathline", "迹线图", ("graphics", "pathline")),
    ("particle_track", "Particle Tracks", ("graphics", "particle_track")),
    ("report_definition", "报告/表", ("parameters", "output_parameters", "report_definitions")),
    ("report_file", "Report Files", ("solution", "monitor", "report_files")),
]
DEFAULT_ON_DEMAND_FUNCTIONS = [
    "Vari_Sources",
]
DEFAULT_INIT_ZONE_TYPE = "mass-flow-inlet"
DEFAULT_INIT_ZONE_NAME = "inlet"
DEFAULT_INIT_PHASE = "mixture"
COMMON_INIT_ZONE_TYPES = [
    "mass-flow-inlet",
    "velocity-inlet",
    "pressure-inlet",
    "pressure-outlet",
    "inlet",
]
COMMON_INIT_PHASES = [
    "mixture",
]
WORKFLOW_STEP_TYPES = [
    ("tui", "执行 TUI 命令"),
    ("python", "执行 PyFluent 语句"),
    ("post_object", "后处理对象"),
    ("wait", "等待"),
    ("execute_on_demand", "Execute On Demand"),
    ("iterate", "开始计算"),
    ("initialize", "初始化"),
    ("mesh_check", "检查网格"),
    ("load_scm", "加载 SCM"),
]
DEFAULT_AUTOMATION_WORKFLOWS = [
    {
        "name": "检查网格",
        "steps": [{"type": "mesh_check"}],
    },
    {
        "name": "初始化后计算",
        "steps": [
            {
                "type": "initialize",
                "from_zone_type": DEFAULT_INIT_ZONE_TYPE,
                "from_zone_name": DEFAULT_INIT_ZONE_NAME,
                "phase": DEFAULT_INIT_PHASE,
            },
            {"type": "wait", "seconds": 1.0},
            {"type": "iterate", "count": 100},
        ],
    },
    {
        "name": "Vari_Sources + 计算",
        "steps": [
            {"type": "execute_on_demand", "function": "Vari_Sources"},
            {"type": "wait", "seconds": 1.0},
            {"type": "iterate", "count": 100},
        ],
    },
]
SWEEP_TOOLS_DIR = TOOL_ROOT / "tools"
SWEEP_MODULE_PATH = SWEEP_TOOLS_DIR / "sweep.py"
SWEEP_CONFIG_PATH = SWEEP_TOOLS_DIR / "sweep_config.py"
FALLBACK_SWEEP_PARAM_GRID: dict[str, list[float]] = {
    "udf/a-ent": [5.0e-13, 1.0e-12, 2.0e-12],
    "udf/lambda-ent": [1.3, 1.5, 1.7],
    "udf/theta-ent": [1.3, 1.5, 1.7],
    "udf/evap-a": [267.81],
    "udf/evap-ea": [125604.0],
}
SWEEP_BUTTON_ACTIONS = [
    ("define_rpvars", "创建 rpvar"),
    ("apply_selected_combo", "应用当前组合"),
    ("reload_params", "刷新 UDF 参数"),
    ("print_params", "打印当前参数"),
    ("run_selected_combo", "运行当前组合流程"),
    ("run_all_combos", "运行全部组合"),
    ("preview_selected_combo", "预览当前命令"),
]
DEFAULT_SWEEP_BUTTONS = [
    {"name": "创建 rpvar", "action": "define_rpvars"},
    {"name": "应用当前组合", "action": "apply_selected_combo"},
    {"name": "刷新 UDF 参数", "action": "reload_params"},
    {"name": "打印当前参数", "action": "print_params"},
    {"name": "预览当前命令", "action": "preview_selected_combo"},
    {"name": "运行当前组合", "action": "run_selected_combo"},
    {"name": "运行全部组合", "action": "run_all_combos"},
]
DEFAULT_SWEEP_WORKFLOWS = [
    {
        "name": "扫描初始化：标准初始化",
        "steps": [
            {
                "type": "initialize",
                "from_zone_type": DEFAULT_INIT_ZONE_TYPE,
                "from_zone_name": DEFAULT_INIT_ZONE_NAME,
                "phase": DEFAULT_INIT_PHASE,
            },
        ],
    },
    {
        "name": "扫描后处理：保存 Data + 导出 XY",
        "steps": [
            {"type": "python", "code": "write_data(combo_data)"},
            {
                "type": "post_object",
                "kind": "xy_plot",
                "action": "write_data",
                "ref": "xy-plot-r-mm",
                "target": "{combo_dir}/xy-plot-r-mm.xy",
            },
            {
                "type": "post_object",
                "kind": "xy_plot",
                "action": "write_data",
                "ref": "xy-plot-t",
                "target": "{combo_dir}/xy-plot-t.xy",
            },
        ],
    },
    {
        "name": "初始化 + 计算 100 步",
        "steps": [
            {
                "type": "initialize",
                "from_zone_type": DEFAULT_INIT_ZONE_TYPE,
                "from_zone_name": DEFAULT_INIT_ZONE_NAME,
                "phase": DEFAULT_INIT_PHASE,
            },
            {"type": "iterate", "count": 100},
        ],
    },
    {
        "name": "计算并保存 Data",
        "steps": [
            {"type": "iterate", "count": 100},
            {"type": "tui", "command": '/file/write-data "{combo_label}.dat.h5"'},
        ],
    },
]
DEFAULT_SWEEP_ITERATIONS = 400
SWEEP_CALCULATION_CHUNK = 50
SWEEP_COMBO_UI_LIMIT = 5_000
SWEEP_STATUS_FILE = "sweep_status.json"
SWEEP_COMPLETED_SUFFIXES = {
    ".xy",
    ".csv",
    ".tsv",
    ".txt",
    ".dat",
    ".out",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".h5",
}
_SWEEP_MODULE_CACHE: Any | None = None
_SWEEP_CONFIG_CACHE: Any | None = None
_SWEEP_MODULE_CACHE_PATH: Path | None = None
_SWEEP_CONFIG_CACHE_PATH: Path | None = None
_ACTIVE_SWEEP_MODULE_PATH = SWEEP_MODULE_PATH.resolve()
_ACTIVE_SWEEP_CONFIG_PATH = SWEEP_CONFIG_PATH.resolve()

IGNORED_UDF_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".svn",
    ".vscode",
    "__pycache__",
    "build",
    "cmake-build-debug",
    "cmake-build-release",
    "libudf",
}

CONSOLE_COMMAND_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*>\s|^\s*>\s")
ITERATION_LINE_RE = re.compile(r"^\s*(\d+)\s+(?:[-+]?\d|\d)")
TUI_ITERATE_RE = re.compile(r"/solve/(?:dual-time-)?iterate\s+(\d+)", re.IGNORECASE)
PYTHON_ITERATE_RE = re.compile(r"\b(?:iterate|dual_time_iterate)\s*\(\s*(\d+)", re.IGNORECASE)
FILE_WRITE_TUI_RE = re.compile(
    r'^\s*/file/(write-case-data|write-case|write-data)\s+(?:"([^"]+)"|(\S+))(?:\s+(?:yes|y))?\s*$',
    re.IGNORECASE,
)
WRITE_DATA_INLINE_YES_RE = re.compile(r'(?im)^(\s*/file/write-data\s+"[^"\n]+")\s+(?:yes|y)\s*$')
COMBO_DATA_ROLE = Qt.ItemDataRole.UserRole
COMBO_SORT_ROLE = Qt.ItemDataRole.UserRole + 1
CONSOLE_ERROR_RE = re.compile(
    r"(\bError\s*:|\bERROR\s*:|\bFatal\s*:|\bFatal error\b|\bTraceback\b|\bException\b|"
    r"\bRuntimeError\s*:|\bValueError\s*:|\bFileNotFoundError\s*:|\[stderr\]|失败)",
    re.IGNORECASE,
)
CONSOLE_WARNING_RE = re.compile(r"(\bWarning\s*:|\bWARNING\s*:|\bWarn\s*:|警告)", re.IGNORECASE)
SWEEP_CACHE_VALUE_RE = re.compile(
    r"\[sweep\]\s+(A_ent|lambda|theta|evap_A|evap_Ea)\s*=\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)
SWEEP_CACHE_STATUS_RE = re.compile(
    r"\[sweep\]\s+status\s+role=(\w+)\s+active_exists=(\d+)\s+"
    r"active=([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+source=(\w+)\s+"
    r"loaded_mask=0x([0-9a-fA-F]+)",
    re.IGNORECASE,
)
SWEEP_CACHE_RPVAR_KEYS = {
    "a_ent": "udf/a-ent",
    "lambda": "udf/lambda-ent",
    "theta": "udf/theta-ent",
    "evap_a": "udf/evap-a",
    "evap_ea": "udf/evap-ea",
}
SWEEP_CACHE_RPVAR_MASKS = {
    "udf/a-ent": 0x01,
    "udf/lambda-ent": 0x02,
    "udf/theta-ent": 0x04,
    "udf/evap-a": 0x08,
    "udf/evap-ea": 0x10,
}


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def clean_entry(value: str) -> str:
    return str(value or "").strip().strip('"')


def clean_text(value: str) -> str:
    return str(value or "").strip()


def apply_application_font(app: QApplication) -> None:
    families = set(QFontDatabase.families())
    for family in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Segoe UI",
    ):
        if family in families:
            app.setFont(QFont(family, 9))
            return
    fallback = "Microsoft YaHei UI" if sys.platform.startswith("win") else "Noto Sans CJK SC"
    app.setFont(QFont(fallback, 9))


def normalize_path(text: str) -> Path:
    return Path(clean_entry(text)).expanduser().resolve()


def unique_file_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 10_000):
        candidate = parent / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成不重名文件路径：{path}")


def optional_env_path(key: str) -> Path | None:
    value = clean_entry(os.environ.get(key, ""))
    return normalize_path(value) if value else None


def parse_udf_targets(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_UDF_TARGETS
    targets = tuple(clean_entry(item).lower() for item in value.split(",") if clean_entry(item))
    return targets or DEFAULT_UDF_TARGETS


def udf_solver_for_dimension(dimension_text: str) -> str:
    explicit = clean_entry(os.environ.get("PYFLUENT_LITE_UDF_SOLVER", "")).lower()
    if explicit:
        return explicit
    return "2ddp" if str(dimension_text).strip().startswith("2") else "3ddp"


def require_path(text: str, label: str) -> Path:
    cleaned = clean_entry(text)
    if not cleaned:
        raise ValueError(f"请选择{label}。")
    return Path(cleaned).expanduser().resolve()


def fluent_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").replace('"', '\\"')


def fluent_tui_arg(value: str) -> str:
    text = clean_entry(value)
    if not text:
        return '""'
    if re.search(r"\s|[\"'()]", text):
        return json.dumps(text)
    return text


def on_demand_target(function_name: str, library_name: str = "libudf") -> str:
    text = clean_entry(function_name)
    if not text:
        raise ValueError("请输入 Execute On Demand 函数名。")
    if "::" in text:
        return text
    return f"{text}::{clean_entry(library_name) or 'libudf'}"


def combo_text(combo: QComboBox) -> str:
    return clean_entry(combo.currentText())


def combo_plain_text(combo: QComboBox) -> str:
    return clean_text(combo.currentText())


def set_combo_text(combo: QComboBox, value: str | Path) -> None:
    combo.setCurrentText(str(value or ""))


def dialog_start_path(*values: str | Path, fallback_name: str = "") -> str:
    for value in values:
        text = clean_entry(str(value or ""))
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.exists():
            if path.is_file():
                return str(path)
            if path.is_dir():
                return str(path / fallback_name) if fallback_name else str(path)
        if path.suffix:
            parent = path.parent
            if parent.exists() and parent.is_dir():
                return str(path)
        elif path.parent.exists() and path.parent.is_dir():
            return str(path)
    fallback = DEFAULT_WORK_DIR if DEFAULT_WORK_DIR.exists() else TOOL_ROOT
    return str(fallback / fallback_name) if fallback_name else str(fallback)


def read_history(settings: QSettings, key: str) -> list[str]:
    raw = settings.value(f"history/{key}", [])
    if isinstance(raw, (list, tuple)):
        values = [clean_entry(str(item)) for item in raw]
    elif raw:
        values = [clean_entry(item) for item in str(raw).splitlines()]
    else:
        values = []

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        marker = value.lower()
        if value and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result[:HISTORY_LIMIT]


def read_text_history(settings: QSettings, key: str) -> list[str]:
    raw = settings.value(f"history/{key}", [])
    if isinstance(raw, (list, tuple)):
        values = [clean_text(str(item)) for item in raw]
    elif raw:
        values = [clean_text(item) for item in str(raw).splitlines()]
    else:
        values = []

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        marker = value.lower()
        if value and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result[:HISTORY_LIMIT]


def remember_history(settings: QSettings, key: str, value: str) -> list[str]:
    text = clean_entry(value)
    items = read_history(settings, key)
    if text:
        items = [item for item in items if item.lower() != text.lower()]
        items.insert(0, text)
    items = items[:HISTORY_LIMIT]
    settings.setValue(f"history/{key}", items)
    return items


def remember_text_history(settings: QSettings, key: str, value: str) -> list[str]:
    text = clean_text(value)
    items = read_text_history(settings, key)
    if text:
        items = [item for item in items if item.lower() != text.lower()]
        items.insert(0, text)
    items = items[:HISTORY_LIMIT]
    settings.setValue(f"history/{key}", items)
    return items


def populate_combo(combo: QComboBox, items: list[str], current: str = "") -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(items)
    combo.setCurrentText(current)
    combo.blockSignals(False)


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


def safe_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def safe_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def load_launch_enums():
    try:
        from ansys.fluent.core.launcher.pyfluent_enums import (
            Dimension,
            FluentMode,
            Precision,
            UIMode,
        )
    except ModuleNotFoundError:
        from ansys.fluent.core.launcher.launch_options import (
            Dimension,
            FluentMode,
            Precision,
            UIMode,
        )
    return Dimension, FluentMode, Precision, UIMode


def should_skip_udf_dir(dirname: str) -> bool:
    name = dirname.strip().lower()
    return name in IGNORED_UDF_DIRS or name.startswith("cmake-build-")


def init_step(
    from_zone_type: str = DEFAULT_INIT_ZONE_TYPE,
    from_zone_name: str = DEFAULT_INIT_ZONE_NAME,
    phase: str = DEFAULT_INIT_PHASE,
) -> dict[str, str]:
    return {
        "type": "initialize",
        "from_zone_type": clean_entry(from_zone_type) or DEFAULT_INIT_ZONE_TYPE,
        "from_zone_name": clean_entry(from_zone_name) or DEFAULT_INIT_ZONE_NAME,
        "phase": clean_entry(phase) or DEFAULT_INIT_PHASE,
    }


def workflow_step_summary(step: dict[str, Any]) -> str:
    step_type = str(step.get("type", "tui"))
    if step_type == "tui":
        return f"TUI：{clean_text(str(step.get('command', '')))}"
    if step_type == "python":
        return f"PyFluent：{clean_text(str(step.get('code', '')))}"
    if step_type == "post_object":
        kind = clean_entry(str(step.get("kind", "xy_plot")))
        action = clean_entry(str(step.get("action", "display")))
        ref = clean_entry(str(step.get("ref", "")))
        target = clean_entry(str(step.get("target", "")))
        action_label = {"display": "显示", "save_image": "保存图片", "write_data": "导出数据"}.get(action, action)
        kind_label = post_object_type_label(kind)
        return f"后处理：{action_label} {kind_label} {ref}" + (f" -> {target}" if target else "")
    if step_type == "wait":
        return f"等待：{float(step.get('seconds', 0) or 0):g} 秒"
    if step_type == "execute_on_demand":
        return f"Execute On Demand：{clean_entry(str(step.get('function', '')))}"
    if step_type == "iterate":
        return f"开始计算：{safe_int(step.get('count', 1), 1, minimum=1)} 步"
    if step_type == "initialize":
        zone_type = clean_entry(str(step.get("from_zone_type", DEFAULT_INIT_ZONE_TYPE)))
        zone_name = clean_entry(str(step.get("from_zone_name", DEFAULT_INIT_ZONE_NAME)))
        phase = clean_entry(str(step.get("phase", DEFAULT_INIT_PHASE)))
        return f"标准初始化：{zone_type} / {zone_name} / {phase}"
    if step_type == "mesh_check":
        return "检查网格：/mesh/check"
    if step_type == "load_scm":
        return f"加载 SCM：{clean_entry(str(step.get('path', '')))}"
    return f"未知步骤：{step_type}"


def post_object_type_label(kind: str) -> str:
    for key, label, _path in POST_OBJECT_TYPES:
        if key == kind:
            return label
    return kind or "后处理对象"


def post_object_data_suffix(kind: str) -> str:
    if kind == "xy_plot":
        return ".xy"
    if kind == "report_file":
        return ".out"
    return ".txt"


def normalize_post_object_step(item: dict[str, Any]) -> dict[str, str] | None:
    valid_kinds = {key for key, _label, _path in POST_OBJECT_TYPES}
    kind = clean_entry(str(item.get("kind", "xy_plot")))
    if kind not in valid_kinds:
        kind = "xy_plot"
    action = clean_entry(str(item.get("action", "display")))
    if action not in {"display", "save_image", "write_data"}:
        action = "display"
    ref = clean_entry(str(item.get("ref", "")))
    target = clean_entry(str(item.get("target", "")))
    if not ref:
        return None
    result = {"type": "post_object", "kind": kind, "action": action, "ref": ref}
    if target:
        result["target"] = target
    return result


def normalize_workflow(raw: dict[str, Any]) -> dict[str, Any]:
    name = clean_entry(str(raw.get("name", ""))) or "未命名流程"
    steps: list[dict[str, Any]] = []
    for item in raw.get("steps", []) if isinstance(raw.get("steps", []), list) else []:
        if not isinstance(item, dict):
            continue
        step_type = str(item.get("type", "tui"))
        if step_type == "python":
            code = clean_text(str(item.get("code", "")))
            if code:
                steps.append({"type": "python", "code": code})
        elif step_type == "post_object":
            step = normalize_post_object_step(item)
            if step is not None:
                steps.append(step)
        elif step_type == "wait":
            steps.append({"type": "wait", "seconds": safe_float(item.get("seconds", 0), 0.0, minimum=0.0)})
        elif step_type == "execute_on_demand":
            function = clean_entry(str(item.get("function", "")))
            if function:
                steps.append({"type": "execute_on_demand", "function": function})
        elif step_type == "iterate":
            steps.append({"type": "iterate", "count": safe_int(item.get("count", 1), 1, minimum=1)})
        elif step_type == "initialize":
            steps.append(
                init_step(
                    str(item.get("from_zone_type", DEFAULT_INIT_ZONE_TYPE)),
                    str(item.get("from_zone_name", DEFAULT_INIT_ZONE_NAME)),
                    str(item.get("phase", DEFAULT_INIT_PHASE)),
                )
            )
        elif step_type == "mesh_check":
            steps.append({"type": "mesh_check"})
        elif step_type == "load_scm":
            path = clean_entry(str(item.get("path", "")))
            if path:
                steps.append({"type": "load_scm", "path": path})
        else:
            command = sanitize_workflow_tui_command(str(item.get("command", "")))
            if command:
                steps.append({"type": "tui", "command": command})
    return {"name": name, "steps": steps}


def default_workflows() -> list[dict[str, Any]]:
    return [normalize_workflow(item) for item in DEFAULT_AUTOMATION_WORKFLOWS]


def _load_module_from_path(cache_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(cache_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_sweep_file_path(value: str | Path | None, default: Path) -> Path:
    text = clean_entry(str(value or ""))
    path = Path(text).expanduser() if text else default
    return path.resolve()


def set_sweep_tool_paths(
    module_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> tuple[Path, Path]:
    global _ACTIVE_SWEEP_MODULE_PATH, _ACTIVE_SWEEP_CONFIG_PATH
    global _SWEEP_MODULE_CACHE, _SWEEP_CONFIG_CACHE
    global _SWEEP_MODULE_CACHE_PATH, _SWEEP_CONFIG_CACHE_PATH

    next_module_path = _resolve_sweep_file_path(module_path, SWEEP_MODULE_PATH)
    next_config_path = _resolve_sweep_file_path(config_path, SWEEP_CONFIG_PATH)
    if next_module_path != _ACTIVE_SWEEP_MODULE_PATH:
        _SWEEP_MODULE_CACHE = None
        _SWEEP_MODULE_CACHE_PATH = None
    if next_config_path != _ACTIVE_SWEEP_CONFIG_PATH:
        _SWEEP_CONFIG_CACHE = None
        _SWEEP_CONFIG_CACHE_PATH = None
    _ACTIVE_SWEEP_MODULE_PATH = next_module_path
    _ACTIVE_SWEEP_CONFIG_PATH = next_config_path
    return _ACTIVE_SWEEP_MODULE_PATH, _ACTIVE_SWEEP_CONFIG_PATH


def current_sweep_module_path() -> Path:
    return _ACTIVE_SWEEP_MODULE_PATH


def current_sweep_config_path() -> Path:
    return _ACTIVE_SWEEP_CONFIG_PATH


def load_sweep_module():
    global _SWEEP_MODULE_CACHE, _SWEEP_MODULE_CACHE_PATH
    path = current_sweep_module_path()
    if _SWEEP_MODULE_CACHE is None or _SWEEP_MODULE_CACHE_PATH != path:
        if not path.exists():
            raise FileNotFoundError(f"找不到参数扫描接口：{path}")
        _SWEEP_MODULE_CACHE = _load_module_from_path("pyfluent_lite_tools_sweep", path)
        _SWEEP_MODULE_CACHE_PATH = path
    return _SWEEP_MODULE_CACHE


def load_sweep_config_module():
    global _SWEEP_CONFIG_CACHE, _SWEEP_CONFIG_CACHE_PATH
    path = current_sweep_config_path()
    if _SWEEP_CONFIG_CACHE is None or _SWEEP_CONFIG_CACHE_PATH != path:
        if not path.exists():
            raise FileNotFoundError(f"找不到参数扫描配置：{path}")
        _SWEEP_CONFIG_CACHE = _load_module_from_path("pyfluent_lite_tools_sweep_config", path)
        _SWEEP_CONFIG_CACHE_PATH = path
    return _SWEEP_CONFIG_CACHE


def normalize_sweep_param_grid(raw: Any) -> dict[str, list[float]]:
    if not isinstance(raw, dict):
        raw = FALLBACK_SWEEP_PARAM_GRID
    result: dict[str, list[float]] = {}
    for key, values in raw.items():
        name = clean_entry(str(key))
        if not name:
            continue
        if isinstance(values, (list, tuple)):
            raw_values = values
        else:
            raw_values = [item for item in re.split(r"[,\s]+", str(values)) if item]
        parsed: list[float] = []
        for value in raw_values:
            try:
                parsed.append(float(value))
            except (TypeError, ValueError):
                continue
        if parsed:
            result[name] = parsed
    return result or {key: list(values) for key, values in FALLBACK_SWEEP_PARAM_GRID.items()}


def default_sweep_param_grid() -> dict[str, list[float]]:
    try:
        config = load_sweep_config_module()
        return normalize_sweep_param_grid(getattr(config, "PARAM_GRID"))
    except Exception:
        return {key: list(values) for key, values in FALLBACK_SWEEP_PARAM_GRID.items()}


def format_sweep_param_grid(param_grid: dict[str, list[float]]) -> str:
    grid = normalize_sweep_param_grid(param_grid)
    lines = []
    for key in sorted(grid.keys()):
        values = ", ".join(f"{value:.9g}" for value in grid[key])
        lines.append(f"{key} = {values}")
    return "\n".join(lines)


def parse_sweep_param_grid_text(text: str) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        separator = "=" if "=" in line else (":" if ":" in line else "")
        if not separator:
            errors.append(f"第 {line_number} 行缺少 = 或 :")
            continue
        key, value_text = line.split(separator, 1)
        name = clean_entry(key)
        tokens = [
            item.strip().strip("[]()")
            for item in re.split(r"[,\s]+", value_text)
            if item.strip().strip("[]()")
        ]
        values: list[float] = []
        for token in tokens:
            try:
                values.append(float(token))
            except ValueError:
                errors.append(f"第 {line_number} 行存在无法解析的数值：{token}")
        if not name:
            errors.append(f"第 {line_number} 行参数名为空")
        elif values:
            result[name] = values
    if errors:
        raise ValueError("\n".join(errors))
    if not result:
        raise ValueError("参数网格为空。")
    return result


def sweep_config_source(param_grid: dict[str, list[float]]) -> str:
    grid = normalize_sweep_param_grid(param_grid)
    max_key_len = max((len(repr(key)) for key in grid.keys()), default=12)
    lines = [
        '"""',
        "sweep_config.py",
        "---------------",
        "参数扫描配置: 定义要扫描的 Fluent rpvar 及其取值列表。",
        "",
        "本文件可由 PyFluent Lite 的“参数扫描”页写回。",
        '"""',
        "",
        "PARAM_GRID: dict[str, list[float]] = {",
    ]
    for key in sorted(grid.keys()):
        key_text = repr(key)
        values = ", ".join(f"{value:.12g}" for value in grid[key])
        lines.append(f"    {key_text:<{max_key_len}}: [{values}],")
    lines.extend(["}", ""])
    return "\n".join(lines)


def write_sweep_config(param_grid: dict[str, list[float]], path: Path | None = None) -> Path:
    target = (path or current_sweep_config_path()).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sweep_config_source(param_grid), encoding="utf-8")
    return target


def list_sweep_combos(param_grid: dict[str, list[float]]) -> list[dict[str, float]]:
    grid = normalize_sweep_param_grid(param_grid)
    try:
        sweep = load_sweep_module()
        return list(sweep.list_combos(grid))
    except Exception:
        keys = sorted(grid.keys())
        return [dict(zip(keys, values)) for values in itertools.product(*(grid[key] for key in keys))]


def sweep_combo_count(param_grid: dict[str, list[float]]) -> int:
    grid = normalize_sweep_param_grid(param_grid)
    total = 1
    for values in grid.values():
        total *= len(values)
    return total


def sweep_define_commands(param_grid: dict[str, list[float]]) -> list[str]:
    grid = normalize_sweep_param_grid(param_grid)
    try:
        sweep = load_sweep_module()
        return list(sweep.get_define_rpvar_commands(grid))
    except Exception:
        return [
            "(make-new-fl-rpvar 'udf/sweep-active 0.0 'real)",
            *[f"(make-new-fl-rpvar '{key} 0.0 'real)" for key in sorted(grid.keys())],
        ]


def sweep_set_commands(combo: dict[str, float]) -> list[str]:
    try:
        sweep = load_sweep_module()
        return list(sweep.get_set_combo_commands(combo))
    except Exception:
        return [
            "(rpsetvar 'udf/sweep-active 1.0)",
            *[f"(rpsetvar '{key} {float(value):.9e})" for key, value in sorted(combo.items())],
        ]


def sweep_reload_command() -> str:
    try:
        return str(load_sweep_module().get_reload_command())
    except Exception:
        return '/define/user-defined/execute-on-demand "Reload_Sweep_Params::libudf"'


def sweep_print_command() -> str:
    try:
        return str(load_sweep_module().get_print_command())
    except Exception:
        return '/define/user-defined/execute-on-demand "Print_Sweep_Params::libudf"'


def sweep_combo_label(index: int) -> str:
    try:
        return str(load_sweep_module().combo_label(index))
    except Exception:
        return f"combo-{index:03d}"


def sweep_combo_summary(combo: dict[str, float]) -> str:
    try:
        return str(load_sweep_module().combo_summary(combo))
    except Exception:
        return ", ".join(f"{key}={value:g}" for key, value in sorted(combo.items()))


def sweep_combo_dir_name(index: int) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", sweep_combo_label(index)).strip("._") or f"combo-{index:03d}"


class SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_workflow_text(text: str, context: dict[str, Any] | None) -> str:
    if not context:
        return text
    try:
        return str(text or "").format_map(SafeFormatDict(context))
    except (KeyError, ValueError):
        return str(text or "")


def sanitize_workflow_tui_command(command: str) -> str:
    return WRITE_DATA_INLINE_YES_RE.sub(r"\1", clean_text(str(command or "")))


def sweep_context(combo: dict[str, float], combo_index: int, total_combos: int) -> dict[str, Any]:
    return {
        "combo": dict(combo),
        "combo_index": combo_index,
        "combo_number": combo_index + 1,
        "combo_total": total_combos,
        "combo_label": sweep_combo_label(combo_index),
        "combo_summary": sweep_combo_summary(combo),
    }


def sweep_batch_context(
    combo: dict[str, float],
    combo_index: int,
    total_combos: int,
    batch_index: int,
    batch_total: int,
    scan_dir: Path,
    combo_dir: Path,
    base_case: Path | None,
) -> dict[str, Any]:
    context = sweep_context(combo, combo_index, total_combos)
    context.update(
        {
            "batch_index": batch_index,
            "batch_number": batch_index + 1,
            "batch_total": batch_total,
            "scan_dir": str(scan_dir),
            "scan_dir_fluent": fluent_path(scan_dir),
            "combo_dir": str(combo_dir),
            "combo_dir_fluent": fluent_path(combo_dir),
            "combo_case": str(combo_dir / f"{context['combo_label']}.cas.h5"),
            "combo_case_fluent": fluent_path(combo_dir / f"{context['combo_label']}.cas.h5"),
            "combo_data": str(combo_dir / f"{context['combo_label']}.dat.h5"),
            "combo_data_fluent": fluent_path(combo_dir / f"{context['combo_label']}.dat.h5"),
            "base_case": str(base_case) if base_case else "",
            "base_case_fluent": fluent_path(base_case) if base_case else "",
        }
    )
    return context


def sweep_status_path(combo_dir: Path) -> Path:
    return combo_dir / SWEEP_STATUS_FILE


def sweep_file_has_content(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def sweep_completed_artifact(combo_dir: Path, combo_label: str) -> Path | None:
    if not combo_dir.exists() or not combo_dir.is_dir():
        return None
    expected_names = [
        f"{combo_label}.dat.h5",
        f"{combo_label}.dat",
        f"{combo_label}.cas.h5",
        f"{combo_label}.cas",
        f"{combo_label}.cas.gz",
        f"{combo_label}.dat.gz",
    ]
    for name in expected_names:
        path = combo_dir / name
        if sweep_file_has_content(path):
            return path
    try:
        children = sorted(combo_dir.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return None
    for path in children:
        if not sweep_file_has_content(path):
            continue
        lowered = path.name.lower()
        if lowered in {"combo_params.json", SWEEP_STATUS_FILE}:
            continue
        if lowered.endswith((".dat.h5", ".cas.h5")) or path.suffix.lower() in SWEEP_COMPLETED_SUFFIXES:
            return path
    return None


def read_sweep_disk_status(combo_dir: Path, combo_label: str) -> tuple[str, str]:
    marker = sweep_status_path(combo_dir)
    if marker.exists():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except Exception as error:
            return "pending", f"状态文件读取失败：{type(error).__name__}: {error}"
        status = str(payload.get("status", "pending"))
        detail = clean_entry(str(payload.get("detail", "")))
        if status in {"success", "skipped"}:
            return "success", detail or f"状态文件显示已完成：{marker}"
        if status in {"failed", "stopped"}:
            return status, detail or f"状态文件：{marker}"

    artifact = sweep_completed_artifact(combo_dir, combo_label)
    if artifact is not None:
        return "success", f"发现已有结果：{artifact}"
    return "pending", ""


def scan_sweep_disk_statuses(
    combo_entries: list[tuple[int, str, str]],
    scan_dir: Path,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    total = len(combo_entries)
    statuses: dict[int, tuple[str, str]] = {}
    counts = {"success": 0, "failed": 0, "stopped": 0, "pending": 0}
    last_progress_emit = 0.0
    for done, (index, label, dir_name) in enumerate(combo_entries, start=1):
        combo_dir = (scan_dir / dir_name).resolve()
        status, detail = read_sweep_disk_status(combo_dir, label)
        if status == "success":
            counts["success"] += 1
            statuses[index] = ("success", detail or f"已完成：{combo_dir}")
        elif status == "failed":
            counts["failed"] += 1
            statuses[index] = ("failed", detail or f"状态文件显示失败：{combo_dir}")
        elif status == "stopped":
            counts["stopped"] += 1
            statuses[index] = ("stopped", detail or f"状态文件显示已停止：{combo_dir}")
        else:
            counts["pending"] += 1
            statuses[index] = ("pending", "")
        now = time.monotonic()
        if progress is not None and (done == 1 or done == total or now - last_progress_emit >= 0.08):
            progress(done, total, f"正在扫描 {label}")
            last_progress_emit = now
    return {
        "statuses": statuses,
        "counts": counts,
        "scan_dir": str(scan_dir),
        "total": total,
    }


def normalize_sweep_button(raw: dict[str, Any]) -> dict[str, str]:
    actions = {key for key, _label in SWEEP_BUTTON_ACTIONS}
    name = clean_entry(str(raw.get("name", ""))) or "未命名模块"
    action = clean_entry(str(raw.get("action", "")))
    if action not in actions:
        action = SWEEP_BUTTON_ACTIONS[0][0]
    return {"name": name, "action": action}


def default_sweep_buttons() -> list[dict[str, str]]:
    return [normalize_sweep_button(item) for item in DEFAULT_SWEEP_BUTTONS]


def default_sweep_workflows() -> list[dict[str, Any]]:
    return [normalize_workflow(item) for item in DEFAULT_SWEEP_WORKFLOWS]


def normalize_command_button(raw: dict[str, Any]) -> dict[str, str]:
    name = clean_entry(str(raw.get("name", ""))) or "未命名命令"
    mode = str(raw.get("mode", "tui")).lower()
    if mode not in {"tui", "python"}:
        mode = "tui"
    command = clean_text(str(raw.get("command", "")))
    return {"name": name, "mode": mode, "command": command}


def default_command_buttons() -> list[dict[str, str]]:
    return [normalize_command_button(item) for item in DEFAULT_COMMAND_BUTTONS]


def normalize_plot_button(raw: dict[str, Any]) -> dict[str, str]:
    name = clean_entry(str(raw.get("name", ""))) or "未命名绘图"
    code = clean_text(str(raw.get("code", "")))
    return {"name": name, "code": code}


def default_plot_buttons() -> list[dict[str, str]]:
    return [normalize_plot_button(item) for item in DEFAULT_PLOT_BUTTONS]


class EmitStream:
    def __init__(self, emit: Callable[[str], None], prefix: str = "") -> None:
        self._emit = emit
        self._prefix = prefix
        self._buffer = ""

    def write(self, value: str) -> int:
        text = str(value or "")
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._emit(f"{self._prefix}{line}\n")
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._emit(f"{self._prefix}{self._buffer}\n")
        self._buffer = ""


class AppSignals(QObject):
    log = Signal(str)
    status = Signal(str)
    busy_changed = Signal(bool)
    session_changed = Signal(bool)
    sweep_combo_status = Signal(int, str, str)
    sweep_progress = Signal(int, int, str)


class WindowSignals(QObject):
    task_finished = Signal(str, str)
    interrupt_finished = Signal(str)
    post_image_ready = Signal(str)
    post_results_scanned = Signal(int, str, list, str, bool)
    post_objects_loaded = Signal(int, str, list, str)
    sweep_disk_scan_progress = Signal(int, int, str)
    sweep_disk_scan_finished = Signal(dict, str)


class ExceptionNotifier(QObject):
    unhandled_exception = Signal(str, str)


class SweepStopped(RuntimeError):
    pass


class SweepRetryRequested(RuntimeError):
    pass


class SortableTableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(COMBO_SORT_ROLE)
        right = other.data(COMBO_SORT_ROLE)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return float(left) < float(right)
        if left is not None and right is not None:
            return str(left) < str(right)
        return super().__lt__(other)


class FluentController:
    def __init__(self, signals: AppSignals) -> None:
        self.signals = signals
        self.session: Any | None = None
        self.work_dir: Path | None = None
        self.udf_solver = "2ddp"
        self._transcript_callback_id: str | None = None
        self._python_scope: dict[str, Any] = {}
        self._sweep_pause_event = threading.Event()
        self._sweep_pause_event.set()
        self._sweep_stop_event = threading.Event()
        self._sweep_retry_event = threading.Event()
        self._sweep_current_index: int | None = None

    @property
    def has_session(self) -> bool:
        return self.session is not None

    def event(self, message: str) -> None:
        self.signals.log.emit(f"[{now_text()}] {message.rstrip()}\n")

    def raw(self, text: str) -> None:
        if not text:
            return
        value = str(text)
        chunk_size = CONSOLE_FORCE_FLUSH_CHARS
        for start in range(0, len(value), chunk_size):
            self.signals.log.emit(value[start : start + chunk_size])

    def set_status(self, message: str) -> None:
        self.signals.status.emit(message)

    def _require_session(self):
        if self.session is None:
            raise RuntimeError("Fluent 尚未启动。")
        return self.session

    @staticmethod
    def _optional_attr(obj: Any, name: str, default: Any = None) -> Any:
        try:
            return getattr(obj, name)
        except Exception:
            return default

    @classmethod
    def _optional_callable(cls, obj: Any, name: str) -> Callable[..., Any] | None:
        value = cls._optional_attr(obj, name)
        return value if callable(value) else None

    def reset_sweep_controls(self) -> None:
        self._sweep_stop_event.clear()
        self._sweep_retry_event.clear()
        self._sweep_pause_event.set()
        self._sweep_current_index = None

    def request_sweep_pause(self) -> None:
        self._sweep_pause_event.clear()
        self.set_status("扫描已暂停")
        self.event("已请求暂停参数扫描，当前 Fluent 操作返回后生效。")

    def request_sweep_resume(self) -> None:
        self._sweep_pause_event.set()
        self.set_status("正在继续扫描")
        self.event("已继续参数扫描。")

    def request_sweep_retry(self) -> None:
        self._sweep_retry_event.set()
        self._sweep_pause_event.set()
        self.set_status("正在请求重试当前组合")
        self.event("已请求重试当前组合，当前 Fluent 操作返回后会重新执行该组合。")

    def request_sweep_stop(self) -> None:
        self._sweep_stop_event.set()
        self._sweep_pause_event.set()
        self.set_status("正在停止扫描")
        self.event("已请求停止参数扫描，当前 Fluent 操作返回后会退出批处理。")

    def _consume_sweep_retry(self) -> bool:
        if not self._sweep_retry_event.is_set():
            return False
        self._sweep_retry_event.clear()
        return True

    def _check_sweep_control(self) -> None:
        if self._sweep_stop_event.is_set():
            raise SweepStopped("用户停止了参数扫描。")
        if self._consume_sweep_retry():
            raise SweepRetryRequested("用户请求重试当前组合。")
        while not self._sweep_pause_event.is_set():
            self.set_status("扫描已暂停")
            time.sleep(0.2)
            if self._sweep_stop_event.is_set():
                raise SweepStopped("用户停止了参数扫描。")
            if self._consume_sweep_retry():
                raise SweepRetryRequested("用户请求重试当前组合。")

    def _session_looks_online(self) -> bool:
        if self.session is None:
            return False
        version = self._optional_callable(self.session, "get_fluent_version")
        if version is None:
            return True
        try:
            version()
            return True
        except Exception as error:
            self.event(f"检测到 Fluent session 不在线：{type(error).__name__}: {error}")
            return False

    @staticmethod
    def _is_session_failure(error: BaseException) -> bool:
        text = (f"{type(error).__name__}: {error}").lower()
        return any(
            token in text
            for token in (
                "grpc",
                "connection",
                "channel",
                "socket",
                "unavailable",
                "deadline",
                "terminated",
                "exited",
                "closed",
                "broken pipe",
                "failed to connect",
                "server is not available",
                "fluent exited",
                "fluent has exited",
            )
        )

    def _clear_failed_session(self, reason: str) -> None:
        if self.session is None:
            return
        self.event(reason)
        with contextlib.suppress(Exception):
            self.shutdown()
        if self.session is not None:
            self.session = None
            self.work_dir = None
            self._transcript_callback_id = None
            self._python_scope.clear()
            self.signals.session_changed.emit(False)
            self.set_status("Fluent 已离线")

    def _ensure_sweep_session(self, launch_config: dict[str, Any] | None, reason: str = "扫描") -> None:
        if self._session_looks_online():
            return
        self._clear_failed_session("当前 Fluent 不在线，准备重新启动。")
        if not launch_config:
            raise RuntimeError("Fluent 未启动，且没有可用的自动启动配置。")
        self.event(f"Fluent 未在线，正在自动启动以继续{reason}。")
        self.launch(
            str(launch_config.get("work_dir", "")),
            str(launch_config.get("case_file", "")),
            str(launch_config.get("dimension_text", "2D")),
            safe_int(launch_config.get("processor_count", 1), 1, minimum=1),
            coerce_bool(launch_config.get("show_gui", True), True),
            coerce_bool(launch_config.get("load_scm_on_start", False), False),
            str(launch_config.get("scm_file", "")),
        )

    def launch(
        self,
        work_dir: str,
        case_file: str,
        dimension_text: str,
        processor_count: int,
        show_gui: bool,
        load_scm_on_start: bool,
        scm_file: str,
    ) -> None:
        if self.session is not None:
            raise RuntimeError("Fluent 已经启动，请先停止当前实例。")

        work_path = require_path(work_dir, "工作目录")
        if not work_path.exists() or not work_path.is_dir():
            raise FileNotFoundError(f"工作目录不存在：{work_path}")

        case_path: Path | None = None
        if clean_entry(case_file):
            case_path = require_path(case_file, "Case 文件")
            if not case_path.exists() or not case_path.is_file():
                raise FileNotFoundError(f"Case 文件不存在：{case_path}")

        scm_path: Path | None = None
        if load_scm_on_start:
            scm_path = require_path(scm_file, "SCM 文件")
            if not scm_path.exists() or not scm_path.is_file():
                raise FileNotFoundError(f"SCM 文件不存在：{scm_path}")

        self.event("正在启动 Fluent...")
        self.set_status("正在启动 Fluent")

        import ansys.fluent.core as pyfluent

        Dimension, FluentMode, Precision, UIMode = load_launch_enums()
        dimension = Dimension.TWO if dimension_text.startswith("2") else Dimension.THREE
        self.udf_solver = udf_solver_for_dimension(dimension_text)
        ui_mode = UIMode.GUI if show_gui else UIMode.NO_GUI_OR_GRAPHICS

        kwargs: dict[str, Any] = {
            "dimension": dimension,
            "precision": Precision.DOUBLE,
            "processor_count": max(1, int(processor_count or 1)),
            "ui_mode": ui_mode,
            "mode": FluentMode.SOLVER,
            "cleanup_on_exit": True,
            "start_transcript": False,
            "py": False,
            "cwd": str(work_path),
        }
        if case_path is not None:
            kwargs["case_file_name"] = str(case_path)
            self.event(f"启动时读取 case：{case_path}")

        with contextlib.redirect_stdout(EmitStream(self.raw)), contextlib.redirect_stderr(
            EmitStream(self.raw, prefix="[stderr] ")
        ):
            session = pyfluent.launch_fluent(**kwargs)

        self.session = session
        self.work_dir = work_path
        self._start_transcript(work_path)
        self.event("Fluent 已就绪。")
        self.set_status("Fluent 已就绪")
        self.signals.session_changed.emit(True)
        if scm_path is not None:
            try:
                self.load_scm(str(scm_path))
            except Exception as error:
                self.event(f"启动后加载 SCM 失败：{type(error).__name__}: {error}")
                self.set_status("Fluent 已就绪，SCM 加载失败")

    def _start_transcript(self, work_path: Path) -> None:
        if self.session is None:
            return

        def on_transcript(text: str) -> None:
            self.raw(str(text or ""))

        transcript = getattr(self.session, "transcript", None)
        if transcript is None:
            self.event("当前 PyFluent session 没有 transcript streaming。")
            return

        callback_id: str | None = None
        try:
            callback_id = transcript.register_callback(
                on_transcript,
                keep_new_lines=True,
            )
            self._transcript_callback_id = callback_id
        except Exception as error:
            self.event(f"Transcript 回调注册失败，继续运行但不显示实时 transcript：{type(error).__name__}: {error}")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        preferred = work_path / f"_pyfluent_lite_transcript_{timestamp}.log"
        log_file = preferred
        if preferred.exists():
            log_file = unique_file_path(preferred)
        legacy_log = work_path / "_pyfluent_lite_transcript.log"
        with contextlib.suppress(Exception):
            if legacy_log.exists() and legacy_log.stat().st_size > TRANSCRIPT_LOG_MAX_BYTES:
                rotated = unique_file_path(work_path / f"_pyfluent_lite_transcript_old_{timestamp}.log")
                legacy_log.replace(rotated)
                self.event(f"旧 transcript 日志过大，已轮转：{rotated}")

        try:
            transcript.start(file_name=str(log_file), write_to_stdout=False)
        except Exception as error:
            self.event(f"Transcript 文件写入启动失败，继续运行但不写 transcript 文件：{type(error).__name__}: {error}")
            with contextlib.suppress(Exception):
                transcript.unregister_callback(callback_id)
            self._transcript_callback_id = None
            return
        self.event(f"Transcript 已连接：{log_file}")

    def shutdown(self) -> None:
        if self.session is None:
            return
        self.event("正在关闭 Fluent...")
        try:
            transcript = getattr(self.session, "transcript", None)
            if transcript is not None and self._transcript_callback_id:
                with contextlib.suppress(Exception):
                    transcript.unregister_callback(self._transcript_callback_id)
                with contextlib.suppress(Exception):
                    transcript.stop()
            closer = getattr(self.session, "exit", None)
            if callable(closer):
                closer()
        finally:
            self.session = None
            self.work_dir = None
            self._transcript_callback_id = None
            self._python_scope.clear()
            self.signals.session_changed.emit(False)
            self.set_status("未启动")
            self.event("Fluent 已关闭。")

    def _execute_tui_raw(self, command: str) -> str:
        session = self._require_session()
        command_text = command.rstrip() + "\n"
        scheme_eval = getattr(session, "scheme_eval", None)
        scheme_exec = getattr(scheme_eval, "exec", None)
        if callable(scheme_exec):
            expression = f"(ti-menu-load-string {json.dumps(command_text)})"
            output = str(scheme_exec((expression,), wait=True, silent=True) or "")
            if output.strip():
                if not output.endswith("\n"):
                    output += "\n"
                self.raw(output)
            return output

        execute_tui = getattr(session, "execute_tui", None)
        if not callable(execute_tui):
            raise RuntimeError("当前 PyFluent 版本没有可用的 TUI 执行接口。")
        execute_tui(command_text)
        return ""

    def _execute_scheme_raw(self, expression: str) -> str:
        session = self._require_session()
        scheme_eval = getattr(session, "scheme_eval", None)
        scheme_exec = getattr(scheme_eval, "exec", None)
        if callable(scheme_exec):
            output = str(scheme_exec((expression,), wait=True, silent=True) or "")
            if output.strip():
                if not output.endswith("\n"):
                    output += "\n"
                self.raw(output)
            return output

        return self._execute_tui_raw(expression)

    def _execute_scheme_commands_raw(self, commands: list[str] | tuple[str, ...]) -> str:
        command_list = [str(command).strip() for command in commands if str(command).strip()]
        if not command_list:
            return ""

        session = self._require_session()
        scheme_eval = getattr(session, "scheme_eval", None)
        scheme_exec = getattr(scheme_eval, "exec", None)
        if callable(scheme_exec):
            output = str(scheme_exec(tuple(command_list), wait=True, silent=True) or "")
            if output.strip():
                if not output.endswith("\n"):
                    output += "\n"
                self.raw(output)
            return output

        output = ""
        for command in command_list:
            output += self._execute_tui_raw(command)
        return output

    def _eval_scheme_value(self, expression: str) -> Any:
        session = self._require_session()
        scheme_eval = getattr(session, "scheme_eval", None)
        scheme_eval_fn = getattr(scheme_eval, "scheme_eval", None)
        if callable(scheme_eval_fn):
            return scheme_eval_fn(expression)
        string_eval = getattr(scheme_eval, "string_eval", None)
        if callable(string_eval):
            return string_eval(expression)
        raise RuntimeError("当前 PyFluent 版本没有可用的 Scheme 求值接口，无法校验扫描参数。")

    def _sweep_rpvar_value(self, name: str) -> float:
        return float(self._eval_scheme_value(f"(rpgetvar '{name})"))

    def _verify_sweep_rpvars(self, combo: dict[str, float]) -> None:
        expected_values = {"udf/sweep-active": 1.0, **{key: float(value) for key, value in combo.items()}}
        mismatches: list[str] = []
        for name, expected in sorted(expected_values.items()):
            actual = self._sweep_rpvar_value(name)
            tolerance = max(1e-15, abs(expected) * 1e-9)
            if abs(actual - expected) > tolerance:
                mismatches.append(f"{name}: 期望 {expected:.9g}，实际 {actual:.9g}")
        if mismatches:
            raise RuntimeError("参数扫描 rpvar 写入校验失败：" + "；".join(mismatches))
        self.event(f"参数扫描 rpvar 写入校验通过：{len(expected_values)} 个值。")

    def _parse_sweep_cache_values(self, output: str) -> dict[str, list[float]]:
        parsed: dict[str, list[float]] = {}
        for raw_line in str(output or "").splitlines():
            match = SWEEP_CACHE_VALUE_RE.search(raw_line.strip())
            if not match:
                continue
            raw_name = match.group(1).lower().replace("-", "_")
            rpvar_name = SWEEP_CACHE_RPVAR_KEYS.get(raw_name)
            if not rpvar_name:
                continue
            parsed.setdefault(rpvar_name, []).append(float(match.group(2)))
        return parsed

    def _parse_sweep_cache_statuses(self, output: str) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for raw_line in str(output or "").splitlines():
            match = SWEEP_CACHE_STATUS_RE.search(raw_line.strip())
            if not match:
                continue
            statuses.append(
                {
                    "role": match.group(1).lower(),
                    "active_exists": int(match.group(2)),
                    "active": float(match.group(3)),
                    "source": match.group(4).lower(),
                    "loaded_mask": int(match.group(5), 16),
                }
            )
        return statuses

    def _verify_sweep_udf_cache(self, combo: dict[str, float], output: str) -> bool:
        parsed = self._parse_sweep_cache_values(output)
        if not parsed:
            return False
        statuses = self._parse_sweep_cache_statuses(output)

        mismatches: list[str] = []
        missing: list[str] = []
        expected_mask = 0
        unknown_keys: list[str] = []
        for name, expected in sorted((key, float(value)) for key, value in combo.items()):
            mask = SWEEP_CACHE_RPVAR_MASKS.get(name)
            if mask is None:
                unknown_keys.append(name)
            else:
                expected_mask |= mask
            values = parsed.get(name)
            if not values:
                missing.append(name)
                continue
            tolerance = max(1e-15, abs(expected) * 1e-9)
            bad_values = [value for value in values if abs(value - expected) > tolerance]
            if bad_values:
                actual_text = ", ".join(f"{value:.9g}" for value in values)
                mismatches.append(f"{name}: expected {expected:.9g}, UDF cache {actual_text}")

        if missing:
            mismatches.append("missing from UDF cache output: " + ", ".join(missing))
        if unknown_keys:
            mismatches.append("unsupported UDF sweep keys: " + ", ".join(unknown_keys))
        if not statuses:
            mismatches.append(
                "missing [sweep] status lines; rebuild and reload the updated libudf before running sweep"
            )
        for status in statuses:
            role = str(status["role"])
            if int(status["active_exists"]) != 1:
                mismatches.append(f"{role}: udf/sweep-active rpvar is missing")
            if float(status["active"]) < 0.5:
                mismatches.append(f"{role}: udf/sweep-active is not enabled ({float(status['active']):.9g})")
            if str(status["source"]).lower() != "rpvars":
                mismatches.append(f"{role}: UDF cache source is {status['source']}, expected rpvars")
            loaded_mask = int(status["loaded_mask"])
            if expected_mask and (loaded_mask & expected_mask) != expected_mask:
                mismatches.append(
                    f"{role}: loaded_mask 0x{loaded_mask:02x} does not include expected 0x{expected_mask:02x}"
                )
        if mismatches:
            raise RuntimeError("UDF sweep cache verification failed: " + "; ".join(mismatches))

        self.event(f"UDF sweep cache verification passed: {len(combo)} values, {len(statuses)} status lines.")
        return True

    @staticmethod
    def _fluent_output_excerpt(output: str, limit: int = 1200) -> str:
        text = clean_text(output)
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n..."

    def _raise_on_fluent_error_output(self, action: str, output: str) -> None:
        if output and CONSOLE_ERROR_RE.search(output):
            raise RuntimeError(f"{action} 返回错误：{self._fluent_output_excerpt(output)}")

    def _execute_file_write_command_if_supported(self, command: str) -> bool:
        lines = [line.strip() for line in str(command or "").splitlines() if line.strip()]
        if len(lines) != 1:
            return False
        match = FILE_WRITE_TUI_RE.match(lines[0])
        if not match:
            return False
        command_name = match.group(1).lower()
        path = match.group(2) or match.group(3) or ""
        if command_name == "write-data":
            self.write_data(path)
        elif command_name == "write-case":
            self.write_case(path)
        else:
            self.write_case_data(path)
        self.event("文件保存命令已通过 PyFluent 文件 API 执行。")
        return True

    def execute_tui(self, command: str) -> None:
        text = str(command or "").strip()
        if not text:
            return
        self.event(f"> {text}")
        if self._execute_file_write_command_if_supported(text):
            return
        self._execute_tui_raw(text)
        self.event("TUI 命令已发送。")

    def _python_exec_scope(self) -> dict[str, Any]:
        session = self._require_session()
        def default_post_path(name: str = "post.png") -> Path:
            base = (self.work_dir or Path.cwd()) / "post"
            base.mkdir(parents=True, exist_ok=True)
            path = Path(clean_entry(name) or "post.png")
            if not path.is_absolute():
                path = base / path
            return unique_file_path(path.resolve())

        def save_picture_helper(path: str | Path) -> Path:
            target = Path(path)
            return self.save_picture(str(target))

        self._python_scope.update(
            {
                "solver": session,
                "session": session,
                "fluent": session,
                "Path": Path,
                "json": json,
                "time": time,
                "run_tui": self._execute_tui_raw,
                "run_scheme": self._execute_scheme_raw,
                "read_case": self.read_case,
                "read_data": self.read_data,
                "write_case": self.write_case,
                "write_data": self.write_data,
                "write_case_data": self.write_case_data,
                "post_path": self._python_scope.get("post_path", default_post_path),
                "save_picture": self._python_scope.get("save_picture", save_picture_helper),
                "show_image": self._python_scope.get("show_image", lambda path: Path(path)),
                "open_image": self._python_scope.get("open_image", lambda path: Path(path)),
                "refresh_post": self._python_scope.get("refresh_post", lambda: None),
            }
        )
        return self._python_scope

    def execute_python(self, code: str) -> None:
        text = str(code or "").strip()
        if not text:
            return
        scope = self._python_exec_scope()
        self.event(f"py> {text}")
        self.set_status("正在执行 PyFluent")
        with contextlib.redirect_stdout(EmitStream(self.raw)), contextlib.redirect_stderr(
            EmitStream(self.raw, prefix="[stderr] ")
        ):
            try:
                compiled = compile(text, "<pyfluent-lite>", "eval")
            except SyntaxError:
                exec(compile(text, "<pyfluent-lite>", "exec"), scope, scope)
            else:
                result = eval(compiled, scope, scope)
                if result is not None:
                    self.raw(repr(result) + "\n")
        self.set_status("PyFluent 已执行")
        self.event("PyFluent 语句已执行。")

    def execute_on_demand(self, function_name: str, library_name: str = "libudf") -> None:
        target = on_demand_target(function_name, library_name)
        session = self._require_session()
        self.event(f"正在执行 Execute On Demand：{target}")
        self.set_status("正在执行 On Demand")
        errors: list[str] = []

        try:
            self._execute_tui_raw(f'/define/user-defined/execute-on-demand "{target}"')
            self.set_status("On Demand 已执行")
            self.event(f"Execute On Demand 完成：{target}")
            return
        except Exception as error:
            errors.append(f"raw TUI execute-on-demand: {type(error).__name__}: {error}")

        try:
            command = session.settings.setup.user_defined.execute_on_demand
            command(lib_name=target)
            self.set_status("On Demand 已执行")
            self.event(f"Execute On Demand 完成：{target}")
            return
        except Exception as error:
            errors.append(f"settings.setup.user_defined.execute_on_demand: {type(error).__name__}: {error}")

        try:
            session.tui.define.user_defined.execute_on_demand(target)
            self.set_status("On Demand 已执行")
            self.event(f"Execute On Demand 完成：{target}")
            return
        except Exception as error:
            errors.append(f"tui.define.user_defined.execute_on_demand: {type(error).__name__}: {error}")

        raise RuntimeError("无法执行 Execute On Demand：" + " | ".join(errors))

    def start_calculation(self, iterations: int) -> None:
        count = safe_int(iterations, 1, minimum=1)
        self.event(f"开始计算：{count} 步")
        self.set_status("正在计算")
        self._execute_tui_raw(f"/solve/iterate {count}")
        self.set_status("计算完成")
        self.event("计算完成。")

    def stop_calculation(self) -> None:
        session = self._require_session()
        self.event("正在请求停止当前计算...")
        self.set_status("正在请求停止计算")
        errors: list[str] = []

        try:
            interrupt = session.settings.solution.run_calculation.interrupt
            try:
                interrupt(interrupt_at="iteration")
            except TypeError:
                interrupt()
            self.event("已发送停止计算请求。")
            self.set_status("已请求停止计算")
            return
        except Exception as error:
            errors.append(f"settings.solution.run_calculation.interrupt: {type(error).__name__}: {error}")

        for command in ("/solve/interrupt", "/solve/run-calculation/interrupt"):
            try:
                self._execute_tui_raw(command)
                self.event(f"已通过 TUI 发送停止计算请求：{command}")
                self.set_status("已请求停止计算")
                return
            except Exception as error:
                errors.append(f"{command}: {type(error).__name__}: {error}")

        raise RuntimeError("无法发送停止计算请求：" + " | ".join(errors))

    def save_picture(self, file_path: str) -> Path:
        session = self._require_session()
        path = require_path(file_path, "图片保存路径")
        path.parent.mkdir(parents=True, exist_ok=True)
        path = unique_file_path(path)
        self.event(f"正在保存当前图形窗口：{path}")
        self.set_status("正在保存后处理图片")
        errors: list[str] = []

        try:
            session.tui.display.save_picture(str(path))
            self.event(f"图片已保存：{path}")
            self.set_status("后处理图片已保存")
            return path
        except Exception as error:
            errors.append(f"tui.display.save_picture: {type(error).__name__}: {error}")

        try:
            self._execute_tui_raw(f'/display/save-picture "{fluent_path(path)}"')
            self.event(f"图片已保存：{path}")
            self.set_status("后处理图片已保存")
            return path
        except Exception as error:
            errors.append(f"raw TUI save-picture: {type(error).__name__}: {error}")

        raise RuntimeError("无法保存当前图形窗口：" + " | ".join(errors))

    def _results_root(self):
        session = self._require_session()
        try:
            return session.settings.results
        except Exception:
            return session.results

    def _post_collection(self, kind: str):
        paths = {key: path for key, _label, path in POST_OBJECT_TYPES}
        if kind not in paths:
            raise ValueError(f"不支持的后处理对象类型：{kind}")
        path = paths[kind]
        session = self._require_session()
        if path and path[0] in {"parameters", "solution", "setup"}:
            try:
                obj = session.settings
            except Exception as error:
                raise RuntimeError(f"无法访问 Fluent settings 根对象：{type(error).__name__}: {error}") from error
        elif path and path[0] == "results":
            try:
                obj = session.settings
            except Exception as error:
                raise RuntimeError(f"无法访问 Fluent settings 根对象：{type(error).__name__}: {error}") from error
        else:
            obj = self._results_root()
        errors: list[str] = []
        for attr in path:
            try:
                obj = getattr(obj, attr)
            except Exception as error:
                errors.append(f"{attr}: {type(error).__name__}: {error}")
                raise RuntimeError(f"无法访问后处理对象集合 {kind}：" + " | ".join(errors)) from error
        return obj

    def list_post_objects(self, kind: str) -> list[str]:
        collection = self._post_collection(kind)
        errors: list[str] = []
        for label, getter in (
            ("get_object_names", lambda: collection.get_object_names()),
            ("keys", lambda: list(collection.keys())),
            ("list", lambda: collection.list()),
        ):
            try:
                items = getter()
            except Exception as error:
                errors.append(f"{label}: {type(error).__name__}: {error}")
                continue
            if items is None:
                errors.append(f"{label}: returned None")
                continue
            if isinstance(items, str):
                return [line.strip() for line in items.splitlines() if line.strip()]
            try:
                return [str(item) for item in items]
            except TypeError:
                return [str(items)]
        raise RuntimeError(
            f"无法列出{post_object_type_label(kind)}：" + (" | ".join(errors) or "没有可用的列表接口。")
        )

    def _resolve_post_object_name(self, kind: str, ref: str) -> str:
        text = clean_entry(ref)
        if not text:
            raise ValueError("请输入后处理对象名称或编号。")
        items = self.list_post_objects(kind)
        if text.isdigit():
            index = int(text)
            candidates = []
            if 0 <= index < len(items):
                candidates.append(index)
            if 1 <= index <= len(items):
                candidates.append(index - 1)
            for candidate in candidates:
                return items[candidate]
            raise IndexError(f"{post_object_type_label(kind)} 编号超出范围：{text}，当前共有 {len(items)} 个。")
        if text in items:
            return text
        lowered = text.lower()
        for item in items:
            if item.lower() == lowered:
                return item
        return text

    def _post_object(self, kind: str, ref: str):
        collection = self._post_collection(kind)
        name = self._resolve_post_object_name(kind, ref)
        try:
            return name, collection[name]
        except Exception as error:
            raise RuntimeError(
                f"无法获取{post_object_type_label(kind)}“{name}”：{type(error).__name__}: {error}"
            ) from error

    def display_post_object(self, kind: str, ref: str) -> None:
        name, obj = self._post_object(kind, ref)
        if kind == "report_file":
            file_name = self._setting_text(obj, "file_name")
            raise RuntimeError(
                f"Report File “{name}” 是监控输出文件配置，不能显示为图形；"
                f"请使用“导出数据”复制已生成的文件。当前 file_name: {file_name or '<未设置>'}"
            )
        self.event(f"正在显示后处理对象：{post_object_type_label(kind)} / {name}")
        self.set_status("正在显示后处理对象")
        display = self._optional_callable(obj, "display")
        if callable(display):
            display()
            self.set_status("后处理对象已显示")
            self.event(f"后处理对象已显示：{name}")
            return
        render = self._optional_callable(obj, "render")
        if callable(render):
            render()
            self.set_status("后处理对象已显示")
            self.event(f"后处理对象已显示：{name}")
            return
        raise RuntimeError(f"{post_object_type_label(kind)}“{name}”没有可调用的 display/render 接口。")

    def save_post_object_image(self, kind: str, ref: str, file_path: str) -> Path:
        self.display_post_object(kind, ref)
        return self.save_picture(file_path)

    def _post_data_file_candidates(self, target: Path) -> list[Path]:
        candidates: list[Path] = []

        def add(candidate: Path) -> None:
            try:
                resolved = candidate.expanduser().resolve()
            except Exception:
                resolved = candidate.expanduser()
            if resolved not in candidates:
                candidates.append(resolved)

        add(target)
        for base in (target.parent, self.work_dir, Path.cwd()):
            if base is None:
                continue
            add(Path(base) / target.name)
        return candidates

    @staticmethod
    def _file_snapshots(paths: list[Path]) -> dict[Path, tuple[int, int] | None]:
        snapshots: dict[Path, tuple[int, int] | None] = {}
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                snapshots[path] = None
            else:
                snapshots[path] = (stat.st_mtime_ns, stat.st_size)
        return snapshots

    def _find_written_post_data_file(
        self, target: Path, snapshots: dict[Path, tuple[int, int] | None]
    ) -> Path | None:
        deadline = time.time() + 3.0
        while True:
            for candidate, before in snapshots.items():
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                changed = before is None or before != (stat.st_mtime_ns, stat.st_size)
                if stat.st_size <= 0 or not changed:
                    continue
                if candidate != target:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, target)
                    self.event(f"Fluent 将数据写到了 {candidate}，已复制到目标路径：{target}")
                return target
            if time.time() >= deadline:
                return None
            time.sleep(0.1)

    @staticmethod
    def _resolve_object_path(root: Any, attrs: tuple[str, ...]) -> Any | None:
        obj = root
        for attr in attrs:
            if obj is None:
                return None
            try:
                obj = getattr(obj, attr)
                continue
            except Exception:
                pass
            try:
                obj = obj[attr]
                continue
            except Exception:
                return None
        return obj

    def _named_child(self, parent: Any, name: str) -> Any | None:
        for getter in (
            lambda: parent[name],
            lambda: self._optional_callable(parent, "get")(name) if self._optional_callable(parent, "get") else None,
            lambda: self._optional_callable(parent, "get_object")(name)
            if self._optional_callable(parent, "get_object")
            else None,
            lambda: self._optional_attr(parent, name),
        ):
            try:
                child = getter()
            except Exception:
                continue
            if child is not None:
                return child
        return None

    def _export_post_object_via_datamodel(self, kind: str, name: str, path_text: str) -> None:
        if kind != "xy_plot":
            raise RuntimeError("Datamodel ExportData 目前仅用于 XY 图。")
        session = self._require_session()
        roots: list[tuple[str, Any]] = []
        for attr in ("datamodel", "flicing"):
            try:
                root = getattr(session, attr)
            except Exception:
                continue
            if root is not None:
                roots.append((attr, root))
        for label, root in list(roots):
            nested = self._resolve_object_path(root, ("Root",))
            if nested is not None:
                roots.append((f"{label}.Root", nested))

        chains = (
            ("Case", "Results", "Graphics", "XYPlot"),
            ("Root", "Case", "Results", "Graphics", "XYPlot"),
            ("Results", "Graphics", "XYPlot"),
            ("Graphics", "XYPlot"),
        )
        errors: list[str] = []
        for root_label, root in roots:
            for chain in chains:
                collection = self._resolve_object_path(root, chain)
                if collection is None:
                    continue
                plot = self._named_child(collection, name)
                if plot is None:
                    continue
                for method_name in ("ExportData", "export_data"):
                    method = self._optional_callable(plot, method_name)
                    if not callable(method):
                        continue
                    for call_label, call in (
                        ("FileName", lambda: method(FileName=path_text)),
                        ("file_name", lambda: method(file_name=path_text)),
                        ("filename", lambda: method(filename=path_text)),
                        ("positional", lambda: method(path_text)),
                    ):
                        try:
                            call()
                            return
                        except TypeError as error:
                            errors.append(
                                f"{root_label}.{'.'.join(chain)}.{method_name}({call_label}): "
                                f"{type(error).__name__}: {error}"
                            )
                        except Exception as error:
                            errors.append(
                                f"{root_label}.{'.'.join(chain)}.{method_name}({call_label}): "
                                f"{type(error).__name__}: {error}"
                            )
        detail = " | ".join(errors[-6:])
        raise RuntimeError(detail or "未找到可调用的 Datamodel XYPlot ExportData 接口。")

    def _export_xy_plot_via_plot_to_file(self, obj: Any, path_text: str) -> None:
        session = self._require_session()
        errors: list[str] = []
        plot_to_file = None
        end_plot_to_file = None
        try:
            file_set = session.tui.plot.file_set
            plot_to_file = self._optional_callable(file_set, "plot_to_file")
            end_plot_to_file = self._optional_callable(file_set, "end_plot_to_file")
        except Exception as error:
            errors.append(f"tui.plot.file_set: {type(error).__name__}: {error}")

        if callable(plot_to_file):
            try:
                plot_to_file(path_text)
                display = self._optional_callable(obj, "display")
                if not callable(display):
                    raise RuntimeError("XY 图没有 display 接口，无法触发 plot-to-file。")
                display()
                return
            except Exception as error:
                errors.append(f"plot.file_set.plot_to_file/display: {type(error).__name__}: {error}")
            finally:
                if callable(end_plot_to_file):
                    with contextlib.suppress(Exception):
                        end_plot_to_file()

        try:
            self._execute_tui_raw(f'/plot/file-set/plot-to-file "{path_text}"')
            display = self._optional_callable(obj, "display")
            if not callable(display):
                raise RuntimeError("XY 图没有 display 接口，无法触发 plot-to-file。")
            display()
            return
        except Exception as error:
            errors.append(f"raw /plot/file-set/plot-to-file: {type(error).__name__}: {error}")
        finally:
            with contextlib.suppress(Exception):
                self._execute_tui_raw("/plot/file-set/end-plot-to-file")

        raise RuntimeError(" | ".join(errors) or "plot-to-file 兜底导出失败。")

    def _setting_text(self, obj: Any, name: str) -> str:
        setting = self._optional_attr(obj, name)
        if setting is None:
            return ""
        for getter in (
            lambda: setting(),
            lambda: setting.get_state(),
        ):
            try:
                value = getter()
            except Exception:
                continue
            text = clean_entry(str(value or ""))
            if text:
                return text
        return ""

    def _report_file_source_candidates(self, file_name: str, target: Path) -> list[Path]:
        raw = Path(file_name)
        candidates: list[Path] = []

        def add(candidate: Path) -> None:
            try:
                resolved = candidate.expanduser().resolve()
            except Exception:
                resolved = candidate.expanduser()
            if resolved not in candidates:
                candidates.append(resolved)

        add(raw)
        if not raw.is_absolute():
            for base in (target.parent, self.work_dir, Path.cwd()):
                if base is not None:
                    add(Path(base) / raw)
        return candidates

    def _export_report_file_object(self, name: str, obj: Any, target: Path) -> Path:
        file_name = self._setting_text(obj, "file_name")
        if not file_name:
            raise RuntimeError(f"Report File “{name}” 未配置 file_name，无法导出已有文件。")

        sources = self._report_file_source_candidates(file_name, target)
        for source in sources:
            try:
                stat = source.stat()
            except OSError:
                continue
            if not source.is_file() or stat.st_size <= 0:
                continue
            if source.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            self.event(f"Report File 已导出：{source} -> {target}")
            return target

        searched = ", ".join(str(path) for path in sources)
        raise RuntimeError(
            f"Report File “{name}” 当前指向 {file_name}，但没有找到已生成的非空文件。"
            f"已检查：{searched}"
        )

    def write_post_object_data(self, kind: str, ref: str, file_path: str) -> Path:
        name, obj = self._post_object(kind, ref)
        path = require_path(file_path, "数据保存路径")
        path.parent.mkdir(parents=True, exist_ok=True)
        path = unique_file_path(path)
        self.event(f"正在导出后处理数据：{post_object_type_label(kind)} / {name} -> {path}")
        self.set_status("正在导出后处理数据")
        candidates = self._post_data_file_candidates(path)
        snapshots = self._file_snapshots(candidates)
        path_texts = list(dict.fromkeys((fluent_path(path), str(path))))

        if kind == "report_file":
            written = self._export_report_file_object(name, obj, path)
            self.set_status("Report File 已导出")
            return written

        attempts: list[tuple[str, Callable[[], Any]]] = []
        writer = self._optional_callable(obj, "write_to_file")
        if callable(writer):
            for path_text in path_texts:
                attempts.extend(
                    [
                        (
                            f"write_to_file(filename=..., path={path_text})",
                            lambda writer=writer, path_text=path_text: writer(filename=path_text),
                        ),
                        (
                            f"write_to_file(file_name=..., path={path_text})",
                            lambda writer=writer, path_text=path_text: writer(file_name=path_text),
                        ),
                        (
                            f"write_to_file(file_name=..., append_data=False, path={path_text})",
                            lambda writer=writer, path_text=path_text: writer(
                                file_name=path_text, append_data=False
                            ),
                        ),
                        (
                            f"write_to_file(filename=..., append_data=False, path={path_text})",
                            lambda writer=writer, path_text=path_text: writer(
                                filename=path_text, append_data=False
                            ),
                        ),
                        (
                            f"write_to_file(path={path_text})",
                            lambda writer=writer, path_text=path_text: writer(path_text),
                        ),
                    ]
                )

        exporter = self._optional_callable(obj, "export_data")
        if callable(exporter):
            for path_text in path_texts:
                attempts.extend(
                    [
                        (
                            f"export_data(file_name=..., path={path_text})",
                            lambda exporter=exporter, path_text=path_text: exporter(file_name=path_text),
                        ),
                        (
                            f"export_data(FileName=..., path={path_text})",
                            lambda exporter=exporter, path_text=path_text: exporter(FileName=path_text),
                        ),
                        (
                            f"export_data(path={path_text})",
                            lambda exporter=exporter, path_text=path_text: exporter(path_text),
                        ),
                    ]
                )

        if kind == "report_definition":
            collection = self._post_collection(kind)
            collection_writer = self._optional_callable(collection, "write_to_file")
            if callable(collection_writer):
                for path_text in path_texts:
                    attempts.extend(
                        [
                            (
                                f"report_definitions.write_to_file(param_name=..., path={path_text})",
                                lambda collection_writer=collection_writer, path_text=path_text: collection_writer(
                                    param_name=name, file_name=path_text, append_data=False
                                ),
                            ),
                            (
                                f"report_definitions.write_to_file(positional, path={path_text})",
                                lambda collection_writer=collection_writer, path_text=path_text: collection_writer(
                                    name, path_text, False
                                ),
                            ),
                        ]
                    )

        if kind == "xy_plot":
            for path_text in path_texts:
                attempts.append(
                    (
                        f"plot.file_set.plot_to_file/display(path={path_text})",
                        lambda obj=obj, path_text=path_text: self._export_xy_plot_via_plot_to_file(obj, path_text),
                    )
                )
                attempts.append(
                    (
                        f"Datamodel XYPlot.ExportData(FileName=..., path={path_text})",
                        lambda path_text=path_text: self._export_post_object_via_datamodel(kind, name, path_text),
                    )
                )

        if not attempts:
            raise RuntimeError(
                f"{post_object_type_label(kind)}“{name}”没有 write_to_file/export_data 导出接口。"
            )

        errors: list[str] = []
        for label, call in attempts:
            try:
                call()
            except Exception as error:
                errors.append(f"{label}: {type(error).__name__}: {error}")
                continue
            written = self._find_written_post_data_file(path, snapshots)
            if written is not None:
                size = written.stat().st_size
                self.set_status("后处理数据已导出")
                self.event(f"后处理数据已导出：{written} ({size} bytes)")
                return written
            errors.append(f"{label}: 调用完成，但没有生成非空数据文件。")

        self.set_status("后处理数据导出失败")
        detail = " | ".join(errors[-10:])
        raise RuntimeError(
            f"{post_object_type_label(kind)}“{name}”数据导出失败：没有生成文件 {path}。"
            f"已尝试 {len(attempts)} 种调用方式。{detail}"
        )

    def _default_post_object_target(self, kind: str, ref: str, action: str) -> str:
        base = (self.work_dir or Path.cwd()) / "post"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", clean_entry(ref) or kind).strip("._") or kind
        suffix = ".png" if action == "save_image" else post_object_data_suffix(kind)
        return str((base / f"{safe_name}{suffix}").resolve())

    def run_post_object_action(self, kind: str, ref: str, action: str, target: str = "") -> None:
        action_text = clean_entry(action) or "display"
        if action_text == "display":
            self.display_post_object(kind, ref)
            return
        if action_text == "save_image":
            self.save_post_object_image(kind, ref, target or self._default_post_object_target(kind, ref, action_text))
            return
        if action_text == "write_data":
            self.write_post_object_data(kind, ref, target or self._default_post_object_target(kind, ref, action_text))
            return
        raise ValueError(f"不支持的后处理动作：{action}")

    def standard_initialize(
        self,
        from_zone_type: str = DEFAULT_INIT_ZONE_TYPE,
        from_zone_name: str = DEFAULT_INIT_ZONE_NAME,
        phase: str = DEFAULT_INIT_PHASE,
    ) -> None:
        zone_type = clean_entry(from_zone_type) or DEFAULT_INIT_ZONE_TYPE
        zone_name = clean_entry(from_zone_name) or DEFAULT_INIT_ZONE_NAME
        phase_name = clean_entry(phase) or DEFAULT_INIT_PHASE
        session = self._require_session()
        self.event(f"正在标准初始化：type={zone_type}, zone={zone_name}, phase={phase_name}")
        self.set_status("正在初始化")
        errors: list[str] = []

        try:
            init = session.settings.solution.initialization
            try:
                init.compute_defaults(
                    from_zone_type=zone_type,
                    from_zone_name=zone_name,
                    phase=phase_name,
                )
            except TypeError as error:
                errors.append(f"settings.compute_defaults(phase=...): {type(error).__name__}: {error}")
                init.compute_defaults(from_zone_type=zone_type, from_zone_name=zone_name)
            init.standard_initialize()
            self.set_status("初始化完成")
            self.event("标准初始化完成。")
            return
        except Exception as error:
            errors.append(f"settings.solution.initialization: {type(error).__name__}: {error}")

        try:
            tui_init = session.tui.solve.initialize
            try:
                tui_init.compute_defaults(zone_type, zone_name, phase_name)
            except TypeError as error:
                errors.append(f"tui.compute_defaults(phase): {type(error).__name__}: {error}")
                tui_init.compute_defaults(zone_type, zone_name)
            tui_init.initialize_flow()
            self.set_status("初始化完成")
            self.event("标准初始化完成。")
            return
        except Exception as error:
            errors.append(f"tui.solve.initialize: {type(error).__name__}: {error}")

        try:
            command = (
                "/solve/initialize/compute-defaults "
                f"{fluent_tui_arg(zone_type)} {fluent_tui_arg(zone_name)} {fluent_tui_arg(phase_name)}\n"
                "/solve/initialize/initialize-flow"
            )
            self._execute_tui_raw(command)
            self.set_status("初始化完成")
            self.event("标准初始化完成。")
            return
        except Exception as error:
            errors.append(f"raw TUI initialize: {type(error).__name__}: {error}")

        raise RuntimeError("无法执行标准初始化：" + " | ".join(errors))

    def load_scm(self, file_path: str) -> None:
        path = require_path(file_path, "SCM 文件")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"SCM 文件不存在：{path}")

        self.event(f"正在加载 SCM：{path}")
        self.set_status("正在加载 SCM")
        expression = f"(load {json.dumps(fluent_path(path))})"
        self._execute_scheme_raw(expression)
        self.set_status("SCM 已加载")
        self.event("SCM 加载完成。")

    def run_workflow(
        self,
        workflow: dict[str, Any],
        context: dict[str, Any] | None = None,
        control_callback: Callable[[], None] | None = None,
        iterate_runner: Callable[[int], None] | None = None,
    ) -> None:
        normalized = normalize_workflow(workflow)
        steps = normalized["steps"]
        if not steps:
            raise ValueError("流程中没有可执行步骤。")
        self.event(f"开始流程：{normalized['name']}（{len(steps)} 步）")
        self.set_status(f"正在执行流程：{normalized['name']}")
        if context:
            self._python_scope.update(context)
        for index, step in enumerate(steps, start=1):
            if control_callback is not None:
                control_callback()
            self.event(f"流程 {index}/{len(steps)}：{workflow_step_summary(step)}")
            step_type = str(step.get("type", "tui"))
            if step_type == "wait":
                seconds = safe_float(step.get("seconds", 0), 0.0, minimum=0.0)
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if control_callback is not None:
                        control_callback()
                    time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
            elif step_type == "python":
                if context:
                    self._python_scope.update(context)
                self.execute_python(str(step.get("code", "")))
            elif step_type == "post_object":
                self.run_post_object_action(
                    str(step.get("kind", "xy_plot")),
                    render_workflow_text(str(step.get("ref", "")), context),
                    str(step.get("action", "display")),
                    render_workflow_text(str(step.get("target", "")), context),
                )
            elif step_type == "execute_on_demand":
                self.execute_on_demand(render_workflow_text(str(step.get("function", "")), context))
            elif step_type == "iterate":
                count = safe_int(step.get("count", 1), 1, minimum=1)
                if iterate_runner is not None:
                    iterate_runner(count)
                else:
                    self.start_calculation(count)
            elif step_type == "initialize":
                self.standard_initialize(
                    str(step.get("from_zone_type", DEFAULT_INIT_ZONE_TYPE)),
                    str(step.get("from_zone_name", DEFAULT_INIT_ZONE_NAME)),
                    str(step.get("phase", DEFAULT_INIT_PHASE)),
                )
            elif step_type == "mesh_check":
                self.execute_tui("/mesh/check")
            elif step_type == "load_scm":
                self.load_scm(render_workflow_text(str(step.get("path", "")), context))
            else:
                self.execute_tui(render_workflow_text(str(step.get("command", "")), context))
            if control_callback is not None:
                control_callback()
            self.event(f"流程 {index}/{len(steps)} 完成。")
        self.set_status(f"流程完成：{normalized['name']}")
        self.event(f"流程完成：{normalized['name']}")

    def define_sweep_rpvars(self, param_grid: dict[str, list[float]]) -> None:
        self._require_session()
        grid = normalize_sweep_param_grid(param_grid)
        commands = sweep_define_commands(grid)
        self.event(f"正在创建参数扫描 rpvar：{len(commands)} 条命令")
        self.set_status("正在创建扫描变量")
        self._execute_scheme_commands_raw(commands)
        self.set_status("扫描变量已创建")
        self.event("参数扫描 rpvar 创建完成。")

    def apply_sweep_combo(
        self,
        combo: dict[str, float],
        combo_index: int = 0,
        total_combos: int = 1,
        reload_params: bool = True,
    ) -> None:
        self._require_session()
        commands = sweep_set_commands(combo)
        label = sweep_combo_label(combo_index)
        self.event(f"正在应用参数组合 {combo_index + 1}/{total_combos}：{label} | {sweep_combo_summary(combo)}")
        self.set_status(f"正在应用参数组合：{label}")
        self._execute_scheme_commands_raw(commands)
        self._verify_sweep_rpvars(combo)
        if reload_params:
            output = self._execute_tui_raw(sweep_reload_command())
            self._raise_on_fluent_error_output("Reload_Sweep_Params", output)
            if not self._verify_sweep_udf_cache(combo, output):
                print_output = self._execute_tui_raw(sweep_print_command())
                self._raise_on_fluent_error_output("Print_Sweep_Params", print_output)
                if not self._verify_sweep_udf_cache(combo, print_output):
                    raise RuntimeError(
                        "Unable to verify UDF sweep cache: no parseable [sweep] output returned. "
                        "Rebuild/reload the updated libudf and check Fluent transcript."
                    )
            self._raise_on_fluent_error_output("刷新 UDF 参数缓存", output)
        self.set_status(f"参数组合已应用：{label}")
        self.event(f"参数组合已应用：{label}")

    def reload_sweep_params(self) -> None:
        self._require_session()
        self.event("正在刷新 UDF 参数缓存。")
        self.set_status("正在刷新扫描参数")
        output = self._execute_tui_raw(sweep_reload_command())
        self._raise_on_fluent_error_output("刷新 UDF 参数缓存", output)
        self.set_status("扫描参数已刷新")
        self.event("UDF 参数缓存刷新完成。")

    def print_sweep_params(self) -> None:
        self._require_session()
        self.event("正在打印当前 UDF 参数缓存。")
        self.set_status("正在打印扫描参数")
        output = self._execute_tui_raw(sweep_print_command())
        self._raise_on_fluent_error_output("打印 UDF 参数缓存", output)
        self.set_status("扫描参数已打印")
        self.event("当前 UDF 参数缓存打印命令已发送。")

    def run_sweep_combo_workflow(
        self,
        param_grid: dict[str, list[float]],
        combo: dict[str, float],
        workflow: dict[str, Any],
        combo_index: int = 0,
        total_combos: int = 1,
        define_first: bool = True,
    ) -> None:
        if define_first:
            self.define_sweep_rpvars(param_grid)
        self.apply_sweep_combo(combo, combo_index, total_combos)
        context = sweep_context(combo, combo_index, total_combos)
        self.run_workflow(workflow, context=context)

    def apply_sweep_combo_from_grid(
        self,
        param_grid: dict[str, list[float]],
        combo: dict[str, float],
        combo_index: int = 0,
        total_combos: int = 1,
    ) -> None:
        self.define_sweep_rpvars(param_grid)
        self.apply_sweep_combo(combo, combo_index, total_combos)

    def run_sweep_workflow(self, param_grid: dict[str, list[float]], workflow: dict[str, Any]) -> None:
        grid = normalize_sweep_param_grid(param_grid)
        combos = list_sweep_combos(grid)
        if not combos:
            raise ValueError("参数网格没有生成任何组合。")
        normalized = normalize_workflow(workflow)
        if not normalized["steps"]:
            raise ValueError("扫描工作流中没有可执行步骤。")
        self.event(f"开始参数扫描：{len(combos)} 个组合，流程：{normalized['name']}")
        self.set_status("正在参数扫描")
        self.define_sweep_rpvars(grid)
        total = len(combos)
        for index, combo in enumerate(combos):
            context = sweep_context(combo, index, total)
            self.event(f"扫描 {context['combo_number']}/{total}：{context['combo_label']} | {context['combo_summary']}")
            self.apply_sweep_combo(combo, index, total)
            self.run_workflow(normalized, context=context)
        self.set_status("参数扫描完成")
        self.event(f"参数扫描完成：{total} 个组合。")

    def _prepare_sweep_combo_python_scope(self, context: dict[str, Any], combo_dir: Path) -> None:
        combo_dir.mkdir(parents=True, exist_ok=True)

        def combo_post_path(name: str = "post.png") -> Path:
            path = Path(clean_entry(name) or "post.png")
            if not path.is_absolute():
                path = combo_dir / path
            return unique_file_path(path.resolve())

        self._python_scope.update(context)
        self._python_scope.update(
            {
                "post_dir": combo_dir,
                "combo_dir": combo_dir,
                "post_path": combo_post_path,
            }
        )

    def _run_sweep_iterations(self, iterations: int) -> None:
        remaining = safe_int(iterations, 0, minimum=0)
        while remaining > 0:
            self._check_sweep_control()
            chunk = min(SWEEP_CALCULATION_CHUNK, remaining)
            self.start_calculation(chunk)
            remaining -= chunk
            self._check_sweep_control()

    def _write_sweep_combo_status(
        self,
        combo_dir: Path,
        status: str,
        context: dict[str, Any],
        detail: str = "",
    ) -> None:
        payload = {
            "status": status,
            "detail": detail,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "combo_index": context.get("combo_index"),
            "combo_label": context.get("combo_label"),
            "combo_summary": context.get("combo_summary"),
            "combo": context.get("combo", {}),
        }
        with contextlib.suppress(Exception):
            combo_dir.mkdir(parents=True, exist_ok=True)
            sweep_status_path(combo_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_sweep_batch(
        self,
        param_grid: dict[str, list[float]],
        combo_indices: list[int],
        init_workflow: dict[str, Any],
        post_workflow: dict[str, Any],
        scan_dir: str,
        base_case: str = "",
        iterations: int = DEFAULT_SWEEP_ITERATIONS,
        launch_config: dict[str, Any] | None = None,
        skip_completed: bool = False,
    ) -> None:
        self.reset_sweep_controls()
        grid = normalize_sweep_param_grid(param_grid)
        combos = list_sweep_combos(grid)
        if not combos:
            raise ValueError("参数网格没有生成任何组合。")

        selected: list[int] = []
        for raw_index in combo_indices:
            index = safe_int(raw_index, -1)
            if 0 <= index < len(combos) and index not in selected:
                selected.append(index)
        if not selected:
            raise ValueError("请先在组合列表中选择至少一个组合。")

        scan_path = require_path(scan_dir, "扫描工作目录")
        scan_path.mkdir(parents=True, exist_ok=True)
        base_path: Path | None = None
        if clean_entry(base_case):
            base_path = require_path(base_case, "基准 Case")
            if not base_path.exists() or not base_path.is_file():
                raise FileNotFoundError(f"基准 Case 不存在：{base_path}")
        if launch_config is not None:
            launch_config = dict(launch_config)
            launch_config.setdefault("work_dir", str(scan_path))
            if base_path is not None and not clean_entry(str(launch_config.get("case_file", ""))):
                launch_config["case_file"] = str(base_path)

        init_steps = normalize_workflow(init_workflow)
        post_steps = normalize_workflow(post_workflow)
        iter_count = safe_int(iterations, DEFAULT_SWEEP_ITERATIONS, minimum=0, maximum=10_000_000)
        total = len(combos)
        batch_total = len(selected)
        success_count = 0
        failed_count = 0
        skipped_count = 0
        session_prepared = False

        def ensure_session_prepared(reason: str) -> None:
            nonlocal session_prepared
            self._ensure_sweep_session(launch_config, reason)
            if not session_prepared and base_path is None:
                self.define_sweep_rpvars(grid)
            session_prepared = True

        self.event(
            f"开始扫描批处理：选中 {batch_total}/{total} 个组合，目录：{scan_path}，"
            f"计算步数：{iter_count}"
        )
        self.set_status("正在扫描批处理")
        self.signals.sweep_progress.emit(0, batch_total, "准备扫描")

        try:
            batch_index = 0
            while batch_index < batch_total:
                combo_index = selected[batch_index]
                combo = combos[combo_index]
                label = sweep_combo_label(combo_index)
                combo_dir = (scan_path / sweep_combo_dir_name(combo_index)).resolve()
                context = sweep_batch_context(
                    combo, combo_index, total, batch_index, batch_total, scan_path, combo_dir, base_path
                )

                if skip_completed:
                    disk_status, disk_detail = read_sweep_disk_status(combo_dir, label)
                    if disk_status == "success":
                        skipped_count += 1
                        detail = f"跳过已完成：{disk_detail or combo_dir}"
                        self.signals.sweep_combo_status.emit(combo_index, "skipped", detail)
                        self.signals.sweep_progress.emit(batch_index + 1, batch_total, f"{label} 已跳过")
                        self.event(f"跳过已完成组合：{label} | {detail}")
                        batch_index += 1
                        continue

                while True:
                    self._sweep_current_index = combo_index
                    try:
                        self._check_sweep_control()
                        ensure_session_prepared(f"执行 {label}")
                        self.signals.sweep_progress.emit(batch_index, batch_total, f"正在执行 {label}")
                        self.signals.sweep_combo_status.emit(combo_index, "running", "正在构建组合文件夹")
                        combo_dir.mkdir(parents=True, exist_ok=True)
                        (combo_dir / "combo_params.json").write_text(
                            json.dumps(context, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        self._prepare_sweep_combo_python_scope(context, combo_dir)
                        self.event(f"扫描 {batch_index + 1}/{batch_total}：{label} | {context['combo_summary']}")
                        self.event(f"组合目录：{combo_dir}")

                        if base_path is not None:
                            self._check_sweep_control()
                            self.signals.sweep_combo_status.emit(combo_index, "running", "正在读取基准 Case")
                            self.read_case(str(base_path))
                            self.define_sweep_rpvars(grid)

                        self._check_sweep_control()
                        self.signals.sweep_combo_status.emit(combo_index, "running", "正在应用参数组合")
                        self.apply_sweep_combo(combo, combo_index, total)

                        if init_steps["steps"]:
                            self.signals.sweep_combo_status.emit(combo_index, "running", f"正在执行初始化流程：{init_steps['name']}")
                            self.run_workflow(
                                init_steps,
                                context=context,
                                control_callback=self._check_sweep_control,
                                iterate_runner=self._run_sweep_iterations,
                            )

                        if iter_count:
                            self.signals.sweep_combo_status.emit(combo_index, "running", f"正在计算 {iter_count} 步")
                            self._run_sweep_iterations(iter_count)

                        if post_steps["steps"]:
                            self.signals.sweep_combo_status.emit(combo_index, "running", f"正在执行后处理流程：{post_steps['name']}")
                            self.run_workflow(
                                post_steps,
                                context=context,
                                control_callback=self._check_sweep_control,
                                iterate_runner=self._run_sweep_iterations,
                            )

                        success_count += 1
                        success_detail = f"完成，结果目录：{combo_dir}"
                        self._write_sweep_combo_status(combo_dir, "success", context, success_detail)
                        self.signals.sweep_combo_status.emit(combo_index, "success", success_detail)
                        self.signals.sweep_progress.emit(batch_index + 1, batch_total, f"{label} 完成")
                        self.event(f"组合完成：{label} -> {combo_dir}")
                        break
                    except SweepRetryRequested:
                        self.signals.sweep_combo_status.emit(combo_index, "running", "正在重试当前组合")
                        self.signals.sweep_progress.emit(batch_index, batch_total, f"正在重试 {label}")
                        self.event(f"正在重试当前组合：{label}")
                        ensure_session_prepared(f"重试 {label}")
                        continue
                    except SweepStopped:
                        self._write_sweep_combo_status(combo_dir, "stopped", context, "已停止")
                        self.signals.sweep_combo_status.emit(combo_index, "stopped", "已停止")
                        self.signals.sweep_progress.emit(batch_index, batch_total, "扫描已停止")
                        status = (
                            f"扫描批处理已停止：成功 {success_count}，跳过 {skipped_count}，失败 {failed_count}，"
                            f"未完成 {batch_total - batch_index}"
                        )
                        self.set_status(status)
                        self.event(status)
                        return
                    except Exception as error:
                        if self._sweep_stop_event.is_set():
                            self._write_sweep_combo_status(combo_dir, "stopped", context, "已停止")
                            self.signals.sweep_combo_status.emit(combo_index, "stopped", "已停止")
                            self.signals.sweep_progress.emit(batch_index, batch_total, "扫描已停止")
                            status = (
                                f"扫描批处理已停止：成功 {success_count}，跳过 {skipped_count}，失败 {failed_count}，"
                                f"未完成 {batch_total - batch_index}"
                            )
                            self.set_status(status)
                            self.event(status)
                            return
                        if self._consume_sweep_retry():
                            if self._is_session_failure(error):
                                self._clear_failed_session(f"当前组合执行时检测到 Fluent 离线：{type(error).__name__}: {error}")
                                session_prepared = False
                            self.signals.sweep_combo_status.emit(combo_index, "running", "正在重试当前组合")
                            self.signals.sweep_progress.emit(batch_index, batch_total, f"正在重试 {label}")
                            self.event(f"当前组合异常后重试：{label} | {type(error).__name__}: {error}")
                            ensure_session_prepared(f"重试 {label}")
                            continue
                        failed_count += 1
                        message = f"{type(error).__name__}: {error}"
                        if self._is_session_failure(error):
                            self._clear_failed_session(f"检测到 Fluent 崩溃或离线，已清理当前 session：{message}")
                            session_prepared = False
                        self._write_sweep_combo_status(combo_dir, "failed", context, message)
                        self.signals.sweep_combo_status.emit(combo_index, "failed", message)
                        self.signals.sweep_progress.emit(batch_index + 1, batch_total, f"{label} 失败")
                        self.event(f"组合失败：{label} | {message}")
                        self.raw(traceback.format_exc() + "\n")
                        break
                batch_index += 1

            status = f"扫描批处理完成：成功 {success_count}，跳过 {skipped_count}，失败 {failed_count}"
            self.set_status(status)
            self.signals.sweep_progress.emit(batch_total, batch_total, status)
            self.event(status)
        finally:
            self._sweep_current_index = None
            self._sweep_pause_event.set()
            self._sweep_stop_event.clear()
            self._sweep_retry_event.clear()

    def read_case(self, file_path: str) -> None:
        self._read_fluent_file(file_path, "case", "read-case", "Case")

    def read_data(self, file_path: str) -> None:
        self._read_fluent_file(file_path, "data", "read-data", "Data")

    def write_case(self, file_path: str) -> None:
        self._write_fluent_file(file_path, "case", "write-case", "Case")

    def write_data(self, file_path: str) -> None:
        self._write_fluent_file(file_path, "data", "write-data", "Data")

    def write_case_data(self, file_path: str) -> None:
        self._write_fluent_file(file_path, "case-data", "write-case-data", "Case/Data")

    def _read_fluent_file(self, file_path: str, file_type: str, tui_name: str, label: str) -> None:
        session = self._require_session()
        path = require_path(file_path, f"{label} 文件")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"{label} 文件不存在：{path}")

        self.event(f"正在读取 {label}：{path}")
        self.set_status(f"正在读取 {label}")
        try:
            session.settings.file.read(file_type=file_type, file_name=str(path))
        except Exception as error:
            self.event(f"settings.file.read 不可用，改用 TUI：{type(error).__name__}: {error}")
            self._execute_tui_raw(f'/file/{tui_name} "{fluent_path(path)}"')
        self.set_status(f"{label} 已读取")
        self.event(f"{label} 读取完成。")

    def _write_fluent_file(self, file_path: str, file_type: str, tui_name: str, label: str) -> None:
        session = self._require_session()
        path = require_path(file_path, f"{label} 保存路径")
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()

        self.event(f"正在保存 {label}：{path}")
        self.set_status(f"正在保存 {label}")
        try:
            session.settings.file.write(file_type=file_type, file_name=str(path))
        except Exception as error:
            self.event(f"settings.file.write 不可用，改用 TUI：{type(error).__name__}: {error}")
            command = f'/file/{tui_name} "{fluent_path(path)}"'
            if existed:
                command += "\nyes"
            self._execute_tui_raw(command)
        self.set_status(f"{label} 已保存")
        self.event(f"{label} 保存完成。")

    def build_and_load_udf(self, source_dir: str) -> None:
        if self.session is None:
            raise RuntimeError("请先启动 Fluent。")
        if self.work_dir is None:
            raise RuntimeError("工作目录未记录，无法部署 libudf。")

        source_path = require_path(source_dir, "UDF 文件夹")
        if not source_path.exists() or not source_path.is_dir():
            raise FileNotFoundError(f"UDF 文件夹不存在：{source_path}")

        c_files, h_files = scan_udf_sources(source_path)
        if not c_files:
            raise ValueError(f"UDF 文件夹中没有 .c 文件：{source_path}")
        check_duplicate_basenames([*c_files, *h_files])

        solver = udf_solver_for_dimension(self.udf_solver)
        targets = parse_udf_targets(os.environ.get("PYFLUENT_LITE_UDF_TARGETS"))
        parallel_node = clean_entry(os.environ.get("PYFLUENT_LITE_UDF_PARALLEL_NODE", "auto")) or "auto"
        arch = clean_entry(os.environ.get("PYFLUENT_LITE_UDF_ARCH", "win64")) or "win64"
        spec = BuildSpec(
            project_dir=source_path,
            build_root=source_path / "libudf",
            source_dir=source_path,
            c_files=c_files,
            header_files=h_files,
            solver=solver,
            targets=targets,
            parallel_node=parallel_node,
            arch=arch,
            fresh=True,
            fluent_root=optional_env_path("PYFLUENT_LITE_FLUENT_ROOT"),
            release_dir=optional_env_path("PYFLUENT_LITE_FLUENT_RELEASE"),
            vsdevcmd=optional_env_path("PYFLUENT_LITE_VSDEVCMD"),
        )

        self.event(f"开始编译 UDF：{source_path}")
        self.event(f"C 文件：{len(c_files)} 个，头文件：{len(h_files)} 个")
        self.event(f"UDF 编译配置：solver={spec.solver}, targets={','.join(spec.targets)}")
        self.set_status("正在编译 UDF")

        def on_build_event(level: str, scope: str | None, message: str) -> None:
            prefix = f"[{scope}] " if scope else ""
            if level == "command":
                self.raw(f"[{now_text()}] > {prefix}{message}\n")
            elif level == "error":
                self.event(f"UDF Error: {prefix}{message}")
            elif level == "warning":
                self.event(f"UDF Warning: {prefix}{message}")
            else:
                self.event(f"UDF: {prefix}{message}")

        summary = build_with_callback(spec, event_callback=on_build_event)
        if not summary.ok:
            self.set_status("UDF 编译失败")
            details: list[str] = []
            for result in summary.target_results:
                if result.success:
                    continue
                details.append(
                    f"{result.version}: returncode={result.returncode}, log={result.log_path}"
                )
                details.extend(result.error_lines[:8])
            raise RuntimeError("UDF 编译失败，请查看上方日志。\n" + "\n".join(details))

        compiled = summary.spec.build_root
        if not compiled.exists() or not compiled.is_dir():
            raise FileNotFoundError(f"编译完成但未找到 libudf：{compiled}")
        self.event("UDF 编译输出：\n" + "\n".join(f"  {path}" for path in sorted(compiled.rglob("libudf.dll"))))

        self.set_status("正在卸载旧 UDF")
        self._unload_udf_if_loaded("libudf")

        deployed = self._deploy_libudf(compiled, source_path, self.work_dir)
        self.event("已部署 libudf：\n" + "\n".join(f"  {path}" for path in deployed))
        self.set_status("正在加载 UDF")
        self._load_udf("libudf")
        self.set_status("UDF 已加载")
        self.event("UDF 编译并加载完成。")

    def _deploy_libudf(self, compiled: Path, source_path: Path, work_path: Path) -> list[Path]:
        deployed: list[Path] = []
        seen: set[str] = set()
        compiled_path = compiled.resolve()
        for target in ((source_path / "libudf").resolve(), (work_path / "libudf").resolve()):
            key = str(target).lower()
            if key in seen:
                continue
            seen.add(key)
            if target == compiled_path:
                deployed.append(target)
                continue
            if target.exists():
                self._remove_tree_with_retries(target)
            shutil.copytree(compiled, target)
            deployed.append(target)
        return deployed

    def _remove_tree_with_retries(self, target: Path) -> None:
        delays = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25)
        last_error: PermissionError | None = None
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                time.sleep(delay)
            try:
                shutil.rmtree(target)
                return
            except FileNotFoundError:
                return
            except PermissionError as error:
                last_error = error
                if attempt < len(delays):
                    self.event(f"旧 libudf 仍被占用，稍后重试 {attempt}/{len(delays) - 1}：{target}")

        raise PermissionError(
            f"无法删除旧 libudf：{target}\n"
            "旧 UDF 的 DLL 可能仍被 Fluent 或系统占用。请确认旧 UDF 已卸载；"
            "如果仍失败，请关闭当前 Fluent 后重新启动并再试。\n"
            f"原始错误：{last_error}"
        ) from last_error

    def _unload_udf_if_loaded(self, library_name: str) -> None:
        try:
            self._call_udf_command("unload", library_name)
            self.event(f"已卸载旧 UDF：{library_name}")
            time.sleep(0.2)
        except Exception as error:
            self.event(f"卸载旧 UDF 时跳过：{type(error).__name__}: {error}")

    def _load_udf(self, library_name: str) -> None:
        self._call_udf_command("load", library_name)
        self.event(f"已加载 UDF：{library_name}")

    def _reload_udf(self, library_name: str) -> None:
        self._unload_udf_if_loaded(library_name)
        self._load_udf(library_name)

    def _call_udf_command(self, command_name: str, library_name: str) -> None:
        if self.session is None:
            raise RuntimeError("Fluent 尚未启动。")
        errors: list[str] = []
        user_defined = None
        try:
            user_defined = self.session.settings.setup.user_defined
        except Exception as error:
            errors.append(f"settings.setup.user_defined: {type(error).__name__}: {error}")

        if user_defined is not None:
            try:
                manage = getattr(user_defined, "manage")
                kwargs = (
                    {"udf_library_name": [library_name]}
                    if command_name == "unload"
                    else {"udf_library_name": library_name}
                )
                getattr(manage, command_name)(**kwargs)
                return
            except Exception as error:
                errors.append(f"manage.{command_name}: {type(error).__name__}: {error}")

            for kwargs in ({"library_name": library_name}, {"udf_library_name": library_name}):
                try:
                    getattr(user_defined, command_name)(**kwargs)
                    return
                except Exception as error:
                    key = next(iter(kwargs))
                    errors.append(f"user_defined.{command_name}({key}=...): {type(error).__name__}: {error}")

        try:
            tui_command = getattr(self.session.tui.define.user_defined, command_name)
            tui_command(library_name)
            return
        except Exception as error:
            errors.append(f"tui.define.user_defined.{command_name}: {type(error).__name__}: {error}")

        joined = " | ".join(errors)
        raise RuntimeError(f"无法执行 UDF {command_name}：{joined}")


def scan_udf_sources(source_dir: Path) -> tuple[list[Path], list[Path]]:
    c_files: list[Path] = []
    h_files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(source_dir):
        current_dir = Path(current_root)
        dirnames[:] = [name for name in dirnames if not should_skip_udf_dir(name)]
        for filename in filenames:
            path = (current_dir / filename).resolve()
            suffix = path.suffix.lower()
            if suffix == ".c":
                c_files.append(path)
            elif suffix in {".h", ".hpp"}:
                h_files.append(path)
    return sorted(c_files), sorted(h_files)


def check_duplicate_basenames(paths: list[Path]) -> None:
    seen: dict[str, Path] = {}
    duplicates: list[str] = []
    for path in paths:
        key = path.name.lower()
        if key in seen:
            duplicates.append(f"{seen[key]} <-> {path}")
        seen[key] = path
    if duplicates:
        raise ValueError("UDF 源文件存在同名文件，外部构建会冲突：\n" + "\n".join(duplicates))


class WorkflowEditorDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        workflow: dict[str, Any] | None = None,
        command_items: list[str] | None = None,
        python_items: list[str] | None = None,
        on_demand_items: list[str] | None = None,
        scm_items: list[str] | None = None,
        preset_groups: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("流程设置")
        self.setObjectName("workflowDialog")
        self.resize(980, 720)
        self.command_items = command_items or list(DEFAULT_COMMAND_PRESETS)
        self.python_items = python_items or list(DEFAULT_PYFLUENT_PRESETS)
        self.on_demand_items = on_demand_items or list(DEFAULT_ON_DEMAND_FUNCTIONS)
        self.scm_items = scm_items or []
        self.preset_groups = preset_groups or {}

        self.name_edit = QLineEdit()
        self.step_list = QListWidget()
        self.step_list.setObjectName("workflowStepList")
        self.step_list.setMinimumWidth(300)
        self.step_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.step_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.step_list.setAlternatingRowColors(True)
        self.type_combo = QComboBox()
        for key, label in WORKFLOW_STEP_TYPES:
            self.type_combo.addItem(label, key)
        self.value_label = QLabel("内容")
        self.value_combo = QComboBox()
        self.value_combo.setEditable(True)
        self.value_open_btn = QToolButton()
        self.value_open_btn.setText("打开")
        self.value_open_btn.setFixedSize(50, 32)
        self.preset_category_label = QLabel("预设类别")
        self.preset_category_combo = QComboBox()
        self.template_label = QLabel("具体预设")
        self.template_combo = QComboBox()
        self.add_preset_step_btn = QPushButton("添加预设")
        self.add_preset_step_btn.setObjectName("primaryButton")
        self.apply_template_btn = QPushButton("套用预设")
        self.insert_template_btn = QPushButton("插入预设")
        self.load_step_file_btn = QPushButton("导入脚本")
        self.export_step_file_btn = QPushButton("导出脚本")
        self.value_editor = QPlainTextEdit()
        self.value_editor.setObjectName("workflowStepEditor")
        self.value_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor_font = QFont("Consolas")
        editor_font.setStyleHint(QFont.StyleHint.Monospace)
        self.value_editor.setFont(editor_font)
        self.value_editor.setTabStopDistance(self.value_editor.fontMetrics().horizontalAdvance(" ") * 4)
        self.value_highlighter = PythonHighlighter(self.value_editor.document())
        self.wait_label = QLabel("等待")
        self.wait_spin = QDoubleSpinBox()
        self.wait_spin.setRange(0.0, 3600.0)
        self.wait_spin.setDecimals(1)
        self.wait_spin.setSingleStep(0.5)
        self.wait_spin.setSuffix(" 秒")
        self.iter_label = QLabel("步数")
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(1, 100000)
        self.iter_spin.setValue(100)
        self.init_zone_type_label = QLabel("区域类型")
        self.init_zone_type_combo = QComboBox()
        self.init_zone_type_combo.setEditable(True)
        self.init_zone_type_combo.addItems(COMMON_INIT_ZONE_TYPES)
        self.init_zone_name_label = QLabel("区域名称")
        self.init_zone_name_combo = QComboBox()
        self.init_zone_name_combo.setEditable(True)
        self.init_zone_name_combo.addItem(DEFAULT_INIT_ZONE_NAME)
        self.init_phase_label = QLabel("相")
        self.init_phase_combo = QComboBox()
        self.init_phase_combo.setEditable(True)
        self.init_phase_combo.addItems(COMMON_INIT_PHASES)
        self.post_kind_label = QLabel("对象类型")
        self.post_kind_combo = QComboBox()
        for key, label, _path in POST_OBJECT_TYPES:
            self.post_kind_combo.addItem(label, key)
        self.post_action_label = QLabel("动作")
        self.post_action_combo = QComboBox()
        self.post_action_combo.addItem("显示", "display")
        self.post_action_combo.addItem("保存图片", "save_image")
        self.post_action_combo.addItem("导出数据", "write_data")
        self.post_ref_label = QLabel("名称/编号")
        self.post_ref_combo = QComboBox()
        self.post_ref_combo.setEditable(True)
        self.post_ref_combo.lineEdit().setPlaceholderText("xy-pressure 或 0")
        self.refresh_post_ref_btn = QPushButton("刷新列表")
        self.refresh_post_ref_btn.setToolTip("从当前 Fluent 会话读取这种后处理对象，并填入下拉框。")
        self.post_target_label = QLabel("输出")
        self.post_target_edit = QLineEdit()
        self.post_target_edit.setPlaceholderText("可用 {combo_label}，留空按动作自动命名")

        self.add_step_btn = QPushButton("添加步骤")
        self.add_step_btn.setObjectName("primaryButton")
        self.update_step_btn = QPushButton("更新步骤")
        self.update_step_btn.setObjectName("primaryButton")
        self.duplicate_step_btn = QPushButton("复制步骤")
        self.remove_step_btn = QPushButton("删除步骤")
        self.remove_step_btn.setObjectName("dangerButton")
        self.move_up_btn = QPushButton("上移")
        self.move_down_btn = QPushButton("下移")
        self.current_step_label = QLabel("未选择步骤")
        self.current_step_label.setObjectName("currentStepBadge")

        self._build_ui()
        self._connect()
        self._load_workflow(workflow or {"name": "", "steps": []})
        self._sync_editor()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("workflowHeader")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setHorizontalSpacing(10)
        header_layout.addWidget(QLabel("流程名称"), 0, 0)
        header_layout.addWidget(self.name_edit, 0, 1)
        header_layout.addWidget(self.current_step_label, 0, 2)
        header_layout.setColumnStretch(1, 1)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        layout.addWidget(splitter, 1)

        step_box = QGroupBox("流程步骤")
        step_layout = QVBoxLayout(step_box)
        step_layout.setContentsMargins(10, 18, 10, 10)
        step_layout.setSpacing(8)
        step_layout.addWidget(self.step_list, 1)

        step_ops = QGridLayout()
        step_ops.setHorizontalSpacing(8)
        step_ops.setVerticalSpacing(8)
        step_ops.addWidget(self.move_up_btn, 0, 0)
        step_ops.addWidget(self.move_down_btn, 0, 1)
        step_ops.addWidget(self.duplicate_step_btn, 1, 0)
        step_ops.addWidget(self.remove_step_btn, 1, 1)
        step_layout.addLayout(step_ops)
        step_hint = QLabel("可拖拽步骤排序，也可以用上移/下移微调。")
        step_hint.setObjectName("mutedLabel")
        step_hint.setWordWrap(True)
        step_layout.addWidget(step_hint)
        splitter.addWidget(step_box)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 620])

        preset_box = QGroupBox("从预设添加")
        preset_layout = QGridLayout(preset_box)
        preset_layout.setContentsMargins(10, 18, 10, 10)
        preset_layout.setHorizontalSpacing(8)
        preset_layout.setVerticalSpacing(8)
        preset_layout.addWidget(self.preset_category_label, 0, 0)
        preset_layout.addWidget(self.preset_category_combo, 0, 1, 1, 3)
        preset_layout.addWidget(self.template_label, 1, 0)
        preset_layout.addWidget(self.template_combo, 1, 1, 1, 3)
        preset_layout.addWidget(self.add_preset_step_btn, 2, 1)
        preset_layout.addWidget(self.apply_template_btn, 2, 2)
        preset_layout.addWidget(self.insert_template_btn, 2, 3)
        preset_layout.setColumnStretch(1, 1)
        right_layout.addWidget(preset_box)

        editor_box = QGroupBox("手动编辑当前步骤")
        editor_layout = QGridLayout(editor_box)
        editor_layout.setContentsMargins(10, 18, 10, 10)
        editor_layout.setHorizontalSpacing(8)
        editor_layout.setVerticalSpacing(8)
        editor_layout.addWidget(QLabel("类型"), 0, 0)
        editor_layout.addWidget(self.type_combo, 0, 1, 1, 5)
        editor_layout.addWidget(self.value_label, 1, 0)
        editor_layout.addWidget(self.value_combo, 1, 1, 1, 3)
        editor_layout.addWidget(self.value_open_btn, 1, 4)
        editor_layout.addWidget(self.value_editor, 2, 0, 1, 6)
        script_button_row = QHBoxLayout()
        script_button_row.addStretch(1)
        script_button_row.addWidget(self.load_step_file_btn)
        script_button_row.addWidget(self.export_step_file_btn)
        editor_layout.addLayout(script_button_row, 3, 0, 1, 6)
        editor_layout.addWidget(self.post_kind_label, 4, 0)
        editor_layout.addWidget(self.post_kind_combo, 4, 1)
        editor_layout.addWidget(self.post_action_label, 4, 2)
        editor_layout.addWidget(self.post_action_combo, 4, 3)
        editor_layout.addWidget(self.post_ref_label, 5, 0)
        editor_layout.addWidget(self.post_ref_combo, 5, 1, 1, 3)
        editor_layout.addWidget(self.refresh_post_ref_btn, 5, 4, 1, 2)
        editor_layout.addWidget(self.post_target_label, 6, 0)
        editor_layout.addWidget(self.post_target_edit, 6, 1, 1, 5)
        editor_layout.addWidget(self.wait_label, 7, 0)
        editor_layout.addWidget(self.wait_spin, 7, 1)
        editor_layout.addWidget(self.iter_label, 7, 2)
        editor_layout.addWidget(self.iter_spin, 7, 3)
        editor_layout.addWidget(self.init_zone_type_label, 8, 0)
        editor_layout.addWidget(self.init_zone_type_combo, 8, 1)
        editor_layout.addWidget(self.init_zone_name_label, 8, 2)
        editor_layout.addWidget(self.init_zone_name_combo, 8, 3, 1, 3)
        editor_layout.addWidget(self.init_phase_label, 9, 0)
        editor_layout.addWidget(self.init_phase_combo, 9, 1, 1, 5)
        action_row = QHBoxLayout()
        action_row.addWidget(self.add_step_btn)
        action_row.addWidget(self.update_step_btn)
        action_row.addStretch(1)
        editor_layout.addLayout(action_row, 10, 0, 1, 6)
        editor_layout.setColumnStretch(1, 1)
        editor_layout.setColumnStretch(3, 1)
        right_layout.addWidget(editor_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _connect(self) -> None:
        self.type_combo.currentIndexChanged.connect(lambda _: self._sync_editor())
        self.preset_category_combo.currentIndexChanged.connect(lambda _: self._refresh_template_combo())
        self.step_list.currentRowChanged.connect(lambda _: self._load_selected_step())
        self.step_list.model().rowsMoved.connect(lambda *_args: self._sync_step_buttons())
        self.template_combo.activated.connect(lambda _: self._apply_template())
        self.post_kind_combo.currentIndexChanged.connect(lambda _: self._post_kind_changed())
        self.refresh_post_ref_btn.clicked.connect(self._refresh_post_object_refs)
        self.add_step_btn.clicked.connect(self._add_step)
        self.update_step_btn.clicked.connect(self._update_step)
        self.duplicate_step_btn.clicked.connect(self._duplicate_step)
        self.remove_step_btn.clicked.connect(self._remove_step)
        self.move_up_btn.clicked.connect(lambda: self._move_step(-1))
        self.move_down_btn.clicked.connect(lambda: self._move_step(1))
        self.value_open_btn.clicked.connect(self._open_editor_value_folder)
        self.add_preset_step_btn.clicked.connect(self._add_preset_step)
        self.apply_template_btn.clicked.connect(self._apply_template)
        self.insert_template_btn.clicked.connect(self._insert_template)
        self.load_step_file_btn.clicked.connect(self._load_step_file)
        self.export_step_file_btn.clicked.connect(self._export_step_file)

    def _load_workflow(self, workflow: dict[str, Any]) -> None:
        normalized = normalize_workflow(workflow)
        self.name_edit.setText(normalized["name"])
        self.step_list.clear()
        for step in normalized["steps"]:
            self._append_step(step)
        if self.step_list.count():
            self.step_list.setCurrentRow(0)
        self._sync_step_buttons()

    def _append_step(self, step: dict[str, Any]) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, step)
        self.step_list.addItem(item)
        self._renumber_steps()

    def _replace_step(self, row: int, step: dict[str, Any]) -> None:
        item = self.step_list.item(row)
        if item is None:
            return
        item.setData(Qt.ItemDataRole.UserRole, step)
        self._renumber_steps()

    def _renumber_steps(self) -> None:
        for row in range(self.step_list.count()):
            item = self.step_list.item(row)
            if item is None:
                continue
            step = item.data(Qt.ItemDataRole.UserRole) or {}
            item.setText(f"{row + 1}. {workflow_step_summary(step)}")

    def _sync_step_buttons(self) -> None:
        row = self.step_list.currentRow()
        count = self.step_list.count()
        has_selection = 0 <= row < count
        self.current_step_label.setText(f"当前第 {row + 1} / {count} 步" if has_selection else f"共 {count} 步")
        self.update_step_btn.setEnabled(has_selection)
        self.duplicate_step_btn.setEnabled(has_selection)
        self.remove_step_btn.setEnabled(has_selection)
        self.move_up_btn.setEnabled(has_selection and row > 0)
        self.move_down_btn.setEnabled(has_selection and row < count - 1)
        self._renumber_steps()

    def _current_step_type(self) -> str:
        return str(self.type_combo.currentData() or "tui")

    def _set_type(self, step_type: str) -> None:
        for index in range(self.type_combo.count()):
            if self.type_combo.itemData(index) == step_type:
                self.type_combo.setCurrentIndex(index)
                return

    def _sync_editor(self) -> None:
        step_type = self._current_step_type()
        self.value_combo.clear()
        placeholder = ""
        if step_type == "tui":
            self.value_combo.addItems(self.command_items)
            placeholder = "/solve/iterate 100"
        elif step_type == "python":
            self.value_combo.addItems(self.python_items)
            placeholder = "solver.tui.solve.iterate(100)"
        elif step_type == "execute_on_demand":
            self.value_combo.addItems(self.on_demand_items)
            placeholder = "Vari_Sources"
        elif step_type == "load_scm":
            self.value_combo.addItems(self.scm_items)
            placeholder = "script.scm"

        line_edit = self.value_combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText(placeholder)
        self.value_editor.setPlaceholderText(placeholder)

        uses_editor = step_type in {"tui", "python"}
        uses_value = step_type in {"execute_on_demand", "load_scm"}
        uses_post = step_type == "post_object"
        uses_wait = step_type == "wait"
        uses_iter = step_type == "iterate"
        uses_init = step_type == "initialize"
        self.value_label.setVisible(uses_value)
        self.value_combo.setVisible(uses_value)
        self.value_open_btn.setVisible(step_type == "load_scm")
        for widget in (
            self.load_step_file_btn,
            self.export_step_file_btn,
            self.value_editor,
        ):
            widget.setVisible(uses_editor)
        for widget in (
            self.template_label,
            self.template_combo,
            self.apply_template_btn,
            self.insert_template_btn,
        ):
            widget.setVisible(True)
        for widget in (
            self.post_kind_label,
            self.post_kind_combo,
            self.post_action_label,
            self.post_action_combo,
            self.post_ref_label,
            self.post_ref_combo,
            self.refresh_post_ref_btn,
            self.post_target_label,
            self.post_target_edit,
        ):
            widget.setVisible(uses_post)
        self.wait_label.setVisible(uses_wait)
        self.wait_spin.setVisible(uses_wait)
        self.iter_label.setVisible(uses_iter)
        self.iter_spin.setVisible(uses_iter)
        for widget in (
            self.init_zone_type_label,
            self.init_zone_type_combo,
            self.init_zone_name_label,
            self.init_zone_name_combo,
            self.init_phase_label,
            self.init_phase_combo,
        ):
            widget.setVisible(uses_init)
        self._refresh_preset_categories()

    def _fallback_preset_groups(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "TUI 预设": [{"label": item, "step": {"type": "tui", "command": item}} for item in self.command_items],
            "PyFluent 预设": [{"label": item, "step": {"type": "python", "code": item}} for item in self.python_items],
            "On Demand": [
                {"label": item, "step": {"type": "execute_on_demand", "function": item}}
                for item in self.on_demand_items
            ],
            "SCM": [{"label": item, "step": {"type": "load_scm", "path": item}} for item in self.scm_items],
            "后处理对象": [
                {"label": "显示 XY 图", "step": {"type": "post_object", "kind": "xy_plot", "action": "display", "ref": "0"}},
                {
                    "label": "保存 XY 图图片",
                    "step": {
                        "type": "post_object",
                        "kind": "xy_plot",
                        "action": "save_image",
                        "ref": "0",
                        "target": "xy_plot.png",
                    },
                },
                {
                    "label": "导出 XY 数据",
                    "step": {
                        "type": "post_object",
                        "kind": "xy_plot",
                        "action": "write_data",
                        "ref": "0",
                        "target": "xy_plot.xy",
                    },
                },
            ],
        }

    def _all_preset_groups(self) -> dict[str, list[dict[str, Any]]]:
        groups = self._fallback_preset_groups()
        for label, items in self.preset_groups.items():
            cleaned = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("steps"), list):
                    steps = normalize_workflow({"name": str(item.get("label", label)), "steps": item["steps"]})["steps"]
                    if steps:
                        cleaned.append(
                            {
                                "label": clean_entry(str(item.get("label", ""))) or f"{len(steps)} 步流程",
                                "steps": steps,
                            }
                        )
                    continue
                if isinstance(item.get("step"), dict):
                    cleaned.append(
                        {
                            "label": clean_entry(str(item.get("label", ""))) or workflow_step_summary(item["step"]),
                            "step": item["step"],
                        }
                    )
            if cleaned:
                groups[label] = cleaned
        return {label: items for label, items in groups.items() if items}

    def _refresh_preset_categories(self) -> None:
        current = self.preset_category_combo.currentText()
        groups = self._all_preset_groups()
        self.preset_category_combo.blockSignals(True)
        self.preset_category_combo.clear()
        for label in groups.keys():
            self.preset_category_combo.addItem(label)
        if current:
            index = self.preset_category_combo.findText(current)
            self.preset_category_combo.setCurrentIndex(index if index >= 0 else 0)
        elif self.preset_category_combo.count():
            self.preset_category_combo.setCurrentIndex(0)
        self.preset_category_combo.blockSignals(False)
        self._refresh_template_combo()

    def _refresh_template_combo(self) -> None:
        current = self.template_combo.currentText()
        groups = self._all_preset_groups()
        category = self.preset_category_combo.currentText()
        items = groups.get(category, [])
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for item in items:
            self.template_combo.addItem(str(item["label"]), item)
        if current:
            index = self.template_combo.findText(current)
            self.template_combo.setCurrentIndex(index if index >= 0 else 0)
        elif self.template_combo.count():
            self.template_combo.setCurrentIndex(0)
        self.template_combo.blockSignals(False)

    def _load_selected_step(self) -> None:
        item = self.step_list.currentItem()
        if item is None:
            self._sync_step_buttons()
            return
        step = item.data(Qt.ItemDataRole.UserRole) or {}
        step_type = str(step.get("type", "tui"))
        self._set_type(step_type)
        self._sync_editor()
        if step_type == "tui":
            self.value_editor.setPlainText(str(step.get("command", "")))
        elif step_type == "python":
            self.value_editor.setPlainText(str(step.get("code", "")))
        elif step_type == "execute_on_demand":
            set_combo_text(self.value_combo, str(step.get("function", "")))
        elif step_type == "load_scm":
            set_combo_text(self.value_combo, str(step.get("path", "")))
        elif step_type == "post_object":
            self._set_post_kind(str(step.get("kind", "xy_plot")))
            self._set_post_action(str(step.get("action", "display")))
            set_combo_text(self.post_ref_combo, str(step.get("ref", "")))
            self.post_target_edit.setText(str(step.get("target", "")))
        elif step_type == "wait":
            self.wait_spin.setValue(safe_float(step.get("seconds", 0), 0.0, minimum=0.0))
        elif step_type == "iterate":
            self.iter_spin.setValue(safe_int(step.get("count", 1), 1, minimum=1))
        elif step_type == "initialize":
            set_combo_text(self.init_zone_type_combo, str(step.get("from_zone_type", DEFAULT_INIT_ZONE_TYPE)))
            set_combo_text(self.init_zone_name_combo, str(step.get("from_zone_name", DEFAULT_INIT_ZONE_NAME)))
            set_combo_text(self.init_phase_combo, str(step.get("phase", DEFAULT_INIT_PHASE)))
        self._sync_step_buttons()

    def _step_from_editor(self) -> dict[str, Any]:
        step_type = self._current_step_type()
        if step_type == "wait":
            return {"type": "wait", "seconds": self.wait_spin.value()}
        if step_type == "execute_on_demand":
            function = combo_text(self.value_combo)
            if not function:
                raise ValueError("请输入 Execute On Demand 函数名。")
            return {"type": "execute_on_demand", "function": function}
        if step_type == "python":
            code = clean_text(self.value_editor.toPlainText())
            if not code:
                raise ValueError("请输入 PyFluent Python 语句。")
            return {"type": "python", "code": code}
        if step_type == "post_object":
            step = normalize_post_object_step(
                {
                    "kind": str(self.post_kind_combo.currentData() or "xy_plot"),
                    "action": str(self.post_action_combo.currentData() or "display"),
                    "ref": self._post_ref_text(),
                    "target": self.post_target_edit.text(),
                }
            )
            if step is None:
                raise ValueError("请输入后处理对象名称或编号。")
            return step
        if step_type == "iterate":
            return {"type": "iterate", "count": self.iter_spin.value()}
        if step_type == "initialize":
            return init_step(
                combo_text(self.init_zone_type_combo),
                combo_text(self.init_zone_name_combo),
                combo_text(self.init_phase_combo),
            )
        if step_type == "mesh_check":
            return {"type": "mesh_check"}
        if step_type == "load_scm":
            path = combo_text(self.value_combo)
            if not path:
                raise ValueError("请输入或选择 SCM 文件。")
            return {"type": "load_scm", "path": path}
        command = clean_text(self.value_editor.toPlainText())
        if not command:
            raise ValueError("请输入 TUI 命令。")
        return {"type": "tui", "command": command}

    def _set_post_kind(self, kind: str) -> None:
        for index in range(self.post_kind_combo.count()):
            if self.post_kind_combo.itemData(index) == kind:
                self.post_kind_combo.setCurrentIndex(index)
                return

    def _set_post_action(self, action: str) -> None:
        for index in range(self.post_action_combo.count()):
            if self.post_action_combo.itemData(index) == action:
                self.post_action_combo.setCurrentIndex(index)
                return

    def _post_ref_text(self) -> str:
        text = combo_text(self.post_ref_combo)
        current_index = self.post_ref_combo.currentIndex()
        if current_index >= 0 and text == self.post_ref_combo.itemText(current_index):
            data = self.post_ref_combo.currentData()
            if data is not None:
                return clean_entry(str(data))
        match = re.match(r"^\s*\d+\s*:\s*(.+)$", text)
        return clean_entry(match.group(1) if match else text)

    def _post_kind_changed(self) -> None:
        self.post_ref_combo.clear()
        self.post_target_edit.clear()

    def _set_post_ref_items(self, items: list[str], current: str) -> None:
        self.post_ref_combo.blockSignals(True)
        self.post_ref_combo.clear()
        for index, name in enumerate(items):
            self.post_ref_combo.addItem(f"{index}: {name}", name)

        selected = -1
        current_text = clean_entry(current)
        lowered = current_text.lower()
        if current_text:
            for index, name in enumerate(items):
                if lowered in {name.lower(), str(index), str(index + 1)}:
                    selected = index
                    break
        if selected >= 0:
            self.post_ref_combo.setCurrentIndex(selected)
        elif current_text:
            self.post_ref_combo.setCurrentText(current_text)
        self.post_ref_combo.blockSignals(False)

    def _refresh_post_object_refs(self) -> None:
        parent = self.parent()
        controller = getattr(parent, "controller", None)
        if controller is None or not getattr(controller, "has_session", False):
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再刷新后处理对象列表。")
            return
        kind = str(self.post_kind_combo.currentData() or "xy_plot")
        current = self._post_ref_text()
        old_text = self.refresh_post_ref_btn.text()
        self.refresh_post_ref_btn.setEnabled(False)
        self.refresh_post_ref_btn.setText("刷新中...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            items = [str(item) for item in (controller.list_post_objects(kind) or [])]
        except Exception as error:
            QMessageBox.warning(self, "刷新失败", f"{type(error).__name__}: {error}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.refresh_post_ref_btn.setText(old_text)
            self.refresh_post_ref_btn.setEnabled(True)

        self._set_post_ref_items(items, current)
        QMessageBox.information(self, "刷新完成", f"已读取 {post_object_type_label(kind)} 对象 {len(items)} 个。")

    def _template_steps(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("steps"), list):
            raw_steps = payload["steps"]
        elif isinstance(payload.get("step"), dict):
            raw_steps = [payload["step"]]
        elif "type" in payload:
            raw_steps = [payload]
        else:
            raw_steps = []
        normalized = normalize_workflow({"name": "preset", "steps": raw_steps})
        return normalized["steps"]

    def _selected_template_steps(self) -> list[dict[str, Any]]:
        return self._template_steps(self.template_combo.currentData())

    def _selected_template_step(self) -> dict[str, Any] | None:
        steps = self._selected_template_steps()
        return steps[0] if steps else None

    def _apply_step_to_editor(self, step: dict[str, Any]) -> None:
        normalized = normalize_workflow({"name": "preset", "steps": [step]})
        if not normalized["steps"]:
            return
        value = normalized["steps"][0]
        step_type = str(value.get("type", "tui"))
        self._set_type(step_type)
        self._sync_editor()
        if step_type == "tui":
            self.value_editor.setPlainText(str(value.get("command", "")))
        elif step_type == "python":
            self.value_editor.setPlainText(str(value.get("code", "")))
        elif step_type == "execute_on_demand":
            set_combo_text(self.value_combo, str(value.get("function", "")))
        elif step_type == "load_scm":
            set_combo_text(self.value_combo, str(value.get("path", "")))
        elif step_type == "post_object":
            self._set_post_kind(str(value.get("kind", "xy_plot")))
            self._set_post_action(str(value.get("action", "display")))
            set_combo_text(self.post_ref_combo, str(value.get("ref", "")))
            self.post_target_edit.setText(str(value.get("target", "")))
        elif step_type == "iterate":
            self.iter_spin.setValue(safe_int(value.get("count", 1), 1, minimum=1))
        elif step_type == "wait":
            self.wait_spin.setValue(safe_float(value.get("seconds", 0), 0.0, minimum=0.0))
        elif step_type == "initialize":
            set_combo_text(self.init_zone_type_combo, str(value.get("from_zone_type", DEFAULT_INIT_ZONE_TYPE)))
            set_combo_text(self.init_zone_name_combo, str(value.get("from_zone_name", DEFAULT_INIT_ZONE_NAME)))
            set_combo_text(self.init_phase_combo, str(value.get("phase", DEFAULT_INIT_PHASE)))

    def _apply_template(self) -> None:
        step = self._selected_template_step()
        if step is None:
            return
        self._apply_step_to_editor(step)
        if self.value_editor.isVisible():
            self.value_editor.setFocus()

    def _add_preset_step(self) -> None:
        steps = self._selected_template_steps()
        if not steps:
            QMessageBox.information(self, "没有预设", "请先选择一个具体预设。")
            return
        start_row = self.step_list.count()
        for step in steps:
            self._append_step(step)
        self.step_list.setCurrentRow(start_row)
        self._sync_step_buttons()

    def _insert_template(self) -> None:
        steps = self._selected_template_steps()
        if not steps:
            return
        step = steps[0]
        step_type = str(step.get("type", ""))
        if len(steps) > 1:
            row = self.step_list.currentRow()
            insert_at = row + 1 if row >= 0 else self.step_list.count()
            for offset, item_step in enumerate(steps):
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, item_step)
                self.step_list.insertItem(insert_at + offset, item)
            self.step_list.setCurrentRow(insert_at)
            self._renumber_steps()
            self._sync_step_buttons()
            return
        if step_type not in {"tui", "python"}:
            self._apply_step_to_editor(step)
            return
        text = str(step.get("code" if step_type == "python" else "command", ""))
        cursor = self.value_editor.textCursor()
        if cursor.position() > 0:
            text = "\n\n" + text
        cursor.insertText(text)
        self.value_editor.setTextCursor(cursor)
        self.value_editor.setFocus()

    def _script_file_filter(self) -> str:
        if self._current_step_type() == "python":
            return "Python (*.py);;All Files (*)"
        return "Fluent Journal/Scheme (*.jou *.scm *.txt);;All Files (*)"

    def _script_fallback_name(self) -> str:
        return "workflow_step.py" if self._current_step_type() == "python" else "workflow_step.jou"

    def _dialog_start(self, fallback_name: str) -> str:
        parent = self.parent()
        if hasattr(parent, "work_dir_edit"):
            try:
                work_dir = combo_text(parent.work_dir_edit)  # type: ignore[attr-defined]
                if work_dir:
                    return str(Path(work_dir).expanduser() / fallback_name)
            except Exception:
                pass
        return str(TOOL_ROOT / fallback_name)

    def _load_step_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入流程步骤脚本",
            self._dialog_start(self._script_fallback_name()),
            self._script_file_filter(),
        )
        if not path:
            return
        try:
            self.value_editor.setPlainText(Path(path).read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            self.value_editor.setPlainText(Path(path).read_text(encoding="gbk"))
        except Exception as error:
            QMessageBox.warning(self, "导入失败", f"{type(error).__name__}: {error}")

    def _export_step_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出流程步骤脚本",
            self._dialog_start(self._script_fallback_name()),
            self._script_file_filter(),
        )
        if not path:
            return
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.value_editor.toPlainText(), encoding="utf-8")
        except Exception as error:
            QMessageBox.warning(self, "导出失败", f"{type(error).__name__}: {error}")

    def _open_editor_value_folder(self) -> None:
        text = combo_text(self.value_combo)
        if not text:
            QMessageBox.information(self, "没有路径", "请先输入 SCM 文件路径。")
            return
        path = Path(text).expanduser()
        parent = self.parent()
        if not path.is_absolute() and hasattr(parent, "work_dir_edit"):
            work_dir = combo_text(parent.work_dir_edit)  # type: ignore[attr-defined]
            if work_dir:
                path = Path(work_dir).expanduser() / path
        folder = path if path.exists() and path.is_dir() else path.parent
        while folder and not folder.exists() and folder != folder.parent:
            folder = folder.parent
        if not folder or not folder.exists():
            QMessageBox.warning(self, "路径不可用", f"找不到可打开的文件夹：{path}")
            return
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception as error:
            QMessageBox.warning(self, "打开失败", f"{type(error).__name__}: {error}")

    def _add_step(self) -> None:
        try:
            step = self._step_from_editor()
        except ValueError as error:
            QMessageBox.warning(self, "步骤不完整", str(error))
            return
        self._append_step(step)
        self.step_list.setCurrentRow(self.step_list.count() - 1)
        self._sync_step_buttons()

    def _update_step(self) -> None:
        row = self.step_list.currentRow()
        if row < 0:
            self._add_step()
            return
        try:
            step = self._step_from_editor()
        except ValueError as error:
            QMessageBox.warning(self, "步骤不完整", str(error))
            return
        self._replace_step(row, step)
        self.step_list.setCurrentRow(row)
        self._sync_step_buttons()

    def _duplicate_step(self) -> None:
        row = self.step_list.currentRow()
        item = self.step_list.currentItem()
        if row < 0 or item is None:
            return
        step = item.data(Qt.ItemDataRole.UserRole) or {}
        try:
            copied = json.loads(json.dumps(step, ensure_ascii=False))
        except (TypeError, ValueError):
            copied = dict(step)
        new_item = QListWidgetItem()
        new_item.setData(Qt.ItemDataRole.UserRole, copied)
        self.step_list.insertItem(row + 1, new_item)
        self._renumber_steps()
        self.step_list.setCurrentRow(row + 1)
        self._sync_step_buttons()

    def _remove_step(self) -> None:
        row = self.step_list.currentRow()
        if row >= 0:
            self.step_list.takeItem(row)
            if self.step_list.count():
                self.step_list.setCurrentRow(min(row, self.step_list.count() - 1))
            self._sync_step_buttons()

    def _move_step(self, direction: int) -> None:
        row = self.step_list.currentRow()
        new_row = row + direction
        if row < 0 or new_row < 0 or new_row >= self.step_list.count():
            return
        item = self.step_list.takeItem(row)
        self.step_list.insertItem(new_row, item)
        self.step_list.setCurrentRow(new_row)
        self._renumber_steps()
        self._sync_step_buttons()

    def workflow(self) -> dict[str, Any]:
        steps = []
        for row in range(self.step_list.count()):
            item = self.step_list.item(row)
            if item is not None:
                steps.append(item.data(Qt.ItemDataRole.UserRole))
        return normalize_workflow({"name": self.name_edit.text(), "steps": steps})

    def accept(self) -> None:
        workflow = self.workflow()
        if not workflow["steps"]:
            QMessageBox.warning(self, "流程为空", "请至少添加一个流程步骤。")
            return
        self.name_edit.setText(workflow["name"])
        super().accept()


class PythonHighlighter(QSyntaxHighlighter):
    KEYWORDS = {
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    }
    BUILTINS = {
        "dict",
        "enumerate",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "Path",
        "print",
        "range",
        "repr",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
    }

    def __init__(self, document) -> None:
        super().__init__(document)
        self.keyword_format = self._format("#93c5fd", bold=True)
        self.builtin_format = self._format("#c4b5fd")
        self.string_format = self._format("#86efac")
        self.comment_format = self._format("#94a3b8", italic=True)
        self.number_format = self._format("#fbbf24")
        self.decorator_format = self._format("#f472b6")
        self.name_format = self._format("#67e8f9", bold=True)
        self.keyword_pattern = re.compile(
            r"\b(" + "|".join(re.escape(item) for item in sorted(self.KEYWORDS)) + r")\b"
        )
        self.builtin_pattern = re.compile(
            r"\b(" + "|".join(re.escape(item) for item in sorted(self.BUILTINS)) + r")\b"
        )
        self.string_pattern = re.compile(
            r"(?i)(?:[rubf]{0,3})(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
        )
        self.comment_pattern = re.compile(r"#.*$")
        self.number_pattern = re.compile(r"\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\b")
        self.decorator_pattern = re.compile(r"^\s*@\w+(?:\.\w+)*")
        self.definition_pattern = re.compile(r"\b(?:def|class)\s+([A-Za-z_]\w*)")

    def _format(self, color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _apply_matches(self, pattern: re.Pattern[str], text: str, fmt: QTextCharFormat) -> None:
        for match in pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), fmt)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        self._apply_matches(self.keyword_pattern, text, self.keyword_format)
        self._apply_matches(self.builtin_pattern, text, self.builtin_format)
        self._apply_matches(self.number_pattern, text, self.number_format)
        self._apply_matches(self.string_pattern, text, self.string_format)
        self._apply_matches(self.decorator_pattern, text, self.decorator_format)
        for match in self.definition_pattern.finditer(text):
            start, end = match.span(1)
            self.setFormat(start, end - start, self.name_format)
        self._apply_matches(self.comment_pattern, text, self.comment_format)


class CommandButtonEditorDialog(QDialog):
    def __init__(self, parent: QWidget, button: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑命令按钮")
        self.resize(760, 520)
        default_button = DEFAULT_COMMAND_BUTTONS[0] if DEFAULT_COMMAND_BUTTONS else {"name": "", "mode": "tui", "command": ""}
        data = normalize_command_button(button or default_button)

        self.name_edit = QLineEdit(data["name"])
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("TUI", "tui")
        self.mode_combo.addItem("PyFluent", "python")
        self.mode_combo.setCurrentIndex(1 if data["mode"] == "python" else 0)
        self.template_combo = QComboBox()
        self.apply_template_btn = QPushButton("替换命令")
        self.insert_template_btn = QPushButton("插入模板")
        self.load_command_file_btn = QPushButton("导入脚本")
        self.export_command_file_btn = QPushButton("导出脚本")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("commandButtonEditor")
        self.editor.setPlainText(data["command"])
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = PythonHighlighter(self.editor.document())

        self._build_ui()
        self._connect()
        self._refresh_templates()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("按钮名称"), 0, 0)
        form.addWidget(self.name_edit, 0, 1, 1, 3)
        form.addWidget(QLabel("模式"), 1, 0)
        form.addWidget(self.mode_combo, 1, 1)
        form.addWidget(QLabel("模板"), 2, 0)
        form.addWidget(self.template_combo, 2, 1, 1, 2)
        form.addWidget(self.apply_template_btn, 2, 3)
        form.addWidget(self.insert_template_btn, 2, 4)
        form.addWidget(self.load_command_file_btn, 3, 3)
        form.addWidget(self.export_command_file_btn, 3, 4)
        form.setColumnStretch(2, 1)
        layout.addLayout(form)

        helper = QLabel("TUI 按钮会发送到 Fluent TUI；PyFluent 按钮会在当前 session 中执行 Python，可写多行脚本。")
        helper.setObjectName("mutedLabel")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _connect(self) -> None:
        self.mode_combo.currentIndexChanged.connect(lambda _: self._refresh_templates())
        self.apply_template_btn.clicked.connect(self._apply_template)
        self.insert_template_btn.clicked.connect(self._insert_template)
        self.load_command_file_btn.clicked.connect(self._load_file)
        self.export_command_file_btn.clicked.connect(self._export_file)

    def _mode(self) -> str:
        return str(self.mode_combo.currentData() or "tui")

    def _template_items(self) -> list[str]:
        return list(DEFAULT_PYFLUENT_PRESETS if self._mode() == "python" else DEFAULT_COMMAND_PRESETS)

    def _refresh_templates(self) -> None:
        current = self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for item in self._template_items():
            self.template_combo.addItem(item)
        if current:
            self.template_combo.setCurrentText(current)
        self.template_combo.blockSignals(False)
        line_text = "输入 PyFluent Python，可多行" if self._mode() == "python" else "输入 Fluent TUI 命令，可多行"
        self.editor.setPlaceholderText(line_text)

    def _selected_template(self) -> str:
        return self.template_combo.currentText()

    def _apply_template(self) -> None:
        self.editor.setPlainText(self._selected_template())
        self.editor.setFocus()

    def _insert_template(self) -> None:
        cursor = self.editor.textCursor()
        text = self._selected_template()
        if cursor.position() > 0:
            text = "\n\n" + text
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _dialog_start(self, fallback_name: str) -> str:
        parent = self.parent()
        if hasattr(parent, "work_dir_edit"):
            try:
                work_dir = combo_text(parent.work_dir_edit)  # type: ignore[attr-defined]
                if work_dir:
                    return str(Path(work_dir).expanduser() / fallback_name)
            except Exception:
                pass
        return str(TOOL_ROOT / fallback_name)

    def _file_filter(self) -> str:
        if self._mode() == "python":
            return "Python (*.py);;All Files (*)"
        return "Fluent Journal/Scheme (*.jou *.scm *.txt);;All Files (*)"

    def _fallback_name(self) -> str:
        return "command_button.py" if self._mode() == "python" else "command_button.jou"

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入脚本",
            self._dialog_start(self._fallback_name()),
            self._file_filter(),
        )
        if not path:
            return
        try:
            self.editor.setPlainText(Path(path).read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            self.editor.setPlainText(Path(path).read_text(encoding="gbk"))
        except Exception as error:
            QMessageBox.warning(self, "导入失败", f"{type(error).__name__}: {error}")

    def _export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出脚本",
            self._dialog_start(self._fallback_name()),
            self._file_filter(),
        )
        if not path:
            return
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.editor.toPlainText(), encoding="utf-8")
        except Exception as error:
            QMessageBox.warning(self, "导出失败", f"{type(error).__name__}: {error}")

    def button_data(self) -> dict[str, str]:
        return normalize_command_button(
            {"name": self.name_edit.text(), "mode": self._mode(), "command": self.editor.toPlainText()}
        )

    def accept(self) -> None:
        data = self.button_data()
        if not data["command"]:
            QMessageBox.warning(self, "命令为空", "请为这个按钮填写 TUI 命令或 PyFluent 代码。")
            return
        if data["mode"] == "python":
            try:
                compile(data["command"], f"<command-button:{data['name']}>", "exec")
            except SyntaxError as error:
                QMessageBox.warning(self, "语法错误", f"{error.msg}\n第 {error.lineno} 行，第 {error.offset or 0} 列")
                return
        self.name_edit.setText(data["name"])
        super().accept()


class SweepButtonEditorDialog(QDialog):
    def __init__(self, parent: QWidget, button: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑扫描模块按钮")
        self.resize(480, 220)
        data = normalize_sweep_button(button or DEFAULT_SWEEP_BUTTONS[0])

        self.name_edit = QLineEdit(data["name"])
        self.action_combo = QComboBox()
        for key, label in SWEEP_BUTTON_ACTIONS:
            self.action_combo.addItem(label, key)
        for index in range(self.action_combo.count()):
            if self.action_combo.itemData(index) == data["action"]:
                self.action_combo.setCurrentIndex(index)
                break

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        form = QFormLayout()
        form.addRow("按钮名称", self.name_edit)
        form.addRow("模块动作", self.action_combo)
        layout.addLayout(form)

        helper = QLabel("模块按钮绑定 tools/sweep.py 的参数扫描动作；名称和动作都可以单独调整。")
        helper.setObjectName("mutedLabel")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def button_data(self) -> dict[str, str]:
        return normalize_sweep_button(
            {"name": self.name_edit.text(), "action": str(self.action_combo.currentData() or "")}
        )

    def accept(self) -> None:
        data = self.button_data()
        self.name_edit.setText(data["name"])
        super().accept()


class PlotButtonEditorDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        button: dict[str, Any] | None = None,
        templates: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑绘图按钮")
        self.resize(820, 620)
        self.templates = templates or default_plot_buttons()

        data = normalize_plot_button(button or {"name": "新绘图", "code": self.templates[0]["code"]})
        self.name_edit = QLineEdit(data["name"])
        self.template_combo = QComboBox()
        for item in self.templates:
            self.template_combo.addItem(item["name"])
        self.apply_template_btn = QPushButton("替换代码")
        self.insert_template_btn = QPushButton("插入模板")
        self.load_py_btn = QPushButton("导入 .py")
        self.export_py_btn = QPushButton("导出 .py")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("plotCodeEditor")
        self.editor.setPlainText(data["code"])
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = PythonHighlighter(self.editor.document())

        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        form = QFormLayout()
        form.addRow("按钮名称", self.name_edit)
        layout.addLayout(form)

        toolbar = QGridLayout()
        toolbar.setHorizontalSpacing(8)
        toolbar.setVerticalSpacing(8)
        toolbar.addWidget(QLabel("模板"), 0, 0)
        toolbar.addWidget(self.template_combo, 0, 1, 1, 2)
        toolbar.addWidget(self.apply_template_btn, 0, 3)
        toolbar.addWidget(self.insert_template_btn, 0, 4)
        toolbar.addWidget(self.load_py_btn, 1, 3)
        toolbar.addWidget(self.export_py_btn, 1, 4)
        toolbar.setColumnStretch(1, 1)
        layout.addLayout(toolbar)

        helper = QLabel(
            "可用对象：solver/session/fluent、run_tui(command)、run_scheme(expr)、post_dir、post_path(name)、"
            "save_picture(path)、show_image(path)、refresh_post()"
        )
        helper.setObjectName("mutedLabel")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _connect(self) -> None:
        self.apply_template_btn.clicked.connect(self._apply_template)
        self.insert_template_btn.clicked.connect(self._insert_template)
        self.load_py_btn.clicked.connect(self._load_file)
        self.export_py_btn.clicked.connect(self._export_file)

    def _selected_template_code(self) -> str:
        index = max(0, self.template_combo.currentIndex())
        if index >= len(self.templates):
            index = 0
        return self.templates[index]["code"]

    def _apply_template(self) -> None:
        self.editor.setPlainText(self._selected_template_code())
        self.editor.setFocus()

    def _insert_template(self) -> None:
        cursor = self.editor.textCursor()
        text = self._selected_template_code()
        if cursor.position() > 0:
            text = "\n\n" + text
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _dialog_start(self, fallback_name: str) -> str:
        parent = self.parent()
        if hasattr(parent, "_selected_post_dir"):
            try:
                return str(parent._selected_post_dir() / fallback_name)  # type: ignore[attr-defined]
            except Exception:
                pass
        return str(TOOL_ROOT / fallback_name)

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 Python 脚本",
            self._dialog_start("post_button.py"),
            "Python (*.py);;All Files (*)",
        )
        if not path:
            return
        try:
            self.editor.setPlainText(Path(path).read_text(encoding="utf-8"))
        except Exception as error:
            QMessageBox.warning(self, "导入失败", f"{type(error).__name__}: {error}")

    def _export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Python 脚本",
            self._dialog_start("post_button.py"),
            "Python (*.py);;All Files (*)",
        )
        if not path:
            return
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.editor.toPlainText(), encoding="utf-8")
        except Exception as error:
            QMessageBox.warning(self, "导出失败", f"{type(error).__name__}: {error}")

    def button_data(self) -> dict[str, str]:
        return normalize_plot_button({"name": self.name_edit.text(), "code": self.editor.toPlainText()})

    def accept(self) -> None:
        data = self.button_data()
        if not data["code"]:
            QMessageBox.warning(self, "脚本为空", "请为这个绘图按钮填写 Python 代码。")
            return
        try:
            compile(data["code"], f"<plot-button:{data['name']}>", "exec")
        except SyntaxError as error:
            QMessageBox.warning(self, "语法错误", f"{error.msg}\n第 {error.lineno} 行，第 {error.offset or 0} 列")
            return
        self.name_edit.setText(data["name"])
        super().accept()


class PostImageWindow(QDialog):
    def __init__(self, parent: QWidget, image_path: str | Path) -> None:
        super().__init__(parent)
        self.path = Path(image_path)
        self.setWindowTitle(f"后处理图形 - {self.path.name}")
        self.resize(900, 640)
        self.image_label = QLabel()
        self.image_label.setObjectName("postPopupImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(520, 360)
        self.image_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.path_label = QLabel(str(self.path))
        self.path_label.setObjectName("mutedLabel")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pixmap = QPixmap(str(self.path))
        self._build_ui()
        self._update_pixmap()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.path_label)
        layout.addWidget(self.image_label, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _update_pixmap(self) -> None:
        if self.pixmap.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"无法显示图片\n{self.path}")
            return
        scaled = self.pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setText("")
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_pixmap)


class PostResultsWindow(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_window: Any = parent
        self.setWindowTitle("后处理结果预览")
        self.resize(1120, 760)
        self.image_paths: list[Path] = []
        self.current_path: Path | None = None
        self.pixmap = QPixmap()

        self.dir_label = QLabel()
        self.dir_label.setObjectName("postPathLabel")
        self.dir_label.setWordWrap(True)
        self.dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.refresh_btn = QPushButton("刷新")
        self.open_dir_btn = QPushButton("打开目录")
        self.popout_btn = QPushButton("弹出图片")
        self.copy_path_btn = QPushButton("复制路径")
        self.image_list = QListWidget()
        self.image_list.setObjectName("postImageList")
        self.image_list.setAlternatingRowColors(True)
        self.image_list.setUniformItemSizes(True)
        self.image_list.setMinimumWidth(280)
        self.preview = QLabel("暂无图片")
        self.preview.setObjectName("postPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview.setMinimumSize(560, 420)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail_label = QLabel("未选择图片")
        self.detail_label.setObjectName("postPathLabel")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._build_ui()
        self._connect()
        self.refresh_from_paths(list(getattr(self.parent_window, "post_image_paths", [])))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(self.dir_label, 1)
        top_row.addWidget(self.refresh_btn)
        top_row.addWidget(self.open_dir_btn)
        top_row.addWidget(self.popout_btn)
        top_row.addWidget(self.copy_path_btn)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)
        list_title = QLabel("图片列表")
        list_title.setObjectName("sectionTitle")
        list_layout.addWidget(list_title)
        list_layout.addWidget(self.image_list, 1)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        preview_title = QLabel("结果预览")
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview, 1)
        preview_layout.addWidget(self.detail_label)

        splitter.addWidget(list_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 760])
        layout.addWidget(splitter, 1)

    def _connect(self) -> None:
        self.refresh_btn.clicked.connect(self.refresh)
        self.open_dir_btn.clicked.connect(self._open_directory)
        self.popout_btn.clicked.connect(self._popout_current)
        self.copy_path_btn.clicked.connect(self._copy_current_path)
        self.image_list.currentRowChanged.connect(lambda _: self._show_selected())
        self.image_list.itemDoubleClicked.connect(lambda _: self._popout_current())

    def refresh(self) -> None:
        if hasattr(self.parent_window, "_refresh_post_results"):
            self.parent_window._refresh_post_results(update_window=False)
        self.refresh_from_paths(list(getattr(self.parent_window, "post_image_paths", [])))

    def refresh_from_paths(self, paths: list[Path]) -> None:
        directory = self.parent_window._selected_post_dir()
        self.dir_label.setText(f"目录：{directory}    图片 {len(paths)} 张")
        previous = str(self.current_path or getattr(self.parent_window, "current_post_image_path", "") or "")
        self.image_paths = list(paths)
        self.image_list.blockSignals(True)
        self.image_list.clear()
        selected_row = 0
        for path in self.image_paths:
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
            item = QListWidgetItem(f"{path.name}\n{stat.st_size / 1024:.1f} KB    {modified}")
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.image_list.addItem(item)
            if str(path) == previous:
                selected_row = self.image_list.count() - 1
        self.image_list.blockSignals(False)
        if self.image_paths:
            self.image_list.setCurrentRow(selected_row)
            self._show_selected()
        else:
            self.current_path = None
            self.pixmap = QPixmap()
            self.preview.setPixmap(QPixmap())
            self.preview.setText("暂无图片")
            self.detail_label.setText("未选择图片")
        self._update_buttons()

    def _selected_path(self) -> Path | None:
        item = self.image_list.currentItem()
        if item is None:
            return None
        value = str(item.data(Qt.ItemDataRole.UserRole) or "")
        return Path(value) if value else None

    def _show_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            self.current_path = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("暂无图片")
            self.detail_label.setText("未选择图片")
            self._update_buttons()
            return

        self.current_path = path
        self.parent_window.current_post_image_path = path
        self.pixmap = QPixmap(str(path))
        if self.pixmap.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"无法显示图片\n{path}")
        else:
            self._update_pixmap()
        stat = path.stat() if path.exists() else None
        detail = path.name
        if stat is not None:
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            detail += f"    {stat.st_size / 1024:.1f} KB    {modified}"
        self.detail_label.setText(f"{detail}\n{path}")
        self.detail_label.setToolTip(str(path))
        self._update_buttons()

    def _update_pixmap(self) -> None:
        if self.pixmap.isNull():
            return
        scaled = self.pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setText("")
        self.preview.setPixmap(scaled)

    def _update_buttons(self) -> None:
        has_image = self.current_path is not None
        self.popout_btn.setEnabled(has_image)
        self.copy_path_btn.setEnabled(has_image)

    def _open_directory(self) -> None:
        directory = self.parent_window._selected_post_dir()
        try:
            os.startfile(str(directory))  # type: ignore[attr-defined]
        except Exception as error:
            QMessageBox.warning(self, "打开失败", f"{type(error).__name__}: {error}")

    def _popout_current(self) -> None:
        if self.current_path is None:
            QMessageBox.information(self, "没有图片", "请先选择一张图片。")
            return
        self.parent_window._open_post_image_window(str(self.current_path))

    def _copy_current_path(self) -> None:
        if self.current_path is None:
            QMessageBox.information(self, "没有图片", "请先选择一张图片。")
            return
        QApplication.clipboard().setText(str(self.current_path))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_pixmap)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_application_font(app)
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setMinimumSize(900, 680)

        self.settings = QSettings("pyfluent_qt_lite", "pyfluent_qt_lite")
        self.app_signals = AppSignals()
        self.window_signals = WindowSignals()
        self.controller = FluentController(self.app_signals)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyfluent-lite")
        self.interrupt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyfluent-lite-stop")
        self.scan_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyfluent-lite-scan")
        self.io_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyfluent-lite-io")
        self.busy = False
        self.current_task_label = ""
        self._last_error_dialog_at = 0.0
        self._error_dialog_open = False
        self.console_formats = self._build_console_formats()
        self.console_buffer: deque[str] = deque()
        self.console_buffer_chars = 0
        self.workflow_buttons: list[QPushButton] = []
        self.command_buttons: list[dict[str, str]] = []
        self.command_run_buttons: list[QPushButton] = []
        self.command_edit_buttons: list[QToolButton] = []
        self.command_delete_buttons: list[QToolButton] = []
        self.sweep_buttons: list[dict[str, str]] = []
        self.sweep_run_buttons: list[QPushButton] = []
        self.sweep_edit_buttons: list[QToolButton] = []
        self.sweep_delete_buttons: list[QToolButton] = []
        self.sweep_workflow_buttons: list[QPushButton] = []
        self.sweep_combo_statuses: dict[int, tuple[str, str]] = {}
        self.sweep_active = False
        self.sweep_paused = False
        self.sweep_disk_scan_active = False
        self.sweep_current_combo_index: int | None = None
        self.sweep_combo_grid_summary = "组合 0 个"
        self.sweep_combo_param_keys: list[str] = []
        self.plot_buttons: list[dict[str, str]] = []
        self.plot_run_buttons: list[QPushButton] = []
        self.plot_edit_buttons: list[QToolButton] = []
        self.plot_delete_buttons: list[QToolButton] = []
        self.calculation_active = False
        self.calculation_expected = 0
        self.calculation_completed_offset = 0
        self.calculation_first_iteration: int | None = None
        self.calculation_last_iteration: int | None = None
        self.calculation_stop_requested = False
        self.progress_parse_tail = ""
        self.post_image_paths: list[Path] = []
        self.post_windows: list[PostImageWindow] = []
        self.post_results_window: PostResultsWindow | None = None
        self.current_post_image_path: Path | None = None
        self.pending_post_refresh = False
        self.post_refresh_active = False
        self.post_refresh_token = 0
        self.post_object_refresh_active = False
        self.post_object_refresh_token = 0
        self.output_layout_initialized = False
        self._applying_output_layout = False
        self.console_flush_timer = QTimer(self)
        self.console_flush_timer.setInterval(CONSOLE_FLUSH_MS)
        self.console_flush_timer.setSingleShot(True)
        self.console_flush_timer.timeout.connect(self._flush_console_buffer)

        self._build_ui()
        self._connect_signals()
        self._restore_settings()
        self._update_enabled_state()

    def _build_console_formats(self) -> dict[str, QTextCharFormat]:
        def make(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            font = QFont("Consolas")
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setBold(bold)
            font.setItalic(italic)
            fmt.setFont(font)
            return fmt

        return {
            "normal": make("#d8e3f0"),
            "event": make("#8ea2ba"),
            "command": make("#7dd3fc", bold=True),
            "warning": make("#facc15", bold=True),
            "error": make("#fb7185", bold=True),
        }

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("header")
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header.setFrameShadow(QFrame.Shadow.Raised)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        app_title = QLabel(APP_NAME)
        app_title.setObjectName("appTitle")
        app_subtitle = QLabel("本地单实例 Fluent 控制台")
        app_subtitle.setObjectName("appSubtitle")
        title_col.addWidget(app_title)
        title_col.addWidget(app_subtitle)
        self.status_label = QLabel("未启动")
        self.status_label.setObjectName("statusBadge")
        self.status_label.setProperty("status", "idle")
        self.status_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.status_label.setFrameShadow(QFrame.Shadow.Sunken)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.output_visible_checkbox = QCheckBox("显示输出")
        self.output_visible_checkbox.setChecked(True)
        self.output_below_checkbox = QCheckBox("输出下方")
        self.topmost_btn = QPushButton("置顶")
        self.topmost_btn.setObjectName("toggleButton")
        self.topmost_btn.setCheckable(True)
        self.header_busy_progress = QProgressBar()
        self.header_busy_progress.setObjectName("headerBusyProgress")
        self.header_busy_progress.setRange(0, 0)
        self.header_busy_progress.setTextVisible(False)
        self.header_busy_progress.setFixedSize(120, 8)
        self.header_busy_progress.setVisible(False)
        header_layout.addLayout(title_col)
        header_layout.addStretch(1)
        header_layout.addWidget(self.header_busy_progress)
        header_layout.addWidget(self.output_visible_checkbox)
        header_layout.addWidget(self.output_below_checkbox)
        header_layout.addWidget(self.topmost_btn)
        header_layout.addWidget(self.status_label)
        root_layout.addWidget(header)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        root_layout.addWidget(self.main_splitter, 1)

        self.control_panel = QWidget()
        self.control_panel.setObjectName("controlPanel")
        self.control_panel.setMinimumWidth(480)
        self.control_panel.setMaximumWidth(16_777_215)
        left_layout = QVBoxLayout(self.control_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        launch_box = QGroupBox("Fluent")
        launch_layout = QGridLayout(launch_box)
        launch_layout.setContentsMargins(12, 18, 12, 12)
        launch_layout.setHorizontalSpacing(8)
        launch_layout.setVerticalSpacing(8)
        self.work_dir_edit = self._history_combo("选择工作目录")
        self.case_file_edit = self._history_combo("Case 文件可选")
        self.dim_combo = QComboBox()
        self.dim_combo.addItems(["2D", "3D"])
        self.cores_spin = QSpinBox()
        self.cores_spin.setRange(1, 256)
        self.cores_spin.setValue(1)
        self.gui_checkbox = QCheckBox("显示 Fluent GUI")
        self.gui_checkbox.setChecked(True)
        self.load_scm_on_start_checkbox = QCheckBox("启动后加载 SCM")
        self.launch_scm_file_edit = self._history_combo("选择启动后加载的 .scm 文件")

        self.browse_work_btn = self._tool_button("...")
        self.open_work_btn = self._open_button()
        self.browse_case_btn = self._tool_button("...")
        self.open_case_btn = self._open_button()
        self.clear_case_btn = self._clear_button()
        self.browse_launch_scm_btn = self._tool_button("...")
        self.open_launch_scm_btn = self._open_button()
        self.clear_launch_scm_btn = self._clear_button()
        self.start_btn = QPushButton("启动 Fluent")
        self.start_btn.setObjectName("primaryButton")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("dangerButton")

        launch_layout.addWidget(QLabel("工作目录"), 0, 0)
        launch_layout.addWidget(self.work_dir_edit, 0, 1, 1, 3)
        launch_layout.addWidget(self.browse_work_btn, 0, 4)
        launch_layout.addWidget(self.open_work_btn, 0, 5)
        launch_layout.addWidget(QLabel("Case"), 1, 0)
        launch_layout.addWidget(self.case_file_edit, 1, 1, 1, 2)
        launch_layout.addWidget(self.browse_case_btn, 1, 3)
        launch_layout.addWidget(self.open_case_btn, 1, 4)
        launch_layout.addWidget(self.clear_case_btn, 1, 5)
        launch_layout.addWidget(QLabel("维度"), 2, 0)
        launch_layout.addWidget(self.dim_combo, 2, 1)
        launch_layout.addWidget(QLabel("核数"), 2, 2)
        launch_layout.addWidget(self.cores_spin, 2, 3, 1, 3)
        launch_layout.addWidget(self.gui_checkbox, 3, 0, 1, 2)
        launch_layout.addWidget(self.load_scm_on_start_checkbox, 3, 2, 1, 4)
        launch_layout.addWidget(QLabel("SCM"), 4, 0)
        launch_layout.addWidget(self.launch_scm_file_edit, 4, 1, 1, 2)
        launch_layout.addWidget(self.browse_launch_scm_btn, 4, 3)
        launch_layout.addWidget(self.open_launch_scm_btn, 4, 4)
        launch_layout.addWidget(self.clear_launch_scm_btn, 4, 5)
        launch_layout.addWidget(self.start_btn, 5, 0, 1, 5)
        launch_layout.addWidget(self.stop_btn, 5, 5)
        launch_layout.setColumnStretch(1, 1)
        launch_layout.setColumnStretch(2, 1)

        file_box = QGroupBox("Case / Data")
        file_layout = QGridLayout(file_box)
        file_layout.setContentsMargins(12, 18, 12, 12)
        file_layout.setHorizontalSpacing(8)
        file_layout.setVerticalSpacing(10)
        self.file_path_edit = self._history_combo("选择或输入 Case/Data 路径")
        self.browse_file_btn = self._tool_button("...")
        self.save_file_btn = self._tool_button("存")
        self.open_file_btn = self._open_button()
        self.read_case_btn = QPushButton("读取 Case")
        self.read_data_btn = QPushButton("读取 Data")
        self.write_case_btn = QPushButton("保存 Case")
        self.write_data_btn = QPushButton("保存 Data")
        self.write_case_data_btn = QPushButton("保存 Case+Data")
        file_layout.addWidget(QLabel("路径"), 0, 0)
        file_layout.addWidget(self.file_path_edit, 0, 1, 1, 2)
        file_layout.addWidget(self.browse_file_btn, 0, 3)
        file_layout.addWidget(self.save_file_btn, 0, 4)
        file_layout.addWidget(self.open_file_btn, 0, 5)
        file_layout.addWidget(QLabel("读取"), 1, 0)
        file_layout.addWidget(self.read_case_btn, 1, 1, 1, 2)
        file_layout.addWidget(self.read_data_btn, 1, 3, 1, 3)
        file_layout.addWidget(QLabel("保存"), 2, 0)
        file_layout.addWidget(self.write_case_btn, 2, 1)
        file_layout.addWidget(self.write_data_btn, 2, 2)
        file_layout.addWidget(self.write_case_data_btn, 2, 3, 1, 3)
        file_layout.addWidget(QLabel("常用"), 3, 0)
        self.file_use_case_btn = QPushButton("使用启动 Case")
        self.file_use_work_btn = QPushButton("默认保存路径")
        file_layout.addWidget(self.file_use_case_btn, 3, 1, 1, 2)
        file_layout.addWidget(self.file_use_work_btn, 3, 3, 1, 3)
        file_layout.setColumnStretch(1, 1)

        udf_box = QGroupBox("UDF")
        udf_layout = QGridLayout(udf_box)
        udf_layout.setContentsMargins(12, 18, 12, 12)
        udf_layout.setHorizontalSpacing(10)
        udf_layout.setVerticalSpacing(8)
        self.udf_dir_edit = self._history_combo("选择包含 .c/.h/.hpp 的 UDF 文件夹")
        self.browse_udf_btn = self._tool_button("...")
        self.open_udf_btn = self._open_button()
        self.build_udf_btn = QPushButton("编译并加载 UDF")
        self.build_udf_btn.setObjectName("primaryButton")
        self.on_demand_function_edit = self._history_combo("Execute On Demand 函数，例如：Vari_Sources")
        self.execute_on_demand_btn = QPushButton("执行 On Demand")
        udf_layout.addWidget(QLabel("文件夹"), 0, 0)
        udf_layout.addWidget(self.udf_dir_edit, 0, 1, 1, 2)
        udf_layout.addWidget(self.browse_udf_btn, 0, 3)
        udf_layout.addWidget(self.open_udf_btn, 0, 4)
        udf_layout.addWidget(self.build_udf_btn, 1, 0, 1, 5)
        udf_layout.addWidget(QLabel("On Demand"), 2, 0)
        udf_layout.addWidget(self.on_demand_function_edit, 2, 1, 1, 2)
        udf_layout.addWidget(self.execute_on_demand_btn, 2, 3, 1, 2)
        udf_layout.setColumnStretch(1, 1)

        command_box = QWidget()
        command_layout = QVBoxLayout(command_box)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(8)
        self.command_mode_combo = QComboBox()
        self.command_mode_combo.setObjectName("modeCombo")
        self.command_mode_combo.addItem("TUI", "tui")
        self.command_mode_combo.addItem("PyFluent", "python")
        self.preset_combo = self._history_combo("选择预设指令")
        self.preset_combo.setEditable(False)
        self.command_scm_file_edit = self._history_combo("选择或输入 .scm 文件")
        self.browse_command_scm_btn = self._tool_button("...")
        self.open_command_scm_btn = self._open_button()
        self.load_scm_btn = QPushButton("加载 SCM")
        self.mesh_check_btn = QPushButton("检查网格")
        self.initialize_btn = QPushButton("初始化")
        self.init_zone_type_edit = self._history_combo("mass-flow-inlet")
        self.init_zone_name_edit = self._history_combo("inlet")
        self.init_phase_edit = self._history_combo("mixture")
        self.iterations_spin = QSpinBox()
        self.iterations_spin.setRange(1, 100000)
        self.iterations_spin.setValue(100)
        self.iterate_btn = QPushButton("开始计算")
        self.stop_calc_btn = QPushButton("停止计算")
        self.stop_calc_btn.setObjectName("dangerButton")
        self.use_preset_btn = QPushButton("套用")
        self.run_preset_btn = QPushButton("运行预设")
        self.add_preset_btn = QPushButton("添加")
        self.remove_preset_btn = QPushButton("删除")
        self.clear_command_btn = QPushButton("清空输入")
        self.command_edit = self._history_combo('输入 TUI 命令，例如：/file/read-case "case.cas.h5"')
        self.command_edit.setMinimumWidth(300)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primaryButton")

        send_box = QGroupBox("发送命令")
        send_layout = QGridLayout(send_box)
        send_layout.setContentsMargins(12, 18, 12, 12)
        send_layout.setHorizontalSpacing(8)
        send_layout.setVerticalSpacing(8)
        send_layout.addWidget(QLabel("模式"), 0, 0)
        send_layout.addWidget(self.command_mode_combo, 0, 1)
        send_layout.addWidget(QLabel("预设"), 1, 0)
        send_layout.addWidget(self.preset_combo, 1, 1, 1, 3)
        send_layout.addWidget(self.use_preset_btn, 1, 4)
        send_layout.addWidget(self.run_preset_btn, 1, 5)
        send_layout.addWidget(QLabel("输入"), 2, 0)
        send_layout.addWidget(self.command_edit, 2, 1, 1, 4)
        send_layout.addWidget(self.send_btn, 2, 5)
        send_layout.addWidget(self.add_preset_btn, 3, 1)
        send_layout.addWidget(self.remove_preset_btn, 3, 2)
        send_layout.addWidget(self.clear_command_btn, 3, 3)
        send_layout.setColumnStretch(1, 1)
        send_layout.setColumnStretch(3, 1)

        quick_box = QGroupBox("快捷操作")
        quick_layout = QGridLayout(quick_box)
        quick_layout.setContentsMargins(12, 18, 12, 12)
        quick_layout.setHorizontalSpacing(8)
        quick_layout.setVerticalSpacing(8)
        quick_layout.addWidget(QLabel("网格"), 0, 0)
        quick_layout.addWidget(self.mesh_check_btn, 0, 1, 1, 3)
        quick_layout.addWidget(QLabel("区域类型"), 1, 0)
        quick_layout.addWidget(self.init_zone_type_edit, 1, 1, 1, 3)
        quick_layout.addWidget(QLabel("区域名称"), 2, 0)
        quick_layout.addWidget(self.init_zone_name_edit, 2, 1, 1, 3)
        quick_layout.addWidget(QLabel("相"), 3, 0)
        quick_layout.addWidget(self.init_phase_edit, 3, 1, 1, 2)
        quick_layout.addWidget(self.initialize_btn, 3, 3)
        quick_layout.addWidget(QLabel("迭代步数"), 4, 0)
        quick_layout.addWidget(self.iterations_spin, 4, 1)
        quick_layout.addWidget(self.iterate_btn, 4, 2)
        quick_layout.addWidget(self.stop_calc_btn, 4, 3)
        quick_layout.setColumnStretch(2, 1)

        scm_box = QGroupBox("SCM 脚本")
        scm_layout = QGridLayout(scm_box)
        scm_layout.setContentsMargins(12, 18, 12, 12)
        scm_layout.setHorizontalSpacing(8)
        scm_layout.setVerticalSpacing(8)
        scm_layout.addWidget(QLabel("文件"), 0, 0)
        scm_layout.addWidget(self.command_scm_file_edit, 0, 1, 1, 3)
        scm_layout.addWidget(self.browse_command_scm_btn, 0, 4)
        scm_layout.addWidget(self.open_command_scm_btn, 0, 5)
        scm_layout.addWidget(self.load_scm_btn, 1, 1, 1, 5)
        scm_layout.setColumnStretch(1, 1)

        command_button_box = QGroupBox("自定义命令按钮")
        command_button_layout = QVBoxLayout(command_button_box)
        command_button_layout.setContentsMargins(10, 18, 10, 10)
        command_button_layout.setSpacing(8)
        command_button_toolbar = QHBoxLayout()
        command_button_toolbar.setSpacing(8)
        self.add_command_button_btn = QPushButton("新增命令按钮")
        self.add_command_button_from_input_btn = QPushButton("从当前输入生成")
        self.reset_command_buttons_btn = QPushButton("恢复默认按钮")
        self.command_button_empty_label = QLabel("还没有命令按钮。点击“新增命令按钮”创建。")
        self.command_button_empty_label.setObjectName("mutedLabel")
        command_button_toolbar.addWidget(self.add_command_button_btn)
        command_button_toolbar.addWidget(self.add_command_button_from_input_btn)
        command_button_toolbar.addWidget(self.reset_command_buttons_btn)
        command_button_toolbar.addStretch(1)
        self.command_button_grid = QGridLayout()
        self.command_button_grid.setHorizontalSpacing(8)
        self.command_button_grid.setVerticalSpacing(8)
        command_button_layout.addLayout(command_button_toolbar)
        command_button_layout.addWidget(self.command_button_empty_label)
        command_button_layout.addLayout(self.command_button_grid)

        command_layout.addWidget(send_box)
        command_layout.addWidget(quick_box)
        command_layout.addWidget(scm_box)
        command_layout.addWidget(command_button_box)
        command_layout.addStretch(1)

        automation_box = QGroupBox("自动化流程")
        automation_layout = QVBoxLayout(automation_box)
        automation_layout.setContentsMargins(12, 18, 12, 12)
        automation_layout.setSpacing(8)
        manage_layout = QGridLayout()
        manage_layout.setHorizontalSpacing(8)
        manage_layout.setVerticalSpacing(8)
        self.workflow_combo = QComboBox()
        self.workflow_combo.setMinimumHeight(36)
        self.add_workflow_btn = QPushButton("新增流程")
        self.edit_workflow_btn = QPushButton("编辑")
        self.delete_workflow_btn = QPushButton("删除")
        manage_layout.addWidget(QLabel("配置"), 0, 0)
        manage_layout.addWidget(self.workflow_combo, 0, 1)
        manage_layout.addWidget(self.add_workflow_btn, 0, 2)
        manage_layout.addWidget(self.edit_workflow_btn, 0, 3)
        manage_layout.addWidget(self.delete_workflow_btn, 0, 4)
        manage_layout.setColumnStretch(1, 1)
        automation_layout.addLayout(manage_layout)
        self.workflow_empty_label = QLabel("还没有流程按钮。点击“新增流程”创建。")
        self.workflow_empty_label.setObjectName("mutedLabel")
        automation_layout.addWidget(self.workflow_empty_label)
        self.workflow_button_grid = QGridLayout()
        self.workflow_button_grid.setHorizontalSpacing(8)
        self.workflow_button_grid.setVerticalSpacing(8)
        automation_layout.addLayout(self.workflow_button_grid)
        automation_layout.addStretch(1)

        sweep_box = QWidget()
        sweep_layout = QVBoxLayout(sweep_box)
        sweep_layout.setContentsMargins(0, 0, 0, 0)
        sweep_layout.setSpacing(8)

        sweep_param_box = QGroupBox("参数扫描网格")
        sweep_param_box.setObjectName("sweepSectionBox")
        sweep_param_layout = QVBoxLayout(sweep_param_box)
        sweep_param_layout.setContentsMargins(12, 18, 12, 12)
        sweep_param_layout.setSpacing(8)
        sweep_tools_row = QHBoxLayout()
        sweep_tools_row.setSpacing(8)
        self.sweep_tools_label = QLabel(str(SWEEP_TOOLS_DIR))
        self.sweep_tools_label.setObjectName("mutedLabel")
        self.load_sweep_config_btn = QPushButton("读取配置")
        self.save_sweep_grid_btn = QPushButton("保存参数")
        self.preview_sweep_combos_btn = QPushButton("刷新组合")
        sweep_tools_row.addWidget(QLabel("来源"))
        sweep_tools_row.addWidget(self.sweep_tools_label, 1)
        sweep_tools_row.addWidget(self.load_sweep_config_btn)
        sweep_tools_row.addWidget(self.save_sweep_grid_btn)
        sweep_tool_path_grid = QGridLayout()
        sweep_tool_path_grid.setHorizontalSpacing(8)
        sweep_tool_path_grid.setVerticalSpacing(6)
        self.sweep_module_path_edit = self._history_combo("参数扫描接口 sweep.py")
        self.browse_sweep_module_path_btn = self._tool_button("...")
        self.open_sweep_module_path_btn = self._open_button()
        self.sweep_config_path_edit = self._history_combo("参数网格配置 sweep_config.py")
        self.browse_sweep_config_path_btn = self._tool_button("...")
        self.open_sweep_config_path_btn = self._open_button()
        sweep_tool_path_grid.addWidget(QLabel("接口 sweep.py"), 0, 0)
        sweep_tool_path_grid.addWidget(self.sweep_module_path_edit, 0, 1)
        sweep_tool_path_grid.addWidget(self.browse_sweep_module_path_btn, 0, 2)
        sweep_tool_path_grid.addWidget(self.open_sweep_module_path_btn, 0, 3)
        sweep_tool_path_grid.addWidget(QLabel("配置 config.py"), 1, 0)
        sweep_tool_path_grid.addWidget(self.sweep_config_path_edit, 1, 1)
        sweep_tool_path_grid.addWidget(self.browse_sweep_config_path_btn, 1, 2)
        sweep_tool_path_grid.addWidget(self.open_sweep_config_path_btn, 1, 3)
        sweep_tool_path_grid.setColumnStretch(1, 1)
        self.sweep_grid_editor = QPlainTextEdit()
        self.sweep_grid_editor.setObjectName("sweepGridEditor")
        self.sweep_grid_editor.setMinimumHeight(120)
        self.sweep_grid_editor.setPlaceholderText("udf/a-ent = 5e-13, 1e-12, 2e-12")
        sweep_param_layout.addLayout(sweep_tools_row)
        sweep_param_layout.addLayout(sweep_tool_path_grid)
        sweep_param_layout.addWidget(self.sweep_grid_editor)

        sweep_batch_box = QGroupBox("扫描批处理")
        sweep_batch_box.setObjectName("sweepPrimaryBox")
        sweep_batch_layout = QVBoxLayout(sweep_batch_box)
        sweep_batch_layout.setContentsMargins(12, 18, 12, 12)
        sweep_batch_layout.setSpacing(10)
        sweep_config_panel = QFrame()
        sweep_config_panel.setObjectName("sweepPanel")
        sweep_config_layout = QGridLayout(sweep_config_panel)
        sweep_config_layout.setContentsMargins(10, 10, 10, 10)
        sweep_config_layout.setHorizontalSpacing(8)
        sweep_config_layout.setVerticalSpacing(8)
        sweep_execute_panel = QFrame()
        sweep_execute_panel.setObjectName("sweepAccentPanel")
        sweep_execute_layout = QGridLayout(sweep_execute_panel)
        sweep_execute_layout.setContentsMargins(10, 10, 10, 10)
        sweep_execute_layout.setHorizontalSpacing(8)
        sweep_execute_layout.setVerticalSpacing(8)
        self.sweep_scan_dir_edit = self._history_combo("扫描工作目录，例如 D:\\Fluent\\Cases\\sweep")
        self.browse_sweep_scan_dir_btn = self._tool_button("...")
        self.open_sweep_scan_dir_btn = self._open_button()
        self.sweep_base_case_edit = self._history_combo("基准 Case，可留空使用当前 Fluent 状态")
        self.browse_sweep_base_case_btn = self._tool_button("...")
        self.open_sweep_base_case_btn = self._open_button()
        self.sweep_init_workflow_combo = QComboBox()
        self.sweep_post_workflow_combo = QComboBox()
        self.sweep_iterations_spin = QSpinBox()
        self.sweep_iterations_spin.setRange(0, 10_000_000)
        self.sweep_iterations_spin.setValue(DEFAULT_SWEEP_ITERATIONS)
        self.sweep_iterations_spin.setSuffix(" 步")
        self.skip_completed_sweep_checkbox = QCheckBox("跳过已完成")
        self.run_sweep_workflow_btn = QPushButton("开始执行选中组合")
        self.run_sweep_workflow_btn.setObjectName("primaryButton")
        self.run_all_sweep_workflow_btn = QPushButton("执行全部组合")
        self.run_all_sweep_workflow_btn.setObjectName("primaryButton")
        self.sweep_progress_label = QLabel("扫描进度：空闲")
        self.sweep_progress_label.setObjectName("mutedLabel")
        self.sweep_progress_bar = QProgressBar()
        self.sweep_progress_bar.setObjectName("calcProgress")
        self.sweep_progress_bar.setRange(0, 1)
        self.sweep_progress_bar.setValue(0)
        self.sweep_progress_bar.setFormat("空闲")
        self.pause_sweep_btn = QPushButton("暂停")
        self.resume_sweep_btn = QPushButton("继续")
        self.retry_sweep_btn = QPushButton("重试当前组合")
        self.stop_sweep_btn = QPushButton("停止")
        self.stop_sweep_btn.setObjectName("dangerButton")
        sweep_file_label = QLabel("文件与基准")
        sweep_file_label.setObjectName("sweepSectionLabel")
        sweep_flow_label = QLabel("流程设置")
        sweep_flow_label.setObjectName("sweepSectionLabel")
        sweep_execute_label = QLabel("执行控制")
        sweep_execute_label.setObjectName("sweepSectionLabel")
        sweep_control_row = QHBoxLayout()
        sweep_control_row.setSpacing(8)
        sweep_control_row.addWidget(self.pause_sweep_btn)
        sweep_control_row.addWidget(self.resume_sweep_btn)
        sweep_control_row.addWidget(self.retry_sweep_btn)
        sweep_control_row.addWidget(self.stop_sweep_btn)
        self.sweep_scan_dir_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sweep_base_case_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sweep_init_workflow_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sweep_post_workflow_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.run_sweep_workflow_btn.setMinimumWidth(0)
        self.run_all_sweep_workflow_btn.setMinimumWidth(0)
        self.retry_sweep_btn.setMinimumWidth(0)

        sweep_config_layout.addWidget(sweep_file_label, 0, 0, 1, 6)
        sweep_config_layout.addWidget(QLabel("扫描目录"), 1, 0)
        sweep_config_layout.addWidget(self.sweep_scan_dir_edit, 1, 1, 1, 3)
        sweep_config_layout.addWidget(self.browse_sweep_scan_dir_btn, 1, 4)
        sweep_config_layout.addWidget(self.open_sweep_scan_dir_btn, 1, 5)
        sweep_config_layout.addWidget(QLabel("基准 Case"), 2, 0)
        sweep_config_layout.addWidget(self.sweep_base_case_edit, 2, 1, 1, 3)
        sweep_config_layout.addWidget(self.browse_sweep_base_case_btn, 2, 4)
        sweep_config_layout.addWidget(self.open_sweep_base_case_btn, 2, 5)
        sweep_config_layout.addWidget(sweep_flow_label, 3, 0, 1, 6)
        sweep_config_layout.addWidget(QLabel("初始化流程"), 4, 0)
        sweep_config_layout.addWidget(self.sweep_init_workflow_combo, 4, 1, 1, 5)
        sweep_config_layout.addWidget(QLabel("后处理流程"), 5, 0)
        sweep_config_layout.addWidget(self.sweep_post_workflow_combo, 5, 1, 1, 5)
        sweep_config_layout.setColumnStretch(1, 1)
        sweep_config_layout.setColumnStretch(3, 1)

        sweep_execute_layout.addWidget(sweep_execute_label, 0, 0, 1, 4)
        sweep_execute_layout.addWidget(QLabel("计算步数"), 1, 0)
        sweep_execute_layout.addWidget(self.sweep_iterations_spin, 1, 1)
        sweep_execute_layout.addWidget(self.skip_completed_sweep_checkbox, 1, 2, 1, 2)
        sweep_execute_layout.addWidget(self.run_sweep_workflow_btn, 2, 0, 1, 2)
        sweep_execute_layout.addWidget(self.run_all_sweep_workflow_btn, 2, 2, 1, 2)
        sweep_execute_layout.addWidget(self.sweep_progress_label, 3, 0)
        sweep_execute_layout.addWidget(self.sweep_progress_bar, 3, 1, 1, 3)
        sweep_execute_layout.addLayout(sweep_control_row, 4, 0, 1, 4)
        sweep_execute_layout.setColumnStretch(1, 1)
        sweep_execute_layout.setColumnStretch(2, 1)

        sweep_batch_layout.addWidget(sweep_config_panel)
        sweep_batch_layout.addWidget(sweep_execute_panel)

        self.sweep_combo_box = QGroupBox("组合状态")
        self.sweep_combo_box.setObjectName("sweepStatusBox")
        sweep_combo_layout = QGridLayout(self.sweep_combo_box)
        sweep_combo_layout.setContentsMargins(12, 18, 12, 12)
        sweep_combo_layout.setHorizontalSpacing(8)
        sweep_combo_layout.setVerticalSpacing(8)
        self.sweep_summary_label = QLabel("组合 0 个")
        self.sweep_summary_label.setObjectName("mutedLabel")
        self.sweep_combo_list = QTableWidget()
        self.sweep_combo_list.setObjectName("sweepComboTable")
        self.sweep_combo_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sweep_combo_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sweep_combo_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sweep_combo_list.setAlternatingRowColors(True)
        self.sweep_combo_list.setSortingEnabled(True)
        self.sweep_combo_list.setWordWrap(False)
        self.sweep_combo_list.setShowGrid(False)
        self.sweep_combo_list.verticalHeader().setVisible(False)
        self.sweep_combo_list.horizontalHeader().setSectionsClickable(True)
        self.sweep_combo_list.horizontalHeader().setStretchLastSection(True)
        self.sweep_combo_list.setMinimumHeight(220)
        self.sweep_preview_text = QPlainTextEdit()
        self.sweep_preview_text.setObjectName("sweepPreviewText")
        self.sweep_preview_text.setReadOnly(True)
        self.sweep_preview_text.setMinimumHeight(120)
        self.sweep_preview_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        sweep_combo_select_row = QHBoxLayout()
        sweep_combo_select_row.setSpacing(8)
        self.sweep_preview_toggle = QCheckBox("显示命令预览")
        self.sweep_preview_toggle.setChecked(False)
        self.select_all_sweep_combos_btn = QPushButton("全选")
        self.clear_sweep_selection_btn = QPushButton("清空选择")
        self.scan_sweep_completed_btn = QPushButton("扫描已完成")
        self.reset_sweep_status_btn = QPushButton("重置状态")
        sweep_combo_filter_row = QGridLayout()
        sweep_combo_filter_row.setSpacing(8)
        self.sweep_combo_filter_param_combo = QComboBox()
        self.sweep_combo_filter_value_combo = QComboBox()
        self.sweep_combo_filter_select_btn = QPushButton("勾选匹配")
        self.sweep_combo_filter_unselect_btn = QPushButton("取消匹配")
        self.sweep_combo_filter_only_checkbox = QCheckBox("只显示匹配")
        self.sweep_combo_filter_param_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sweep_combo_filter_value_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sweep_combo_filter_select_btn.setMinimumWidth(0)
        self.sweep_combo_filter_unselect_btn.setMinimumWidth(0)
        sweep_combo_filter_row.addWidget(QLabel("参数"), 0, 0)
        sweep_combo_filter_row.addWidget(self.sweep_combo_filter_param_combo, 0, 1)
        sweep_combo_filter_row.addWidget(QLabel("取值"), 0, 2)
        sweep_combo_filter_row.addWidget(self.sweep_combo_filter_value_combo, 0, 3)
        sweep_combo_filter_row.addWidget(self.sweep_combo_filter_select_btn, 1, 1)
        sweep_combo_filter_row.addWidget(self.sweep_combo_filter_unselect_btn, 1, 2)
        sweep_combo_filter_row.addWidget(self.sweep_combo_filter_only_checkbox, 1, 3)
        sweep_combo_filter_row.setColumnStretch(1, 1)
        sweep_combo_filter_row.setColumnStretch(3, 1)
        sweep_combo_select_row.addWidget(self.preview_sweep_combos_btn)
        sweep_combo_select_row.addWidget(self.select_all_sweep_combos_btn)
        sweep_combo_select_row.addWidget(self.clear_sweep_selection_btn)
        sweep_combo_select_row.addWidget(self.scan_sweep_completed_btn)
        sweep_combo_select_row.addWidget(self.reset_sweep_status_btn)
        sweep_combo_select_row.addWidget(self.sweep_preview_toggle)
        sweep_combo_select_row.addStretch(1)
        sweep_combo_layout.addWidget(self.sweep_summary_label, 0, 0, 1, 2)
        sweep_combo_layout.addLayout(sweep_combo_select_row, 1, 0, 1, 2)
        sweep_combo_layout.addLayout(sweep_combo_filter_row, 2, 0, 1, 2)
        sweep_combo_layout.addWidget(self.sweep_combo_list, 3, 0, 1, 2)
        sweep_combo_layout.addWidget(self.sweep_preview_text, 4, 0, 1, 2)
        sweep_combo_layout.setColumnStretch(0, 1)

        sweep_module_box = QGroupBox("模块按钮")
        sweep_module_box.setObjectName("sweepSectionBox")
        sweep_module_layout = QVBoxLayout(sweep_module_box)
        sweep_module_layout.setContentsMargins(10, 18, 10, 10)
        sweep_module_layout.setSpacing(8)
        sweep_button_toolbar = QHBoxLayout()
        sweep_button_toolbar.setSpacing(8)
        self.add_sweep_button_btn = QPushButton("新增模块按钮")
        self.reset_sweep_buttons_btn = QPushButton("恢复默认模块")
        self.sweep_button_empty_label = QLabel("还没有扫描模块按钮。点击“新增模块按钮”创建。")
        self.sweep_button_empty_label.setObjectName("mutedLabel")
        sweep_button_toolbar.addWidget(self.add_sweep_button_btn)
        sweep_button_toolbar.addWidget(self.reset_sweep_buttons_btn)
        sweep_button_toolbar.addStretch(1)
        self.sweep_button_grid = QGridLayout()
        self.sweep_button_grid.setHorizontalSpacing(8)
        self.sweep_button_grid.setVerticalSpacing(8)
        sweep_module_layout.addLayout(sweep_button_toolbar)
        sweep_module_layout.addWidget(self.sweep_button_empty_label)
        sweep_module_layout.addLayout(self.sweep_button_grid)

        sweep_workflow_box = QGroupBox("扫描工作流")
        sweep_workflow_box.setObjectName("sweepSectionBox")
        sweep_workflow_layout = QVBoxLayout(sweep_workflow_box)
        sweep_workflow_layout.setContentsMargins(12, 18, 12, 12)
        sweep_workflow_layout.setSpacing(8)
        sweep_workflow_manage = QGridLayout()
        sweep_workflow_manage.setHorizontalSpacing(8)
        sweep_workflow_manage.setVerticalSpacing(8)
        self.sweep_workflow_combo = QComboBox()
        self.sweep_workflow_combo.setMinimumHeight(36)
        self.add_sweep_workflow_btn = QPushButton("新增工作流")
        self.edit_sweep_workflow_btn = QPushButton("编辑")
        self.delete_sweep_workflow_btn = QPushButton("删除")
        sweep_workflow_manage.addWidget(QLabel("配置"), 0, 0)
        sweep_workflow_manage.addWidget(self.sweep_workflow_combo, 0, 1, 1, 2)
        sweep_workflow_manage.addWidget(self.add_sweep_workflow_btn, 0, 3)
        sweep_workflow_manage.addWidget(self.edit_sweep_workflow_btn, 0, 4)
        sweep_workflow_manage.addWidget(self.delete_sweep_workflow_btn, 0, 5)
        sweep_workflow_manage.setColumnStretch(1, 1)
        sweep_workflow_layout.addLayout(sweep_workflow_manage)
        self.sweep_workflow_empty_label = QLabel("还没有扫描工作流。点击“新增工作流”创建。")
        self.sweep_workflow_empty_label.setObjectName("mutedLabel")
        sweep_workflow_layout.addWidget(self.sweep_workflow_empty_label)
        self.sweep_workflow_button_grid = QGridLayout()
        self.sweep_workflow_button_grid.setHorizontalSpacing(8)
        self.sweep_workflow_button_grid.setVerticalSpacing(8)
        sweep_workflow_layout.addLayout(self.sweep_workflow_button_grid)

        self.sweep_advanced_box = QGroupBox("高级配置：参数网格 / 模块按钮 / 流程库")
        self.sweep_advanced_box.setObjectName("sweepAdvancedBox")
        self.sweep_advanced_box.setCheckable(True)
        self.sweep_advanced_box.setChecked(False)
        sweep_advanced_layout = QVBoxLayout(self.sweep_advanced_box)
        sweep_advanced_layout.setContentsMargins(10, 18, 10, 10)
        self.sweep_advanced_tabs = QTabWidget()
        self.sweep_advanced_tabs.addTab(sweep_param_box, "参数网格")
        self.sweep_advanced_tabs.addTab(sweep_module_box, "模块按钮")
        self.sweep_advanced_tabs.addTab(sweep_workflow_box, "流程库")
        sweep_advanced_layout.addWidget(self.sweep_advanced_tabs)

        sweep_layout.addWidget(sweep_batch_box)
        sweep_layout.addWidget(self.sweep_combo_box)
        sweep_layout.addWidget(self.sweep_advanced_box)
        sweep_layout.addStretch(1)

        post_box = QGroupBox("后处理")
        post_layout = QVBoxLayout(post_box)
        post_layout.setContentsMargins(12, 18, 12, 12)
        post_layout.setSpacing(10)

        post_ops_frame = QFrame()
        post_ops_frame.setObjectName("sectionPanel")
        post_ops_layout = QVBoxLayout(post_ops_frame)
        post_ops_layout.setContentsMargins(10, 10, 10, 10)
        post_ops_layout.setSpacing(8)

        post_dir_layout = QGridLayout()
        post_dir_layout.setHorizontalSpacing(10)
        post_dir_layout.setVerticalSpacing(8)
        self.post_output_dir_edit = self._history_combo("后处理输出目录，默认使用工作目录\\post")
        self.browse_post_dir_btn = self._tool_button("...")
        self.open_post_dir_btn = self._open_button()
        self.refresh_post_btn = QPushButton("刷新结果")
        self.post_summary_label = QLabel("图片 0 张")
        self.post_summary_label.setObjectName("postSummary")
        post_dir_layout.addWidget(QLabel("输出目录"), 0, 0)
        post_dir_layout.addWidget(self.post_output_dir_edit, 0, 1)
        post_dir_layout.addWidget(self.browse_post_dir_btn, 0, 2)
        post_dir_layout.addWidget(self.open_post_dir_btn, 0, 3)
        post_dir_layout.addWidget(self.refresh_post_btn, 0, 4)
        post_dir_layout.addWidget(self.post_summary_label, 1, 1, 1, 4)
        post_dir_layout.setColumnStretch(1, 1)

        post_command_layout = QGridLayout()
        post_command_layout.setHorizontalSpacing(10)
        post_command_layout.setVerticalSpacing(8)
        self.post_command_edit = self._history_combo('输入后处理 TUI 命令，例如：/display/save-picture "post.png"')
        self.run_post_command_btn = QPushButton("运行后处理")
        self.post_picture_name_edit = QLineEdit()
        self.post_picture_name_edit.setPlaceholderText("图片文件名，例如 contour.png；留空自动命名")
        self.save_picture_btn = QPushButton("保存当前图片")
        self.save_picture_btn.setObjectName("primaryButton")
        post_command_layout.addWidget(QLabel("命令"), 0, 0)
        post_command_layout.addWidget(self.post_command_edit, 0, 1, 1, 3)
        post_command_layout.addWidget(self.run_post_command_btn, 0, 4)
        post_command_layout.addWidget(QLabel("图片"), 1, 0)
        post_command_layout.addWidget(self.post_picture_name_edit, 1, 1, 1, 3)
        post_command_layout.addWidget(self.save_picture_btn, 1, 4)
        post_command_layout.setColumnStretch(1, 1)
        post_ops_layout.addLayout(post_dir_layout)
        post_ops_layout.addLayout(post_command_layout)

        post_existing_box = QGroupBox("已有 Fluent 图/表")
        post_existing_layout = QGridLayout(post_existing_box)
        post_existing_layout.setContentsMargins(10, 18, 10, 10)
        post_existing_layout.setHorizontalSpacing(8)
        post_existing_layout.setVerticalSpacing(8)
        self.post_object_type_combo = QComboBox()
        for key, label, _path in POST_OBJECT_TYPES:
            self.post_object_type_combo.addItem(label, key)
        self.post_object_ref_combo = QComboBox()
        self.post_object_ref_combo.setEditable(True)
        self.post_object_ref_combo.lineEdit().setPlaceholderText("对象名称或编号，例如 0 / xy-pressure")
        self.refresh_post_objects_btn = QPushButton("刷新列表")
        self.display_post_object_btn = QPushButton("显示")
        self.save_post_object_image_btn = QPushButton("保存图片")
        self.write_post_object_data_btn = QPushButton("导出数据")
        self.post_object_target_edit = QLineEdit()
        self.post_object_target_edit.setPlaceholderText("输出文件名可选；图片默认 .png，数据默认 .xy/.txt")
        post_existing_layout.addWidget(QLabel("类型"), 0, 0)
        post_existing_layout.addWidget(self.post_object_type_combo, 0, 1)
        post_existing_layout.addWidget(QLabel("对象"), 0, 2)
        post_existing_layout.addWidget(self.post_object_ref_combo, 0, 3, 1, 2)
        post_existing_layout.addWidget(self.refresh_post_objects_btn, 0, 5)
        post_existing_layout.addWidget(QLabel("输出"), 1, 0)
        post_existing_layout.addWidget(self.post_object_target_edit, 1, 1, 1, 3)
        post_existing_layout.addWidget(self.display_post_object_btn, 1, 4)
        post_existing_layout.addWidget(self.save_post_object_image_btn, 1, 5)
        post_existing_layout.addWidget(self.write_post_object_data_btn, 2, 5)
        post_existing_layout.setColumnStretch(3, 1)
        post_ops_layout.addWidget(post_existing_box)

        plot_button_box = QGroupBox("绘图按钮")
        plot_button_layout = QVBoxLayout(plot_button_box)
        plot_button_layout.setContentsMargins(10, 18, 10, 10)
        plot_button_layout.setSpacing(8)
        plot_button_toolbar = QHBoxLayout()
        plot_button_toolbar.setSpacing(8)
        self.add_plot_button_btn = QPushButton("新增绘图按钮")
        self.reset_plot_buttons_btn = QPushButton("恢复默认模板")
        self.plot_button_empty_label = QLabel("还没有绘图按钮。点击“新增绘图按钮”创建。")
        self.plot_button_empty_label.setObjectName("mutedLabel")
        plot_button_toolbar.addWidget(self.add_plot_button_btn)
        plot_button_toolbar.addWidget(self.reset_plot_buttons_btn)
        plot_button_toolbar.addStretch(1)
        self.plot_button_grid = QGridLayout()
        self.plot_button_grid.setHorizontalSpacing(8)
        self.plot_button_grid.setVerticalSpacing(8)
        plot_button_layout.addLayout(plot_button_toolbar)
        plot_button_layout.addWidget(self.plot_button_empty_label)
        plot_button_layout.addLayout(self.plot_button_grid)

        post_results_box = QGroupBox("结果")
        post_results_layout = QVBoxLayout(post_results_box)
        post_results_layout.setContentsMargins(10, 18, 10, 10)
        post_results_layout.setSpacing(8)
        post_results_row = QHBoxLayout()
        post_results_row.setSpacing(8)
        self.open_post_results_btn = QPushButton("打开结果预览")
        self.open_post_results_btn.setObjectName("primaryButton")
        self.open_post_results_btn.setMinimumHeight(40)
        post_results_row.addWidget(self.open_post_results_btn)
        post_results_row.addStretch(1)
        post_results_layout.addLayout(post_results_row)

        self.post_result_text = QTextEdit()
        self.post_result_text.setObjectName("postResultText")
        self.post_result_text.setReadOnly(True)
        self.post_result_text.setMinimumHeight(96)
        self.post_result_text.setMaximumHeight(150)

        post_results_layout.addWidget(self.post_result_text)

        post_layout.addWidget(post_ops_frame)
        post_layout.addWidget(plot_button_box)
        post_layout.addWidget(post_results_box)
        post_layout.addStretch(1)

        about_box = QGroupBox("About")
        about_layout = QVBoxLayout(about_box)
        about_layout.setContentsMargins(14, 20, 14, 14)
        about_layout.setSpacing(10)
        about_header = QHBoxLayout()
        about_header.setSpacing(12)
        about_logo = QLabel("PF")
        about_logo.setObjectName("aboutLogo")
        about_logo.setFixedSize(56, 56)
        about_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_title_col = QVBoxLayout()
        about_title_col.setSpacing(3)
        about_title = QLabel(APP_NAME)
        about_title.setObjectName("appTitle")
        about_author = QLabel(f"Author: {APP_AUTHOR}")
        about_author.setObjectName("aboutAuthor")
        about_version = QLabel(f"Version: {APP_VERSION}")
        about_version.setObjectName("mutedLabel")
        about_title_col.addWidget(about_title)
        about_title_col.addWidget(about_author)
        about_title_col.addWidget(about_version)
        about_header.addWidget(about_logo)
        about_header.addLayout(about_title_col, 1)
        about_desc = QLabel(
            "本地单实例 Fluent 辅助工具，支持启动、Case/Data、UDF、SCM、命令控制、自动化流程和参数扫描。"
        )
        about_desc.setWordWrap(True)
        about_github = QLabel(f'GitHub: <a href="{APP_GITHUB_URL}">{APP_GITHUB_URL}</a>')
        about_github.setObjectName("aboutLink")
        about_github.setTextFormat(Qt.TextFormat.RichText)
        about_github.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        about_github.setOpenExternalLinks(True)
        about_notes = QLabel(
            "PyFluent 模式中可直接使用 solver/session；自动化流程按顺序执行，每一步返回后才进入下一步。"
        )
        about_notes.setObjectName("mutedLabel")
        about_notes.setWordWrap(True)
        about_scope = QLabel("Designed for lightweight local Fluent control on Windows 11.")
        about_scope.setObjectName("mutedLabel")
        about_scope.setWordWrap(True)
        about_layout.addLayout(about_header)
        about_layout.addWidget(about_desc)
        about_layout.addWidget(about_github)
        about_layout.addWidget(about_notes)
        about_layout.addWidget(about_scope)
        about_layout.addStretch(1)

        self.action_tabs = QTabWidget()
        self.action_tabs.setObjectName("actionTabs")
        self.action_tabs.setDocumentMode(True)
        self.action_tabs.setUsesScrollButtons(True)
        self.action_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.action_tabs.addTab(self._tab_page(launch_box), "启动")
        self.action_tabs.addTab(self._tab_page(file_box), "Case/Data")
        self.action_tabs.addTab(self._tab_page(udf_box), "UDF")
        self.action_tabs.addTab(self._tab_page(command_box), "命令")
        self.action_tabs.addTab(self._tab_page(automation_box), "流程")
        self.sweep_tab_index = self.action_tabs.addTab(self._tab_page(sweep_box), "参数扫描")
        self.post_tab_index = self.action_tabs.addTab(self._tab_page(post_box), "后处理")
        self.action_tabs.addTab(self._tab_page(about_box), "About")
        left_layout.addWidget(self.action_tabs, 1)

        self.output_panel = QWidget()
        self.output_panel.setObjectName("outputPanel")
        right_layout = QVBoxLayout(self.output_panel)
        right_layout.setContentsMargins(8, 2, 0, 0)
        right_layout.setSpacing(8)
        title_row = QHBoxLayout()
        title = QLabel("输出")
        title.setObjectName("consoleTitle")
        self.clear_console_btn = QPushButton("清空")
        self.clear_console_btn.setObjectName("subtleButton")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.clear_console_btn)

        self.console = QTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.console.document().setMaximumBlockCount(CONSOLE_MAX_BLOCKS)
        self.console.setUndoRedoEnabled(False)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.console.setFont(font)
        right_layout.addLayout(title_row)
        right_layout.addWidget(self.console, 1)

        self.main_splitter.addWidget(self.control_panel)
        self.main_splitter.addWidget(self.output_panel)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([760, 600])

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().setObjectName("mainStatusBar")
        self.progress_label = QLabel("计算进度")
        self.progress_label.setObjectName("statusHint")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("calcProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(220)
        self.progress_bar.setFormat("空闲")
        self.statusBar().addPermanentWidget(self.progress_label)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage("未启动")
        self._apply_widget_defaults()
        self._install_tooltips()
        self._apply_style()

    def _tab_page(self, widget: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("tabScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        page = QWidget()
        page.setObjectName("tabScrollPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(widget)
        layout.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def _set_tip(self, widget: QWidget, text: str) -> None:
        widget.setToolTip(text)
        widget.setStatusTip(text)

    def _install_tooltips(self) -> None:
        self._set_tip(self.work_dir_edit, "Fluent 启动时使用的当前工作目录，生成文件和 transcript 会写到这里。")
        self._set_tip(self.browse_work_btn, "选择 Fluent 工作目录。")
        self._set_tip(self.open_work_btn, "在资源管理器中打开工作目录。")
        self._set_tip(self.case_file_edit, "可选：启动 Fluent 时直接读取的 case 文件。留空则只启动空会话。")
        self._set_tip(self.browse_case_btn, "选择启动时读取的 case 文件。")
        self._set_tip(self.open_case_btn, "在资源管理器中打开 Case 文件所在文件夹。")
        self._set_tip(self.clear_case_btn, "清空启动 case 路径，不会删除本地文件。")
        self._set_tip(self.dim_combo, "选择 Fluent 求解器维度：2D 或 3D。")
        self._set_tip(self.cores_spin, "启动 Fluent 时使用的本地处理器数量。")
        self._set_tip(self.gui_checkbox, "勾选后显示 Fluent GUI；取消后以无图形界面方式启动。")
        self._set_tip(self.load_scm_on_start_checkbox, "勾选后在 Fluent 启动完成后自动加载下面选择的 SCM 文件。")
        self._set_tip(self.launch_scm_file_edit, "启动完成后自动加载的 Scheme/SCM 脚本路径。")
        self._set_tip(self.browse_launch_scm_btn, "选择启动后自动加载的 SCM 文件。")
        self._set_tip(self.open_launch_scm_btn, "在资源管理器中打开启动 SCM 文件所在文件夹。")
        self._set_tip(self.clear_launch_scm_btn, "清空 SCM 路径，不会删除本地文件。")
        self._set_tip(self.start_btn, "启动一个新的 Fluent solver session。这个工具只管理当前这一个实例。")
        self._set_tip(self.stop_btn, "关闭当前由本工具启动的 Fluent session。")

        self._set_tip(self.file_path_edit, "Case/Data 文件路径。可用于启动后读取，也可作为保存路径。")
        self._set_tip(self.browse_file_btn, "选择已有的 Case 或 Data 文件。")
        self._set_tip(self.save_file_btn, "选择 Case 或 Case+Data 的保存路径。")
        self._set_tip(self.open_file_btn, "在资源管理器中打开当前 Case/Data 路径所在文件夹。")
        self._set_tip(self.read_case_btn, "将路径中的 case 文件读取到当前 Fluent。")
        self._set_tip(self.read_data_btn, "将路径中的 data 文件读取到当前 Fluent。")
        self._set_tip(self.write_case_btn, "把当前 Fluent 状态保存为 case 文件。")
        self._set_tip(self.write_data_btn, "把当前 Fluent 数据保存为 data 文件。")
        self._set_tip(self.write_case_data_btn, "把当前 Fluent 状态保存为 case+data。")
        self._set_tip(self.file_use_case_btn, "把启动页的 Case 路径填入当前文件路径。")
        self._set_tip(self.file_use_work_btn, "用工作目录生成默认 case-data 保存路径。")

        self._set_tip(self.udf_dir_edit, "包含 UDF .c/.h/.hpp 源码的文件夹。扫描时会跳过 libudf 等生成目录。")
        self._set_tip(self.browse_udf_btn, "选择 UDF 源码文件夹。")
        self._set_tip(self.open_udf_btn, "在资源管理器中打开 UDF 文件夹。")
        self._set_tip(self.build_udf_btn, "扫描 UDF 文件夹，调用本地 UDF Builder 编译，并将 libudf 加载进当前 Fluent。")
        self._set_tip(self.on_demand_function_edit, "Execute On Demand 函数名。输入 Vari_Sources 会自动按 Vari_Sources::libudf 执行。")
        self._set_tip(self.execute_on_demand_btn, "执行 Define/User-Defined/Execute On Demand。函数名会保留历史记录。")

        self._set_tip(self.preset_combo, "保存的 TUI 指令预设。选择后可套用到命令输入框。")
        self._set_tip(self.command_mode_combo, "选择发送 TUI 命令，或执行 PyFluent Python 语句。PyFluent 模式中可直接使用 solver/session。")
        self._set_tip(self.command_scm_file_edit, "手动加载 SCM 时使用的脚本路径，和启动页共享历史记录。")
        self._set_tip(self.browse_command_scm_btn, "选择要加载到当前 Fluent 的 SCM 文件。")
        self._set_tip(self.open_command_scm_btn, "在资源管理器中打开命令页 SCM 文件所在文件夹。")
        self._set_tip(self.load_scm_btn, "将当前 SCM 文件通过 Fluent Scheme 接口加载进会话。")
        self._set_tip(self.mesh_check_btn, "执行 /mesh/check，并在控制台显示 Fluent 返回结果。")
        self._set_tip(self.initialize_btn, "按左侧区域类型、区域名称和相执行 compute_defaults，然后 standard_initialize。")
        self._set_tip(self.init_zone_type_edit, "初始化 compute_defaults 的 from_zone_type，默认 mass-flow-inlet。")
        self._set_tip(self.init_zone_name_edit, "初始化 compute_defaults 的 from_zone_name，默认 inlet。")
        self._set_tip(self.init_phase_edit, "初始化 compute_defaults 的 phase，默认 mixture。")
        self._set_tip(self.iterations_spin, "开始计算时执行的迭代步数。")
        self._set_tip(self.iterate_btn, "按左侧步数开始计算。内部执行 /solve/iterate。")
        self._set_tip(self.stop_calc_btn, "请求 Fluent 中断当前迭代计算。")
        self._set_tip(self.use_preset_btn, "把当前预设填入下方命令输入框。")
        self._set_tip(self.run_preset_btn, "直接按当前模式运行选中的预设指令。")
        self._set_tip(self.add_preset_btn, "把下方当前命令保存为新的预设。重复预设会自动置顶。")
        self._set_tip(self.remove_preset_btn, "删除当前选中的预设指令。")
        self._set_tip(self.clear_command_btn, "清空命令输入框，不影响命令历史和预设。")
        self._set_tip(self.command_edit, "输入当前模式对应的命令。PyFluent 模式中可直接写 solver.tui.solve.iterate(100)。")
        self._set_tip(self.send_btn, "按当前模式发送 TUI 命令或执行 PyFluent Python 语句。")
        self._set_tip(self.add_command_button_btn, "新增一个可直接运行的命令按钮，可选择 TUI 或 PyFluent 模式。")
        self._set_tip(self.add_command_button_from_input_btn, "用当前命令输入框内容快速生成一个自定义按钮。")
        self._set_tip(self.reset_command_buttons_btn, "把命令按钮恢复为内置默认配置。")
        self._set_tip(self.command_button_empty_label, "自定义命令按钮会显示在这里。每个按钮可单独编辑或删除。")

        self._set_tip(self.console, "实时显示 Fluent transcript 和工具日志。Warning/Error/命令会自动高亮。")
        self._set_tip(self.clear_console_btn, "清空当前显示的控制台文本，不影响 Fluent 和日志文件。")
        self._set_tip(self.status_label, "当前 Fluent 管理状态。")
        self._set_tip(self.output_visible_checkbox, "显示或隐藏右侧输出控制台。隐藏后左侧操作区会自动展开。")
        self._set_tip(self.output_below_checkbox, "切换输出面板位置。勾选后输出显示在下方，适合竖屏或窄窗口。")
        self._set_tip(self.topmost_btn, "让 PyFluent Lite 窗口始终显示在其他窗口上方。")
        self._set_tip(self.workflow_combo, "选择要编辑或删除的自定义流程按钮。")
        self._set_tip(self.add_workflow_btn, "创建一个新的可点击流程按钮。")
        self._set_tip(self.edit_workflow_btn, "编辑当前选中的流程按钮和步骤。")
        self._set_tip(self.delete_workflow_btn, "删除当前选中的流程按钮。")
        self._set_tip(self.sweep_tools_label, "当前参数扫描接口目录。默认读取 tools/sweep.py 和 tools/sweep_config.py。")
        self._set_tip(self.sweep_module_path_edit, "用于生成组合、rpvar 命令和组合标签的 sweep.py 文件。")
        self._set_tip(self.browse_sweep_module_path_btn, "选择参数扫描接口文件 sweep.py。")
        self._set_tip(self.open_sweep_module_path_btn, "打开 sweep.py 所在文件夹。")
        self._set_tip(self.sweep_config_path_edit, "用于读取和保存 PARAM_GRID 的配置文件，可指向 UDF 仓库里的 tools/sweep_config.py。")
        self._set_tip(self.browse_sweep_config_path_btn, "选择参数扫描配置文件 sweep_config.py。")
        self._set_tip(self.open_sweep_config_path_btn, "打开配置文件所在文件夹。")
        self._set_tip(self.load_sweep_config_btn, "从当前配置文件重新读取 PARAM_GRID。")
        self._set_tip(self.save_sweep_grid_btn, "保存当前参数网格，并刷新组合列表。")
        self._set_tip(self.preview_sweep_combos_btn, "根据当前参数网格重新生成笛卡尔积组合。")
        self._set_tip(self.sweep_grid_editor, "每行一个 rpvar，例如 udf/a-ent = 5e-13, 1e-12。")
        self._set_tip(self.sweep_scan_dir_edit, "扫描批处理的根目录。每个组合会在这里创建一个独立文件夹。")
        self._set_tip(self.browse_sweep_scan_dir_btn, "选择扫描批处理根目录。")
        self._set_tip(self.open_sweep_scan_dir_btn, "在资源管理器中打开扫描工作目录。")
        self._set_tip(self.sweep_base_case_edit, "每个组合开始前读取的基准 Case。留空时直接使用当前 Fluent 状态连续扫描。")
        self._set_tip(self.browse_sweep_base_case_btn, "选择用于每个组合起点的基准 Case 文件。")
        self._set_tip(self.open_sweep_base_case_btn, "在资源管理器中打开基准 Case 文件所在文件夹。")
        self._set_tip(self.sweep_init_workflow_combo, "应用参数后、开始计算前执行的初始化流程。可在下方流程库中编辑。")
        self._set_tip(self.sweep_post_workflow_combo, "每个组合计算完成后执行的后处理流程。默认会保存 Data 并导出 xy-plot-r-mm、xy-plot-t。")
        self._set_tip(self.sweep_iterations_spin, "每个组合应用参数和初始化后执行的迭代步数，默认 400。设为 0 可只跑流程和后处理。")
        self._set_tip(self.skip_completed_sweep_checkbox, "执行扫描前检查组合目录；已完成的组合直接标记为跳过，不重新计算。")
        self._set_tip(self.sweep_progress_bar, "按组合显示扫描批处理进度；计算细节仍显示在底部计算进度条。")
        self._set_tip(self.pause_sweep_btn, "暂停参数扫描。当前 Fluent 操作或当前计算小段返回后生效。")
        self._set_tip(self.resume_sweep_btn, "继续已暂停的参数扫描。")
        self._set_tip(self.retry_sweep_btn, "重试当前组合；如果 Fluent 已离线，会先清理并自动重新启动。")
        self._set_tip(self.stop_sweep_btn, "停止参数扫描，并尝试中断正在进行的 Fluent 计算。")
        self._set_tip(self.sweep_combo_box, "显示当前参数组合、选择状态和每个组合的执行结果。")
        self._set_tip(self.sweep_combo_list, "表格可按参数列排序；勾选一个或多个参数组合，未勾选时会使用当前选中的组合。执行时仍可滚动查看状态。")
        self._set_tip(self.sweep_combo_filter_param_combo, "选择一个参数，用它和下方取值来快速定位或勾选组合。")
        self._set_tip(self.sweep_combo_filter_value_combo, "选择参数取值；勾选匹配会选中该取值对应的全部组合。")
        self._set_tip(self.sweep_combo_filter_select_btn, "勾选当前参数取值匹配的全部组合。")
        self._set_tip(self.sweep_combo_filter_unselect_btn, "取消勾选当前参数取值匹配的全部组合。")
        self._set_tip(self.sweep_combo_filter_only_checkbox, "只显示当前参数取值匹配的组合；不删除隐藏组合。")
        self._set_tip(self.sweep_preview_toggle, "显示或隐藏当前组合的命令预览。")
        self._set_tip(self.sweep_preview_text, "当前组合的 rpvar 创建、设值、刷新和打印命令预览。")
        self._set_tip(self.select_all_sweep_combos_btn, "勾选当前组合列表中的全部组合。")
        self._set_tip(self.clear_sweep_selection_btn, "清空组合列表中的勾选和选中状态。")
        self._set_tip(self.scan_sweep_completed_btn, "扫描当前 sweep 工作目录，按状态文件或已有结果文件标记已完成、失败或停止的组合。")
        self._set_tip(self.reset_sweep_status_btn, "把组合状态恢复为待执行，不删除任何输出文件。")
        self._set_tip(self.sweep_advanced_box, "展开后可以编辑参数网格、扫描模块按钮和扫描流程库。")
        self._set_tip(self.add_sweep_button_btn, "新增一个可点击的扫描模块按钮。")
        self._set_tip(self.reset_sweep_buttons_btn, "把扫描模块按钮恢复为内置默认配置。")
        self._set_tip(self.sweep_button_empty_label, "扫描模块按钮会显示在这里；每个按钮可单独编辑或删除。")
        self._set_tip(self.sweep_workflow_combo, "扫描流程库。这里创建的流程可在上方选择为初始化流程或后处理流程。")
        self._set_tip(self.add_sweep_workflow_btn, "创建一个新的扫描流程，可用于初始化或后处理。")
        self._set_tip(self.edit_sweep_workflow_btn, "编辑当前扫描流程及其步骤顺序。")
        self._set_tip(self.delete_sweep_workflow_btn, "删除当前扫描流程。")
        self._set_tip(self.run_sweep_workflow_btn, "按上方批处理设置执行当前选中的一个或多个组合。")
        self._set_tip(self.run_all_sweep_workflow_btn, "按上方批处理设置执行组合列表中的全部组合。")
        self._set_tip(self.progress_bar, "根据 Fluent transcript 中的迭代表格解析当前计算进度。")
        self._set_tip(self.post_output_dir_edit, "后处理图片和结果文件目录。刷新时会扫描常见图片格式。")
        self._set_tip(self.refresh_post_btn, "重新扫描后处理目录中的图片。")
        self._set_tip(self.post_command_edit, "发送后处理相关 TUI 命令，输出仍会进入右侧控制台。")
        self._set_tip(self.run_post_command_btn, "运行当前后处理 TUI 命令。")
        self._set_tip(self.post_picture_name_edit, "保存当前 Fluent 图形窗口时使用的图片文件名。")
        self._set_tip(self.save_picture_btn, "调用 Fluent 保存当前图形窗口，并刷新后处理结果。")
        self._set_tip(self.post_object_type_combo, "选择要操作的 Fluent 后处理对象类型，例如已有 XY 图、等值图或报告表。")
        self._set_tip(self.post_object_ref_combo, "输入对象名称，也可以输入刷新列表后的编号。编号 0 和 1 都可用于第一个对象。")
        self._set_tip(self.refresh_post_objects_btn, "从当前 Fluent session 读取该类型已有对象列表。")
        self._set_tip(self.display_post_object_btn, "按名称或编号显示当前 Fluent 中已有的后处理对象。")
        self._set_tip(self.save_post_object_image_btn, "先显示该对象，再把当前图形窗口保存为图片。")
        self._set_tip(
            self.write_post_object_data_btn,
            "导出对象数据并确认文件已生成。XY 图会优先使用 write_to_file，必要时尝试 Datamodel ExportData。",
        )
        self._set_tip(self.post_object_target_edit, "保存图片或导出数据时使用的文件名；相对路径会写到后处理输出目录。")
        self._set_tip(self.add_plot_button_btn, "新增一个绘图按钮，并为它编辑一段 PyFluent Python 脚本。")
        self._set_tip(self.reset_plot_buttons_btn, "把绘图按钮恢复为内置 PyFluent 后处理模板。")
        self._set_tip(self.plot_button_empty_label, "绘图按钮会显示在这里；每个按钮都绑定一段可编辑脚本。")
        self._set_tip(self.open_post_results_btn, "打开独立的后处理结果预览窗口。")
        self._set_tip(self.post_result_text, "记录后处理页操作、图片路径和扫描结果。")

        self.action_tabs.setTabToolTip(0, "启动或停止当前 Fluent 实例。")
        self.action_tabs.setTabToolTip(1, "启动后读取或保存 Case/Data 文件。")
        self.action_tabs.setTabToolTip(2, "编译并加载 UDF 文件夹。")
        self.action_tabs.setTabToolTip(3, "发送 TUI/PyFluent 命令，管理预设，并执行常用快捷操作。")
        self.action_tabs.setTabToolTip(4, "创建并运行自定义自动化流程按钮。")
        self.action_tabs.setTabToolTip(5, "基于 tools/sweep.py 配置参数网格、模块按钮和扫描工作流。")
        self.action_tabs.setTabToolTip(6, "运行后处理命令、自定义绘图按钮，并预览结果图片。")
        self.action_tabs.setTabToolTip(7, "关于 PyFluent Lite。")

    def _history_combo(self, placeholder: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setMinimumHeight(UI_CONTROL_HEIGHT)
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText(placeholder)
            line_edit.setClearButtonEnabled(False)
        return combo

    def _standard_icon(self, icon: QStyle.StandardPixmap):
        return self.style().standardIcon(icon)

    def _tool_button(self, text: str) -> QToolButton:
        button = QToolButton()
        if text == "...":
            button.setText("")
            button.setIcon(self._standard_icon(QStyle.StandardPixmap.SP_DirOpenIcon))
            button.setIconSize(UI_ICON_SIZE)
            button.setAccessibleName("浏览")
        else:
            button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if text == "..." else Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setFixedSize(UI_TOOL_BUTTON_SIZE)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    def _open_button(self) -> QToolButton:
        button = self._tool_button("打开")
        button.setObjectName("openFolderButton")
        button.setText("")
        button.setIcon(self._standard_icon(QStyle.StandardPixmap.SP_DirOpenIcon))
        button.setIconSize(UI_ICON_SIZE)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAccessibleName("打开所在位置")
        button.setFixedSize(UI_TOOL_BUTTON_SIZE)
        return button

    def _clear_button(self) -> QToolButton:
        button = self._tool_button("清空")
        button.setObjectName("clearButton")
        button.setText("")
        button.setIcon(self._standard_icon(QStyle.StandardPixmap.SP_DialogCloseButton))
        button.setIconSize(UI_ICON_SIZE)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAccessibleName("清空")
        button.setFixedSize(UI_TOOL_BUTTON_SIZE)
        return button

    def _apply_widget_defaults(self) -> None:
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
            button.setDefault(False)
            if button.minimumHeight() < UI_CONTROL_HEIGHT:
                button.setMinimumHeight(UI_CONTROL_HEIGHT)

        for button in self.findChildren(QToolButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(UI_ICON_SIZE)

        for combo in self.findChildren(QComboBox):
            if combo.minimumHeight() < UI_CONTROL_HEIGHT:
                combo.setMinimumHeight(UI_CONTROL_HEIGHT)

        for line_edit in self.findChildren(QLineEdit):
            if line_edit.minimumHeight() < UI_CONTROL_HEIGHT:
                line_edit.setMinimumHeight(UI_CONTROL_HEIGHT)

        for spin_box in self.findChildren(QSpinBox):
            if spin_box.minimumHeight() < UI_CONTROL_HEIGHT:
                spin_box.setMinimumHeight(UI_CONTROL_HEIGHT)

        for spin_box in self.findChildren(QDoubleSpinBox):
            if spin_box.minimumHeight() < UI_CONTROL_HEIGHT:
                spin_box.setMinimumHeight(UI_CONTROL_HEIGHT)

        for table in self.findChildren(QTableWidget):
            table.setAlternatingRowColors(True)
            table.setWordWrap(False)
            table.verticalHeader().setVisible(False)

        for edit in self.findChildren(QPlainTextEdit):
            edit.setTabChangesFocus(False)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI";
                font-size: 12px;
            }
            QMainWindow {
                background: #f5f6f8;
            }
            QScrollArea#tabScroll {
                background: transparent;
                border: 0;
            }
            QWidget#tabScrollPage {
                background: transparent;
            }
            QScrollBar:vertical {
                width: 10px;
                background: transparent;
                margin: 2px 0 2px 0;
            }
            QScrollBar::handle:vertical {
                min-height: 28px;
                background: #c6ccd5;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #aeb8c5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
                border: 0;
                background: transparent;
            }
            QToolTip {
                color: #f5f7fb;
                background: #1f2328;
                border: 1px solid #343a40;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QFrame#header {
                background: #fbfbfd;
                border: 1px solid #e4e7ec;
                border-radius: 8px;
            }
            QFrame#workflowHeader {
                background: #ffffff;
                border: 1px solid #d8dee8;
                border-radius: 8px;
            }
            QLabel#appTitle {
                color: #202020;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#appSubtitle {
                color: #5f5f5f;
                font-size: 11px;
            }
            QLabel#mutedLabel {
                color: #687386;
            }
            QLabel#currentStepBadge {
                color: #0f5c9c;
                background: #eaf4ff;
                border: 1px solid #b7d7f0;
                border-radius: 999px;
                padding: 5px 10px;
                font-weight: 600;
            }
            QLabel#aboutAuthor {
                color: #202020;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#aboutLogo {
                color: #ffffff;
                background: #0078d4;
                border: 1px solid #106ebe;
                border-radius: 14px;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#aboutLink {
                color: #0f5c9c;
            }
            QLabel#aboutLink a {
                color: #0067b8;
                text-decoration: none;
            }
            QLabel#statusBadge {
                min-width: 88px;
                padding: 5px 12px;
                color: #424242;
                background: #f3f3f3;
                border: 1px solid #e0e0e0;
                border-radius: 999px;
            }
            QLabel#statusBadge[status="busy"] {
                color: #664b00;
                background: #fff4ce;
                border-color: #f4d47a;
            }
            QLabel#statusBadge[status="ready"] {
                color: #0f5c2f;
                background: #e6f4ea;
                border-color: #a7d8b8;
            }
            QLabel#statusBadge[status="error"] {
                color: #8a1c1c;
                background: #fde7e9;
                border-color: #f1a7ad;
            }
            QGroupBox {
                border: 1px solid #e1e5eb;
                border-radius: 8px;
                margin-top: 12px;
                padding: 8px;
                background: #fbfbfd;
                font-weight: 500;
                color: #202020;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QGroupBox#sweepPrimaryBox {
                border-color: #9dc6e8;
                background: #f7fbff;
            }
            QGroupBox#sweepStatusBox {
                border-color: #bdd7ef;
                background: #fbfdff;
            }
            QGroupBox#sweepSectionBox,
            QGroupBox#sweepAdvancedBox {
                border-color: #d8dee8;
                background: #fcfcfe;
            }
            QFrame#sweepPanel {
                background: #ffffff;
                border: 1px solid #dde6f0;
                border-radius: 7px;
            }
            QFrame#sweepAccentPanel {
                background: #f1f7fe;
                border: 1px solid #b9d6ef;
                border-radius: 7px;
            }
            QLabel#sweepSectionLabel {
                color: #0f5c9c;
                font-weight: 600;
                padding-top: 2px;
                padding-bottom: 2px;
            }
            QFrame#sectionPanel {
                background: #ffffff;
                border: 1px solid #e1e5eb;
                border-radius: 7px;
            }
            QLabel {
                color: #323130;
            }
            QLabel#sectionTitle {
                color: #202020;
                font-weight: 600;
            }
            QLabel#postSummary,
            QLabel#postPathLabel {
                color: #687386;
                font-size: 11px;
            }
            QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #d3d8df;
                border-radius: 6px;
                padding: 6px 8px;
                background: #ffffff;
                color: #202020;
                selection-background-color: #0078d4;
                min-height: 22px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #0078d4;
                background: #ffffff;
            }
            QComboBox::drop-down {
                border: 0;
                width: 26px;
            }
            QComboBox#modeCombo {
                font-weight: 600;
            }
            QPushButton, QToolButton {
                border: 1px solid #d3d8df;
                border-radius: 6px;
                padding: 7px 12px;
                background: #ffffff;
                color: #202020;
                font-weight: 400;
                min-height: 22px;
            }
            QPushButton:hover, QToolButton:hover {
                border-color: #bcc4cf;
                background: #f7f9fc;
            }
            QPushButton:pressed, QToolButton:pressed {
                background: #eef2f7;
                border-color: #aeb8c5;
            }
            QPushButton:disabled, QToolButton:disabled, QComboBox:disabled {
                color: #9a9a9a;
                background: #f4f4f4;
                border-color: #e4e4e4;
            }
            QPushButton#primaryButton {
                color: #ffffff;
                background: #0078d4;
                border-color: #0078d4;
            }
            QPushButton#primaryButton:hover {
                background: #106ebe;
                border-color: #106ebe;
            }
            QPushButton#dangerButton {
                color: #a4262c;
                border-color: #d0d0d0;
                background: #ffffff;
            }
            QPushButton#dangerButton:hover {
                background: #fde7e9;
                border-color: #d13438;
            }
            QPushButton#toggleButton:checked {
                color: #ffffff;
                background: #0078d4;
                border-color: #0078d4;
            }
            QPushButton#toggleButton:checked:hover {
                background: #106ebe;
                border-color: #106ebe;
            }
            QToolButton#clearButton {
                color: #5b6572;
                background: #ffffff;
                border-color: #d3d8df;
                padding-left: 4px;
                padding-right: 4px;
            }
            QToolButton#clearButton:hover {
                color: #202020;
                background: #eef2f7;
            }
            QToolButton#openFolderButton {
                color: #29527a;
                background: #ffffff;
                border-color: #d3d8df;
                padding-left: 4px;
                padding-right: 4px;
            }
            QToolButton#openFolderButton:hover {
                color: #0f3a61;
                background: #eef6ff;
                border-color: #9dc6e8;
            }
            QCheckBox {
                spacing: 7px;
                color: #323130;
            }
            QLabel#consoleTitle {
                color: #202020;
                font-size: 13px;
                font-weight: 600;
            }
            QTextEdit#console {
                background: #0f1720;
                color: #d8e3f0;
                border: 1px solid #1f2f42;
                border-radius: 8px;
                padding: 8px;
            }
            QTextEdit#console QScrollBar:vertical {
                background: #0f1720;
                width: 12px;
                margin: 2px;
            }
            QTextEdit#console QScrollBar::handle:vertical {
                background: #34465c;
                border-radius: 5px;
                min-height: 28px;
            }
            QTextEdit#console QScrollBar::handle:vertical:hover {
                background: #49627d;
            }
            QTextEdit#console QScrollBar::add-line:vertical,
            QTextEdit#console QScrollBar::sub-line:vertical {
                height: 0;
            }
            QSplitter::handle {
                background: #e7eaf0;
                width: 6px;
            }
            QTabWidget::pane {
                border: 1px solid #e1e5eb;
                border-radius: 8px;
                background: #fbfbfd;
                top: -1px;
            }
            QTabBar::tab {
                padding: 7px 14px;
                min-width: 64px;
                border: 1px solid transparent;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #424242;
            }
            QTabBar::tab:selected {
                color: #202020;
                background: #fbfbfd;
                border-color: #e1e5eb;
                border-bottom-color: #fbfbfd;
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: #edf2f8;
            }
            QStatusBar {
                background: #f5f6f8;
                color: #5f6b7a;
            }
            QProgressBar#calcProgress {
                border: 1px solid #cfd7e3;
                border-radius: 5px;
                background: #edf1f6;
                height: 14px;
                text-align: center;
                color: #344054;
            }
            QProgressBar#calcProgress::chunk {
                border-radius: 4px;
                background: #3b82f6;
            }
            QTableWidget#sweepComboTable {
                border: 1px solid #cfdbea;
                border-radius: 6px;
                background: #ffffff;
                alternate-background-color: #f8fbff;
                gridline-color: #e5edf6;
                selection-background-color: #dbeafe;
                selection-color: #0f1720;
                outline: 0;
            }
            QTableWidget#sweepComboTable::item {
                padding: 5px 7px;
            }
            QHeaderView::section {
                color: #1f3a5f;
                background: #edf5fc;
                border: 0;
                border-right: 1px solid #d5e3f2;
                border-bottom: 1px solid #c5d7e8;
                padding: 6px 7px;
                font-weight: 600;
            }
            QListWidget#postImageList {
                outline: 0;
            }
            QListWidget#postImageList::item {
                min-height: 42px;
                padding: 5px 8px;
                border-bottom: 1px solid #eef2f7;
            }
            QListWidget#postImageList::item:selected {
                color: #0f1720;
                background: #dbeafe;
            }
            QLabel#postPreview {
                background: #0f1720;
                color: #cbd5e1;
                border: 1px solid #d8dee8;
                border-radius: 6px;
            }
            QLabel#postPopupImage {
                background: #0f1720;
                color: #cbd5e1;
                border: 1px solid #d8dee8;
                border-radius: 6px;
            }
            QTextEdit#postResultText,
            QListWidget#postImageList {
                border: 1px solid #d8dee8;
                border-radius: 6px;
                background: #ffffff;
            }
            QListWidget#workflowStepList {
                border: 1px solid #d8dee8;
                border-radius: 6px;
                background: #ffffff;
                outline: 0;
                padding: 4px;
            }
            QListWidget#workflowStepList::item {
                border-radius: 5px;
                padding: 8px 7px;
                margin: 2px;
            }
            QListWidget#workflowStepList::item:selected {
                color: #ffffff;
                background: #0078d4;
            }
            QListWidget#workflowStepList::item:hover:!selected {
                background: #eef6ff;
            }
            QTextEdit#postResultText {
                color: #334155;
                padding: 5px;
            }
            QPlainTextEdit#plotCodeEditor,
            QPlainTextEdit#commandButtonEditor,
            QPlainTextEdit#workflowStepEditor {
                background: #111827;
                color: #e5e7eb;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #2563eb;
            }
            QPlainTextEdit#sweepGridEditor,
            QPlainTextEdit#sweepPreviewText {
                background: #ffffff;
                color: #253040;
                border: 1px solid #d8dee8;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #0078d4;
            }
            QWidget#customButtonTile {
                background: #ffffff;
                border: 1px solid #d8dee8;
                border-radius: 6px;
                min-height: 42px;
            }
            QWidget#customButtonTile:hover {
                border-color: #bcc4cf;
                background: #f8fafc;
            }
            QPushButton#plotRunButton,
            QPushButton#commandRunButton,
            QPushButton#sweepRunButton {
                border: 0;
                background: transparent;
                text-align: left;
                min-height: 32px;
                font-weight: 600;
                padding: 6px 8px;
            }
            QPushButton#plotRunButton:hover,
            QPushButton#commandRunButton:hover,
            QPushButton#sweepRunButton:hover {
                background: #eef6ff;
                border-radius: 5px;
            }
            QLabel#buttonModeBadge {
                color: #475569;
                background: #eef2f7;
                border: 1px solid #d8dee8;
                border-radius: 5px;
                padding: 3px 6px;
            }
            QToolButton#buttonEditButton,
            QToolButton#buttonDeleteButton {
                padding-left: 4px;
                padding-right: 4px;
            }
            QToolButton#buttonDeleteButton {
                color: #a4262c;
            }
            QWidget#root {
                background: #f3f6fb;
            }
            QWidget#controlPanel,
            QWidget#outputPanel {
                background: transparent;
            }
            QFrame#header {
                background: #ffffff;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
            }
            QLabel#appTitle {
                color: #172033;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#appSubtitle,
            QLabel#mutedLabel,
            QLabel#statusHint {
                color: #64748b;
            }
            QLabel#statusBadge {
                min-width: 92px;
                max-width: 260px;
                padding: 5px 12px;
                color: #334155;
                background: #f8fafc;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
                font-weight: 600;
            }
            QLabel#statusBadge[status="busy"] {
                color: #854d0e;
                background: #fff7ed;
                border-color: #fed7aa;
            }
            QLabel#statusBadge[status="ready"] {
                color: #166534;
                background: #ecfdf3;
                border-color: #bbf7d0;
            }
            QLabel#statusBadge[status="error"] {
                color: #991b1b;
                background: #fef2f2;
                border-color: #fecaca;
            }
            QProgressBar#headerBusyProgress {
                border: 0;
                border-radius: 4px;
                background: #e2e8f0;
            }
            QProgressBar#headerBusyProgress::chunk {
                border-radius: 4px;
                background: #2563eb;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
                margin-top: 14px;
                padding: 10px;
                color: #172033;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #334155;
                background: #ffffff;
            }
            QFrame#sectionPanel,
            QFrame#sweepPanel,
            QFrame#sweepAccentPanel {
                background: #f8fafc;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
            }
            QFrame#sweepAccentPanel {
                background: #eff6ff;
                border-color: #bfdbfe;
            }
            QLineEdit,
            QComboBox,
            QSpinBox,
            QDoubleSpinBox {
                min-height: 24px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 9px;
                background: #ffffff;
                color: #172033;
                selection-background-color: #2563eb;
            }
            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus,
            QDoubleSpinBox:focus,
            QPlainTextEdit:focus,
            QTextEdit:focus {
                border: 1px solid #2563eb;
            }
            QComboBox QAbstractItemView {
                color: #172033;
                background: #ffffff;
                border: 1px solid #cbd5e1;
                selection-background-color: #dbeafe;
                selection-color: #172033;
                outline: 0;
            }
            QPushButton,
            QToolButton {
                min-height: 24px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 12px;
                background: #ffffff;
                color: #172033;
                font-weight: 600;
            }
            QPushButton:hover,
            QToolButton:hover {
                background: #f8fafc;
                border-color: #94a3b8;
            }
            QPushButton:pressed,
            QToolButton:pressed {
                background: #e2e8f0;
                border-color: #64748b;
            }
            QPushButton:disabled,
            QToolButton:disabled,
            QComboBox:disabled,
            QLineEdit:disabled,
            QSpinBox:disabled,
            QDoubleSpinBox:disabled,
            QPlainTextEdit:disabled,
            QTextEdit:disabled {
                color: #94a3b8;
                background: #f1f5f9;
                border-color: #e2e8f0;
            }
            QPushButton#primaryButton {
                color: #ffffff;
                background: #2563eb;
                border-color: #2563eb;
            }
            QPushButton#primaryButton:hover {
                background: #1d4ed8;
                border-color: #1d4ed8;
            }
            QPushButton#dangerButton,
            QToolButton#buttonDeleteButton {
                color: #b91c1c;
                background: #ffffff;
                border-color: #fecaca;
            }
            QPushButton#dangerButton:hover,
            QToolButton#buttonDeleteButton:hover {
                color: #991b1b;
                background: #fef2f2;
                border-color: #fca5a5;
            }
            QPushButton#subtleButton {
                color: #475569;
                background: #f8fafc;
            }
            QPushButton#toggleButton:checked {
                color: #ffffff;
                background: #0f766e;
                border-color: #0f766e;
            }
            QToolButton#clearButton,
            QToolButton#openFolderButton {
                padding: 0;
                background: #ffffff;
            }
            QCheckBox {
                spacing: 8px;
                color: #334155;
            }
            QTabWidget#actionTabs::pane {
                border: 1px solid #dbe3ee;
                border-radius: 8px;
                background: #ffffff;
            }
            QTabWidget#actionTabs QTabBar::tab {
                padding: 8px 14px;
                min-width: 68px;
                color: #475569;
                background: transparent;
                border: 1px solid transparent;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabWidget#actionTabs QTabBar::tab:selected {
                color: #172033;
                background: #ffffff;
                border-color: #dbe3ee;
                border-bottom-color: #ffffff;
                font-weight: 700;
            }
            QTabWidget#actionTabs QTabBar::tab:hover:!selected {
                background: #f1f5f9;
            }
            QTextEdit#console {
                background: #101827;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 10px;
            }
            QTableWidget#sweepComboTable,
            QListWidget#postImageList,
            QListWidget#workflowStepList,
            QTextEdit#postResultText {
                border: 1px solid #dbe3ee;
                border-radius: 8px;
                background: #ffffff;
                alternate-background-color: #f8fafc;
                outline: 0;
            }
            QHeaderView::section {
                color: #334155;
                background: #f1f5f9;
                border: 0;
                border-right: 1px solid #dbe3ee;
                border-bottom: 1px solid #dbe3ee;
                padding: 7px 8px;
                font-weight: 700;
            }
            QWidget#customButtonTile {
                background: #ffffff;
                border: 1px solid #dbe3ee;
                border-radius: 8px;
            }
            QWidget#customButtonTile:hover {
                background: #f8fafc;
                border-color: #bfdbfe;
            }
            QLabel#buttonModeBadge {
                color: #0369a1;
                background: #e0f2fe;
                border: 1px solid #bae6fd;
                border-radius: 6px;
                padding: 3px 7px;
                font-weight: 700;
            }
            QStatusBar#mainStatusBar {
                background: #eef2f7;
                color: #475569;
                border-top: 1px solid #dbe3ee;
            }
            """
        )

    def _connect_signals(self) -> None:
        self.output_visible_checkbox.toggled.connect(self._set_output_visible)
        self.output_below_checkbox.toggled.connect(self._set_output_below)
        self.main_splitter.splitterMoved.connect(self._remember_output_splitter_state)
        self.action_tabs.currentChanged.connect(lambda _: self._apply_output_layout())
        self.topmost_btn.toggled.connect(self._set_topmost)
        self.browse_work_btn.clicked.connect(self._browse_work_dir)
        self.open_work_btn.clicked.connect(lambda: self._open_path_location(self.work_dir_edit, "工作目录"))
        self.browse_case_btn.clicked.connect(self._browse_case_file)
        self.open_case_btn.clicked.connect(lambda: self._open_path_location(self.case_file_edit, "Case 文件"))
        self.clear_case_btn.clicked.connect(lambda: set_combo_text(self.case_file_edit, ""))
        self.browse_launch_scm_btn.clicked.connect(lambda: self._browse_scm_file(self.launch_scm_file_edit))
        self.open_launch_scm_btn.clicked.connect(lambda: self._open_path_location(self.launch_scm_file_edit, "SCM 文件"))
        self.clear_launch_scm_btn.clicked.connect(lambda: self._set_scm_path(""))
        self.load_scm_on_start_checkbox.toggled.connect(lambda _: self._update_enabled_state())
        self.browse_file_btn.clicked.connect(self._browse_file_open)
        self.save_file_btn.clicked.connect(self._browse_file_save)
        self.open_file_btn.clicked.connect(lambda: self._open_path_location(self.file_path_edit, "Case/Data 路径"))
        self.file_use_case_btn.clicked.connect(self._use_case_path_for_file)
        self.file_use_work_btn.clicked.connect(self._use_work_dir_for_file)
        self.browse_udf_btn.clicked.connect(self._browse_udf_dir)
        self.open_udf_btn.clicked.connect(lambda: self._open_path_location(self.udf_dir_edit, "UDF 文件夹"))
        self.browse_command_scm_btn.clicked.connect(lambda: self._browse_scm_file(self.command_scm_file_edit))
        self.open_command_scm_btn.clicked.connect(lambda: self._open_path_location(self.command_scm_file_edit, "SCM 文件"))
        self.load_scm_btn.clicked.connect(self._load_scm)
        self.mesh_check_btn.clicked.connect(lambda: self._run_quick_command("检查网格", "/mesh/check"))
        self.initialize_btn.clicked.connect(self._initialize)
        self.iterate_btn.clicked.connect(self._iterate)
        self.stop_calc_btn.clicked.connect(self._stop_calculation)
        self.start_btn.clicked.connect(self._start_fluent)
        self.stop_btn.clicked.connect(self._stop_fluent)
        self.read_case_btn.clicked.connect(self._read_case)
        self.read_data_btn.clicked.connect(self._read_data)
        self.write_case_btn.clicked.connect(self._write_case)
        self.write_data_btn.clicked.connect(self._write_data)
        self.write_case_data_btn.clicked.connect(self._write_case_data)
        self.build_udf_btn.clicked.connect(self._build_udf)
        self.execute_on_demand_btn.clicked.connect(self._execute_on_demand)
        self.use_preset_btn.clicked.connect(self._use_preset_command)
        self.run_preset_btn.clicked.connect(self._run_preset_command)
        self.add_preset_btn.clicked.connect(self._add_preset_command)
        self.remove_preset_btn.clicked.connect(self._remove_preset_command)
        self.clear_command_btn.clicked.connect(self._clear_command_input)
        self.command_mode_combo.currentIndexChanged.connect(lambda _: self._command_mode_changed())
        self.add_command_button_btn.clicked.connect(self._add_command_button)
        self.add_command_button_from_input_btn.clicked.connect(self._add_command_button_from_input)
        self.reset_command_buttons_btn.clicked.connect(self._reset_command_buttons)
        self.add_workflow_btn.clicked.connect(self._add_workflow)
        self.edit_workflow_btn.clicked.connect(self._edit_workflow)
        self.delete_workflow_btn.clicked.connect(self._delete_workflow)
        self.browse_sweep_module_path_btn.clicked.connect(lambda: self._browse_sweep_tool_file(self.sweep_module_path_edit, "选择 sweep.py"))
        self.open_sweep_module_path_btn.clicked.connect(lambda: self._open_path_location(self.sweep_module_path_edit, "sweep.py"))
        self.browse_sweep_config_path_btn.clicked.connect(lambda: self._browse_sweep_tool_file(self.sweep_config_path_edit, "选择 sweep_config.py"))
        self.open_sweep_config_path_btn.clicked.connect(lambda: self._open_path_location(self.sweep_config_path_edit, "sweep_config.py"))
        self.load_sweep_config_btn.clicked.connect(self._load_sweep_config)
        self.save_sweep_grid_btn.clicked.connect(self._save_sweep_param_grid_text)
        self.preview_sweep_combos_btn.clicked.connect(self._refresh_sweep_combos)
        self.sweep_combo_list.currentCellChanged.connect(lambda *_args: self._update_sweep_preview())
        self.sweep_combo_list.itemChanged.connect(lambda _: self._update_sweep_summary_label())
        self.sweep_combo_list.itemSelectionChanged.connect(self._update_sweep_summary_label)
        self.sweep_combo_filter_param_combo.currentIndexChanged.connect(lambda _: self._sweep_filter_param_changed())
        self.sweep_combo_filter_value_combo.currentIndexChanged.connect(lambda _: self._apply_sweep_combo_filter())
        self.sweep_combo_filter_select_btn.clicked.connect(lambda _checked=False: self._select_sweep_filter_matches(True))
        self.sweep_combo_filter_unselect_btn.clicked.connect(lambda _checked=False: self._select_sweep_filter_matches(False))
        self.sweep_combo_filter_only_checkbox.toggled.connect(lambda _checked=False: self._apply_sweep_combo_filter())
        self.sweep_preview_toggle.toggled.connect(self._set_sweep_preview_visible)
        self.sweep_advanced_box.toggled.connect(self._set_sweep_advanced_visible)
        self.browse_sweep_scan_dir_btn.clicked.connect(self._browse_sweep_scan_dir)
        self.open_sweep_scan_dir_btn.clicked.connect(lambda: self._open_path_location(self.sweep_scan_dir_edit, "扫描工作目录"))
        self.browse_sweep_base_case_btn.clicked.connect(self._browse_sweep_base_case)
        self.open_sweep_base_case_btn.clicked.connect(lambda: self._open_path_location(self.sweep_base_case_edit, "基准 Case"))
        self.select_all_sweep_combos_btn.clicked.connect(lambda _checked=False: self._select_all_sweep_combos())
        self.clear_sweep_selection_btn.clicked.connect(lambda _checked=False: self._clear_sweep_combo_selection())
        self.scan_sweep_completed_btn.clicked.connect(lambda _checked=False: self._scan_sweep_completed_statuses())
        self.reset_sweep_status_btn.clicked.connect(lambda _checked=False: self._reset_sweep_combo_statuses())
        self.add_sweep_button_btn.clicked.connect(self._add_sweep_button)
        self.reset_sweep_buttons_btn.clicked.connect(self._reset_sweep_buttons)
        self.add_sweep_workflow_btn.clicked.connect(self._add_sweep_workflow)
        self.edit_sweep_workflow_btn.clicked.connect(self._edit_sweep_workflow)
        self.delete_sweep_workflow_btn.clicked.connect(self._delete_sweep_workflow)
        self.run_sweep_workflow_btn.clicked.connect(lambda: self._run_sweep_selected_workflow())
        self.run_all_sweep_workflow_btn.clicked.connect(lambda: self._run_sweep_all_workflow())
        self.pause_sweep_btn.clicked.connect(self._pause_sweep)
        self.resume_sweep_btn.clicked.connect(self._resume_sweep)
        self.retry_sweep_btn.clicked.connect(self._retry_sweep_current)
        self.stop_sweep_btn.clicked.connect(self._stop_sweep)
        self.preset_combo.activated.connect(lambda _: self._use_preset_command())
        self.send_btn.clicked.connect(self._send_command)
        self.command_edit.lineEdit().returnPressed.connect(self._send_command)
        self.clear_console_btn.clicked.connect(self._clear_console)
        self.browse_post_dir_btn.clicked.connect(self._browse_post_dir)
        self.open_post_dir_btn.clicked.connect(lambda: self._open_path_location(self.post_output_dir_edit, "后处理目录"))
        self.refresh_post_btn.clicked.connect(lambda _checked=False: self._refresh_post_results())
        self.run_post_command_btn.clicked.connect(self._run_post_command)
        self.save_picture_btn.clicked.connect(self._save_post_picture)
        self.post_object_type_combo.currentIndexChanged.connect(lambda _: self._post_object_type_changed())
        self.refresh_post_objects_btn.clicked.connect(self._refresh_post_object_names)
        self.display_post_object_btn.clicked.connect(lambda: self._run_post_object_action("display"))
        self.save_post_object_image_btn.clicked.connect(lambda: self._run_post_object_action("save_image"))
        self.write_post_object_data_btn.clicked.connect(lambda: self._run_post_object_action("write_data"))
        self.open_post_results_btn.clicked.connect(self._open_post_results_window)
        self.add_plot_button_btn.clicked.connect(self._add_plot_button)
        self.reset_plot_buttons_btn.clicked.connect(self._reset_plot_buttons)

        self.app_signals.log.connect(self._queue_console_text)
        self.app_signals.status.connect(self._set_status)
        self.app_signals.busy_changed.connect(self._set_busy)
        self.app_signals.session_changed.connect(lambda _: self._update_enabled_state())
        self.app_signals.sweep_combo_status.connect(self._set_sweep_combo_status)
        self.app_signals.sweep_progress.connect(self._set_sweep_progress)
        self.window_signals.task_finished.connect(self._task_finished)
        self.window_signals.interrupt_finished.connect(self._interrupt_finished)
        self.window_signals.post_image_ready.connect(self._open_post_image_window)
        self.window_signals.post_results_scanned.connect(self._post_results_scanned)
        self.window_signals.post_objects_loaded.connect(self._post_objects_loaded)
        self.window_signals.sweep_disk_scan_progress.connect(self._set_sweep_disk_scan_progress)
        self.window_signals.sweep_disk_scan_finished.connect(self._sweep_disk_scan_finished)

    def _restore_settings(self) -> None:
        default_work = DEFAULT_WORK_DIR if DEFAULT_WORK_DIR.exists() else TOOL_ROOT
        self._restore_combo("work_dir", self.work_dir_edit, str(default_work))
        self._restore_combo("case_file", self.case_file_edit, "")
        self._restore_combo("file_path", self.file_path_edit, "")
        self._restore_combo("udf_dir", self.udf_dir_edit, "")
        self._restore_combo("scm_file", self.launch_scm_file_edit, "")
        self._restore_combo("scm_file", self.command_scm_file_edit, combo_text(self.launch_scm_file_edit))
        self._restore_combo("post_output_dir", self.post_output_dir_edit, "")
        self._restore_combo("post_command", self.post_command_edit, "")
        self._restore_combo("init_zone_type", self.init_zone_type_edit, DEFAULT_INIT_ZONE_TYPE)
        self._restore_combo("init_zone_name", self.init_zone_name_edit, DEFAULT_INIT_ZONE_NAME)
        self._restore_combo("init_phase", self.init_phase_edit, DEFAULT_INIT_PHASE)
        self._append_combo_items(self.init_zone_type_edit, COMMON_INIT_ZONE_TYPES)
        self._append_combo_items(self.init_phase_edit, COMMON_INIT_PHASES)
        self._restore_on_demand_functions()
        self.command_mode_combo.setCurrentIndex(1 if self.settings.value("command_mode", "tui") == "python" else 0)
        self._restore_command_text_combo()
        self._restore_command_presets()
        self._restore_command_buttons()
        self._restore_workflows()
        self.sweep_preview_toggle.setChecked(
            coerce_bool(self.settings.value("sweep_preview_visible", False), False)
        )
        self.sweep_advanced_box.setChecked(
            coerce_bool(self.settings.value("sweep_advanced_visible", False), False)
        )
        self._restore_sweep_page()
        self.dim_combo.setCurrentText(str(self.settings.value("dimension", "2D") or "2D"))
        self.cores_spin.setValue(safe_int(self.settings.value("cores", 1), 1, minimum=1, maximum=256))
        self.gui_checkbox.setChecked(coerce_bool(self.settings.value("show_gui", True), True))
        self.load_scm_on_start_checkbox.setChecked(
            coerce_bool(self.settings.value("load_scm_on_start", False), False)
        )
        self.output_visible_checkbox.setChecked(coerce_bool(self.settings.value("output_visible", True), True))
        self.output_below_checkbox.setChecked(coerce_bool(self.settings.value("output_below", False), False))
        self._apply_output_layout()
        self.topmost_btn.setChecked(coerce_bool(self.settings.value("topmost", False), False))
        self.iterations_spin.setValue(
            safe_int(self.settings.value("quick_iterations", 100), 100, minimum=1, maximum=100000)
        )
        if not combo_text(self.post_output_dir_edit):
            set_combo_text(self.post_output_dir_edit, str(self._default_post_dir()))
        self._restore_plot_buttons()
        self._refresh_post_results()
        tab_index = safe_int(self.settings.value("current_tab", 0), 0, minimum=0)
        if 0 <= tab_index < self.action_tabs.count():
            self.action_tabs.setCurrentIndex(tab_index)
            self._apply_output_layout()

    def _restore_combo(self, key: str, combo: QComboBox, default: str) -> None:
        current = clean_entry(str(self.settings.value(key, default) or default))
        items = read_history(self.settings, key)
        if current and current.lower() not in {item.lower() for item in items}:
            items.insert(0, current)
        populate_combo(combo, items[:HISTORY_LIMIT], current)

    def _remember_combo(self, key: str, combo: QComboBox) -> str:
        current = combo_text(combo)
        self.settings.setValue(key, current)
        items = remember_history(self.settings, key, current)
        populate_combo(combo, items, current)
        return current

    def _restore_command_text_combo(self) -> None:
        key = self._command_history_key()
        current = clean_text(str(self.settings.value(key, "") or ""))
        items = read_text_history(self.settings, key)
        if current and current.lower() not in {item.lower() for item in items}:
            items.insert(0, current)
        populate_combo(self.command_edit, items[:HISTORY_LIMIT], current)
        self._update_command_placeholder()

    def _remember_command_text(self, value: str = "") -> str:
        current = clean_text(value or combo_plain_text(self.command_edit))
        key = self._command_history_key()
        self.settings.setValue(key, current)
        items = remember_text_history(self.settings, key, current)
        populate_combo(self.command_edit, items, current)
        self._update_command_placeholder()
        return current

    def _append_combo_items(self, combo: QComboBox, items: list[str]) -> None:
        current = combo_text(combo)
        existing = {combo.itemText(index).lower() for index in range(combo.count())}
        combo.blockSignals(True)
        for item in items:
            text = clean_entry(item)
            if text and text.lower() not in existing:
                combo.addItem(text)
                existing.add(text.lower())
        combo.setCurrentText(current)
        combo.blockSignals(False)

    def _apply_output_layout(self) -> None:
        visible = self.output_visible_checkbox.isChecked()
        below = self.output_below_checkbox.isChecked()
        post_active = (
            hasattr(self, "action_tabs")
            and self.action_tabs.currentIndex() == getattr(self, "post_tab_index", -1)
        )
        self._applying_output_layout = True
        try:
            self.output_panel.setVisible(visible)
            self.output_below_checkbox.setEnabled(visible)

            if not visible:
                self.control_panel.setMinimumWidth(480)
                self.control_panel.setMaximumWidth(16_777_215)
                self.control_panel.setMinimumHeight(0)
                self.output_panel.setMinimumWidth(0)
                self.output_panel.setMinimumHeight(0)
                self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
                self.main_splitter.setSizes([max(self.width(), 1000), 0])
                return

            self.main_splitter.setOrientation(Qt.Orientation.Vertical if below else Qt.Orientation.Horizontal)
            if below:
                self.control_panel.setMinimumWidth(0)
                self.control_panel.setMaximumWidth(16_777_215)
                self.control_panel.setMinimumHeight(300)
                self.output_panel.setMinimumWidth(0)
                self.output_panel.setMinimumHeight(190)
                self._restore_output_splitter_state([520, 300])
            else:
                self.control_panel.setMinimumWidth(480)
                self.control_panel.setMaximumWidth(16_777_215)
                self.control_panel.setMinimumHeight(0)
                self.output_panel.setMinimumWidth(260)
                self.output_panel.setMinimumHeight(0)
                self._restore_output_splitter_state([900, 460] if post_active else [760, 600])
        finally:
            self._applying_output_layout = False

    def _output_splitter_key(self, below: bool | None = None) -> str:
        is_below = self.output_below_checkbox.isChecked() if below is None else below
        return "splitter/output_below" if is_below else "splitter/output_side"

    def _restore_output_splitter_state(self, default_sizes: list[int]) -> bool:
        state = self.settings.value(self._output_splitter_key())
        if state is not None:
            with contextlib.suppress(Exception):
                if self.main_splitter.restoreState(state):
                    return True
        self.main_splitter.setSizes(default_sizes)
        return False

    def _remember_output_splitter_state(
        self, *_args: Any, force: bool = False, below: bool | None = None
    ) -> None:
        if self._applying_output_layout:
            return
        if not force and (not self.output_visible_checkbox.isChecked() or not self.output_panel.isVisible()):
            return
        with contextlib.suppress(Exception):
            self.settings.setValue(self._output_splitter_key(below), self.main_splitter.saveState())

    def _set_output_visible(self, enabled: bool) -> None:
        if not enabled:
            self._remember_output_splitter_state(force=True)
        self.settings.setValue("output_visible", bool(enabled))
        self._apply_output_layout()

    def _set_output_below(self, enabled: bool) -> None:
        self._remember_output_splitter_state(force=True, below=not enabled)
        self.settings.setValue("output_below", bool(enabled))
        self._apply_output_layout()

    def _apply_topmost_native(self, topmost: bool, report_error: bool = True) -> bool:
        if not sys.platform.startswith("win") or USER32 is None or not self.isVisible():
            return False
        hwnd = int(self.winId())
        insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
        ok = bool(
            USER32.SetWindowPos(
                wintypes.HWND(hwnd),
                wintypes.HWND(insert_after),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
        )
        if ok:
            if topmost:
                self.raise_()
                self.activateWindow()
            return True

        if report_error:
            error_code = ctypes.get_last_error()
            self.statusBar().showMessage(f"置顶切换失败：WinError {error_code}", 5000)
            self._queue_console_text(f"[{now_text()}] 置顶切换失败：WinError {error_code}\n")
        return False

    def _set_topmost(self, enabled: bool) -> None:
        topmost = bool(enabled)
        self.settings.setValue("topmost", topmost)
        self.topmost_btn.setText("已置顶" if topmost else "置顶")
        if sys.platform.startswith("win") and self.isVisible():
            if self._apply_topmost_native(topmost):
                return
            self.topmost_btn.blockSignals(True)
            self.topmost_btn.setChecked(not topmost)
            self.topmost_btn.setText("已置顶" if not topmost else "置顶")
            self.topmost_btn.blockSignals(False)
            self.settings.setValue("topmost", not topmost)
            return
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, topmost)
        if self.isVisible():
            self.show()

    def _restore_on_demand_functions(self) -> None:
        current = clean_entry(
            str(self.settings.value("on_demand_function", DEFAULT_ON_DEMAND_FUNCTIONS[0]) or "")
        )
        items = read_history(self.settings, "on_demand_function")
        for item in DEFAULT_ON_DEMAND_FUNCTIONS:
            if item.lower() not in {existing.lower() for existing in items}:
                items.append(item)
        if current and current.lower() not in {item.lower() for item in items}:
            items.insert(0, current)
        populate_combo(self.on_demand_function_edit, items[:HISTORY_LIMIT], current or DEFAULT_ON_DEMAND_FUNCTIONS[0])

    def _remember_on_demand_function(self, function_name: str = "") -> str:
        current = clean_entry(function_name or combo_text(self.on_demand_function_edit))
        self.settings.setValue("on_demand_function", current)
        items = remember_history(self.settings, "on_demand_function", current)
        for item in DEFAULT_ON_DEMAND_FUNCTIONS:
            if item.lower() not in {existing.lower() for existing in items}:
                items.append(item)
        populate_combo(self.on_demand_function_edit, items[:HISTORY_LIMIT], current)
        return current

    def _command_mode(self) -> str:
        return str(self.command_mode_combo.currentData() or "tui")

    def _command_history_key(self) -> str:
        return "python_command" if self._command_mode() == "python" else "command"

    def _command_presets_key(self) -> str:
        return "python_command_presets" if self._command_mode() == "python" else "command_presets"

    def _default_command_presets(self) -> list[str]:
        return list(DEFAULT_PYFLUENT_PRESETS if self._command_mode() == "python" else DEFAULT_COMMAND_PRESETS)

    def _update_command_placeholder(self) -> None:
        line_edit = self.command_edit.lineEdit()
        if line_edit is None:
            return
        if self._command_mode() == "python":
            line_edit.setPlaceholderText('输入 PyFluent Python，例如：solver.tui.solve.iterate(100)')
        else:
            line_edit.setPlaceholderText('输入 TUI 命令，例如：/file/read-case "case.cas.h5"')

    def _command_mode_changed(self) -> None:
        self.settings.setValue("command_mode", self._command_mode())
        self._restore_command_text_combo()
        self._restore_command_presets()
        self._update_command_placeholder()

    def _read_command_presets(self) -> list[str]:
        defaults = self._default_command_presets()
        raw = self.settings.value(self._command_presets_key(), [])
        if isinstance(raw, (list, tuple)):
            items = [clean_text(str(item)) for item in raw]
        elif raw:
            items = [clean_text(item) for item in str(raw).splitlines()]
        else:
            items = list(defaults)
        if not any(items):
            items = list(defaults)
        for default in defaults:
            if default.lower() not in {item.lower() for item in items}:
                items.append(default)

        repaired_items: list[str] = []
        for item in items:
            is_truncated_default = any(
                default.endswith('"')
                and default.lower().startswith(item.lower())
                and len(default) - len(item) == 1
                for default in defaults
            )
            if not is_truncated_default:
                repaired_items.append(item)
        items = repaired_items

        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            marker = item.lower()
            if item and marker not in seen:
                seen.add(marker)
                result.append(item)
        return result

    def _save_command_presets(self, items: list[str], current: str = "") -> None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = clean_text(item)
            marker = text.lower()
            if text and marker not in seen:
                seen.add(marker)
                cleaned.append(text)
        self.settings.setValue(self._command_presets_key(), cleaned)
        populate_combo(self.preset_combo, cleaned, current if current in cleaned else (cleaned[0] if cleaned else ""))

    def _restore_command_presets(self) -> None:
        self._save_command_presets(self._read_command_presets())

    def _clear_grid_widgets(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _custom_button_tile(
        self,
        name: str,
        tooltip: str,
        run_object_name: str,
        mode_label: str,
        run_callback: Callable[[], None],
        edit_callback: Callable[[], None],
        delete_callback: Callable[[], None],
    ) -> tuple[QWidget, QPushButton, QToolButton, QToolButton]:
        tile = QWidget()
        tile.setObjectName("customButtonTile")
        tile_layout = QHBoxLayout(tile)
        tile_layout.setContentsMargins(4, 4, 4, 4)
        tile_layout.setSpacing(6)

        display_name = name if len(name) <= 22 else f"{name[:21]}..."
        run_button = QPushButton(display_name)
        run_button.setObjectName(run_object_name)
        run_button.setToolTip(f"{name}\n{tooltip}" if tooltip else name)
        run_button.setMinimumHeight(34)
        run_button.setMinimumWidth(0)
        run_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        run_button.clicked.connect(lambda _checked=False: run_callback())
        tile_layout.addWidget(run_button, 1)

        if mode_label:
            badge = QLabel(mode_label)
            badge.setObjectName("buttonModeBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(badge)

        edit_button = QToolButton()
        edit_button.setText("编辑")
        edit_button.setObjectName("buttonEditButton")
        edit_button.setFixedSize(48, 32)
        edit_button.setToolTip(f"编辑：{name}")
        edit_button.clicked.connect(lambda _checked=False: edit_callback())
        tile_layout.addWidget(edit_button)

        delete_button = QToolButton()
        delete_button.setText("删除")
        delete_button.setObjectName("buttonDeleteButton")
        delete_button.setFixedSize(48, 32)
        delete_button.setToolTip(f"删除：{name}")
        delete_button.clicked.connect(lambda _checked=False: delete_callback())
        tile_layout.addWidget(delete_button)
        return tile, run_button, edit_button, delete_button

    def _read_command_buttons(self) -> list[dict[str, str]]:
        raw = self.settings.value("command_buttons", "")
        items: Any = []
        has_saved_value = False
        if isinstance(raw, str) and raw.strip():
            has_saved_value = True
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                has_saved_value = False
                items = []
        elif isinstance(raw, list):
            has_saved_value = True
            items = raw
        buttons = [normalize_command_button(item) for item in items if isinstance(item, dict)]
        buttons = [item for item in buttons if item["command"]]
        return buttons if has_saved_value else default_command_buttons()

    def _save_command_buttons(self, buttons: list[dict[str, str]], refresh: bool = False) -> None:
        cleaned = [normalize_command_button(item) for item in buttons]
        cleaned = [item for item in cleaned if item["command"]]
        self.command_buttons = cleaned
        self.settings.setValue("command_buttons", json.dumps(cleaned, ensure_ascii=False))
        if refresh:
            self._refresh_command_buttons()

    def _restore_command_buttons(self) -> None:
        self._save_command_buttons(self._read_command_buttons(), refresh=True)

    def _refresh_command_buttons(self) -> None:
        self._clear_grid_widgets(self.command_button_grid)
        self.command_run_buttons = []
        self.command_edit_buttons = []
        self.command_delete_buttons = []
        self.command_button_empty_label.setVisible(not self.command_buttons)

        for index, button_data in enumerate(self.command_buttons):
            name = button_data["name"]
            mode = button_data["mode"]
            command = button_data["command"]
            mode_label = "Py" if mode == "python" else "TUI"
            tooltip = f"{mode_label}\n{command[:1200]}"
            tile, run_button, edit_button, delete_button = self._custom_button_tile(
                name,
                tooltip,
                "commandRunButton",
                mode_label,
                lambda row=index: self._run_command_button(row),
                lambda row=index: self._edit_command_button(row),
                lambda row=index: self._delete_command_button(row),
            )
            self.command_run_buttons.append(run_button)
            self.command_edit_buttons.append(edit_button)
            self.command_delete_buttons.append(delete_button)
            row = index // 2
            column = index % 2
            self.command_button_grid.addWidget(tile, row, column)
            self.command_button_grid.setColumnStretch(column, 1)
        self._update_enabled_state()

    def _command_button_dialog(self, button: dict[str, Any] | None = None) -> CommandButtonEditorDialog:
        return CommandButtonEditorDialog(self, button=button)

    def _add_command_button(self) -> None:
        dialog = self._command_button_dialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.command_buttons.append(dialog.button_data())
        self._save_command_buttons(self.command_buttons, refresh=True)

    def _add_command_button_from_input(self) -> None:
        command = combo_plain_text(self.command_edit)
        if not command:
            QMessageBox.information(self, "没有命令", "请先在命令输入框中输入一条命令。")
            return
        name = command.splitlines()[0].strip()[:24] or "新命令"
        dialog = self._command_button_dialog({"name": name, "mode": self._command_mode(), "command": command})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.command_buttons.append(dialog.button_data())
        self._save_command_buttons(self.command_buttons, refresh=True)

    def _edit_command_button(self, index: int) -> None:
        if index < 0 or index >= len(self.command_buttons):
            return
        dialog = self._command_button_dialog(self.command_buttons[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.command_buttons[index] = dialog.button_data()
        self._save_command_buttons(self.command_buttons, refresh=True)

    def _delete_command_button(self, index: int) -> None:
        if index < 0 or index >= len(self.command_buttons):
            return
        name = self.command_buttons[index]["name"]
        reply = QMessageBox.question(
            self,
            "删除命令按钮",
            f"删除命令按钮“{name}”吗？这会从本工具设置中移除它绑定的命令。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self.command_buttons[index]
        self._save_command_buttons(self.command_buttons, refresh=True)

    def _reset_command_buttons(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认按钮",
            "恢复默认按钮会覆盖当前命令按钮配置。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._save_command_buttons(default_command_buttons(), refresh=True)

    def _run_command_button(self, index: int) -> None:
        if index < 0 or index >= len(self.command_buttons):
            return
        button = self.command_buttons[index]
        command = button["command"].strip()
        if not command:
            QMessageBox.information(self, "没有命令", "请先编辑这个命令按钮。")
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再运行命令按钮。")
            return
        mode = button["mode"]
        self.command_mode_combo.setCurrentIndex(1 if mode == "python" else 0)
        set_combo_text(self.command_edit, command)
        history_key = "python_command" if mode == "python" else "command"
        remember_text_history(self.settings, history_key, command)
        iteration_count = self._iteration_count_from_command(command, mode)
        if iteration_count:
            self._begin_calculation_progress(iteration_count)
        if mode == "python":
            self._submit(f"命令按钮：{button['name']}", self.controller.execute_python, command)
        else:
            self._submit(f"命令按钮：{button['name']}", self.controller.execute_tui, command)

    def _read_workflows(self) -> list[dict[str, Any]]:
        raw = self.settings.value("automation_workflows", "")
        items: Any = []
        has_saved_value = False
        if isinstance(raw, str) and raw.strip():
            has_saved_value = True
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                has_saved_value = False
                items = []
        elif isinstance(raw, list):
            has_saved_value = True
            items = raw
        workflows = [normalize_workflow(item) for item in items if isinstance(item, dict)]
        workflows = [item for item in workflows if item["steps"]]
        return workflows if has_saved_value else default_workflows()

    def _save_workflows(self, workflows: list[dict[str, Any]], current_index: int = 0) -> None:
        cleaned = [normalize_workflow(item) for item in workflows]
        cleaned = [item for item in cleaned if item["steps"]]
        self.settings.setValue("automation_workflows", json.dumps(cleaned, ensure_ascii=False))
        self.workflow_combo.blockSignals(True)
        self.workflow_combo.clear()
        for item in cleaned:
            self.workflow_combo.addItem(item["name"])
        if cleaned:
            self.workflow_combo.setCurrentIndex(max(0, min(current_index, len(cleaned) - 1)))
        self.workflow_combo.blockSignals(False)
        self._refresh_workflow_buttons(cleaned)

    def _restore_workflows(self) -> None:
        self._save_workflows(self._read_workflows())

    def _default_sweep_scan_dir(self) -> Path:
        work_text = combo_text(self.work_dir_edit)
        if work_text:
            return Path(work_text).expanduser() / "sweep"
        if self.controller.work_dir is not None:
            return self.controller.work_dir / "sweep"
        return TOOL_ROOT / "sweep"

    def _current_sweep_module_path(self) -> Path:
        return _resolve_sweep_file_path(combo_text(self.sweep_module_path_edit), SWEEP_MODULE_PATH)

    def _current_sweep_config_path(self) -> Path:
        return _resolve_sweep_file_path(combo_text(self.sweep_config_path_edit), SWEEP_CONFIG_PATH)

    def _apply_sweep_tool_paths(self) -> tuple[Path, Path]:
        module_path, config_path = set_sweep_tool_paths(
            self._current_sweep_module_path(),
            self._current_sweep_config_path(),
        )
        self.sweep_tools_label.setText(f"{module_path.parent}")
        return module_path, config_path

    def _restore_sweep_page(self) -> None:
        default_scan_dir = self._default_sweep_scan_dir()
        self._restore_combo("sweep_module_path", self.sweep_module_path_edit, str(SWEEP_MODULE_PATH))
        self._restore_combo("sweep_config_path", self.sweep_config_path_edit, str(SWEEP_CONFIG_PATH))
        self._apply_sweep_tool_paths()
        self._restore_combo("sweep_scan_dir", self.sweep_scan_dir_edit, str(default_scan_dir))
        self._restore_combo("sweep_base_case", self.sweep_base_case_edit, combo_text(self.case_file_edit))
        self.sweep_iterations_spin.setValue(
            safe_int(
                self.settings.value("sweep_iterations", DEFAULT_SWEEP_ITERATIONS),
                DEFAULT_SWEEP_ITERATIONS,
                minimum=0,
                maximum=10_000_000,
            )
        )
        self.skip_completed_sweep_checkbox.setChecked(coerce_bool(self.settings.value("sweep_skip_completed", False), False))
        text = clean_text(str(self.settings.value("sweep_param_grid_text", "") or ""))
        if not text:
            text = format_sweep_param_grid(default_sweep_param_grid())
        self.sweep_grid_editor.setPlainText(text)
        self._restore_sweep_buttons()
        self._restore_sweep_workflows()
        self._refresh_sweep_combos(silent=True)
        self._set_sweep_preview_visible(self.sweep_preview_toggle.isChecked())
        self._set_sweep_advanced_visible(self.sweep_advanced_box.isChecked())

    def _current_sweep_param_grid(self) -> dict[str, list[float]]:
        return parse_sweep_param_grid_text(self.sweep_grid_editor.toPlainText())

    def _load_sweep_config(self) -> None:
        global _SWEEP_CONFIG_CACHE, _SWEEP_CONFIG_CACHE_PATH
        _SWEEP_CONFIG_CACHE = None
        _SWEEP_CONFIG_CACHE_PATH = None
        _module_path, config_path = self._apply_sweep_tool_paths()
        try:
            config = load_sweep_config_module()
            grid = normalize_sweep_param_grid(getattr(config, "PARAM_GRID"))
        except Exception as error:
            QMessageBox.warning(self, "读取参数配置失败", f"{config_path}\n\n{type(error).__name__}: {error}")
            return
        self.sweep_grid_editor.setPlainText(format_sweep_param_grid(grid))
        self.settings.setValue("sweep_param_grid_text", self.sweep_grid_editor.toPlainText())
        self._remember_combo("sweep_config_path", self.sweep_config_path_edit)
        self._refresh_sweep_combos()
        self.statusBar().showMessage(f"已读取参数配置：{config_path}")

    def _save_sweep_param_grid_text(self) -> None:
        try:
            _module_path, config_path = self._apply_sweep_tool_paths()
            grid = self._current_sweep_param_grid()
        except ValueError as error:
            QMessageBox.warning(self, "参数网格无效", str(error))
            return
        try:
            target = write_sweep_config(grid, config_path)
        except Exception as error:
            QMessageBox.warning(self, "写入失败", f"{type(error).__name__}: {error}")
            return
        global _SWEEP_CONFIG_CACHE, _SWEEP_CONFIG_CACHE_PATH
        _SWEEP_CONFIG_CACHE = None
        _SWEEP_CONFIG_CACHE_PATH = None
        self.settings.setValue("sweep_param_grid_text", self.sweep_grid_editor.toPlainText())
        self._remember_combo("sweep_config_path", self.sweep_config_path_edit)
        self._refresh_sweep_combos()
        self.statusBar().showMessage(f"参数扫描网格已保存：{target}")

    def _set_sweep_preview_visible(self, visible: bool) -> None:
        self.sweep_preview_text.setVisible(visible)
        self.settings.setValue("sweep_preview_visible", bool(visible))

    def _set_sweep_advanced_visible(self, visible: bool) -> None:
        self.sweep_advanced_tabs.setVisible(visible)
        self.sweep_advanced_box.setMaximumHeight(16_777_215 if visible else 34)
        self.settings.setValue("sweep_advanced_visible", bool(visible))

    def _sweep_combo_status_text(self, status: str) -> str:
        return {
            "pending": "○ 待执行",
            "running": "▶ 运行中",
            "success": "✓ 成功",
            "failed": "× 失败",
            "stopped": "■ 已停止",
            "skipped": "↷ 已跳过",
        }.get(status, "待执行")

    def _sweep_combo_status_sort(self, status: str) -> int:
        return {"running": 0, "failed": 1, "stopped": 2, "pending": 3, "skipped": 4, "success": 5}.get(status, 6)

    def _format_sweep_value(self, value: Any) -> str:
        try:
            return f"{float(value):.9g}"
        except (TypeError, ValueError):
            return str(value)

    def _sweep_combo_item(self, text: str, sort_value: Any = None) -> SortableTableItem:
        item = SortableTableItem(str(text))
        if sort_value is not None:
            item.setData(COMBO_SORT_ROLE, sort_value)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item

    def _sweep_combo_check_item(self, row: int) -> QTableWidgetItem | None:
        if row < 0 or row >= self.sweep_combo_list.rowCount():
            return None
        return self.sweep_combo_list.item(row, 0)

    def _sweep_combo_row_data(self, row: int) -> dict[str, Any]:
        item = self._sweep_combo_check_item(row)
        data = item.data(COMBO_DATA_ROLE) if item is not None else None
        return data if isinstance(data, dict) else {}

    def _find_sweep_combo_row(self, combo_index: int) -> int:
        for row in range(self.sweep_combo_list.rowCount()):
            data = self._sweep_combo_row_data(row)
            if safe_int(data.get("index", -1), -1) == combo_index:
                return row
        return -1

    def _set_sweep_combo_headers(self, param_keys: list[str]) -> None:
        self.sweep_combo_param_keys = list(param_keys)
        headers = ["选择", "状态", "组合", "详情", *self.sweep_combo_param_keys]
        self.sweep_combo_list.setColumnCount(len(headers))
        self.sweep_combo_list.setHorizontalHeaderLabels(headers)
        header = self.sweep_combo_list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column in range(4, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    def _apply_sweep_combo_row_status(
        self, row: int, index: int, combo: dict[str, float], status: str, detail: str = ""
    ) -> None:
        checked = Qt.CheckState.Unchecked
        existing = self._sweep_combo_check_item(row)
        if existing is not None:
            checked = existing.checkState()

        label = sweep_combo_label(index)
        summary = sweep_combo_summary(combo)
        row_data = {"index": index, "combo": dict(combo), "status": status, "detail": detail}
        tooltip = f"{label}\n{summary}"
        if detail:
            tooltip += f"\n{detail}"

        check_item = self._sweep_combo_item("", index)
        check_item.setFlags(
            check_item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
        )
        check_item.setCheckState(checked)

        items: list[QTableWidgetItem] = [
            check_item,
            self._sweep_combo_item(self._sweep_combo_status_text(status), self._sweep_combo_status_sort(status)),
            self._sweep_combo_item(label, index),
            self._sweep_combo_item(detail or summary, detail or summary),
        ]
        for key in self.sweep_combo_param_keys:
            value = combo.get(key, "")
            sort_value = value if isinstance(value, (int, float)) else None
            items.append(self._sweep_combo_item(self._format_sweep_value(value), sort_value))

        if status == "running":
            fg, bg = QColor("#8a6d00"), QColor("#fff7d6")
        elif status == "success":
            fg, bg = QColor("#107c10"), QColor("#e7f6e7")
        elif status == "failed":
            fg, bg = QColor("#a4262c"), QColor("#fde7e9")
        elif status == "stopped":
            fg, bg = QColor("#475569"), QColor("#eef2f7")
        elif status == "skipped":
            fg, bg = QColor("#245b89"), QColor("#eaf4ff")
        else:
            fg, bg = QColor("#253040"), QColor("#ffffff")

        for item in items:
            item.setData(COMBO_DATA_ROLE, row_data)
            item.setForeground(fg)
            item.setBackground(bg)
            item.setToolTip(tooltip)
        for column, item in enumerate(items):
            self.sweep_combo_list.setItem(row, column, item)

    def _update_sweep_filter_options(self, grid: dict[str, list[float]]) -> None:
        current_param = self.sweep_combo_filter_param_combo.currentData()
        current_value_text = self.sweep_combo_filter_value_combo.currentText()
        param_keys = sorted(grid.keys())

        self.sweep_combo_filter_param_combo.blockSignals(True)
        self.sweep_combo_filter_param_combo.clear()
        self.sweep_combo_filter_param_combo.addItem("全部参数", "")
        for key in param_keys:
            self.sweep_combo_filter_param_combo.addItem(key, key)
        param_index = self.sweep_combo_filter_param_combo.findData(current_param)
        self.sweep_combo_filter_param_combo.setCurrentIndex(param_index if param_index >= 0 else 0)
        self.sweep_combo_filter_param_combo.blockSignals(False)

        self._populate_sweep_filter_values(current_value_text)

    def _populate_sweep_filter_values(self, preferred_text: str = "") -> None:
        param = str(self.sweep_combo_filter_param_combo.currentData() or "")
        self.sweep_combo_filter_value_combo.blockSignals(True)
        self.sweep_combo_filter_value_combo.clear()
        self.sweep_combo_filter_value_combo.addItem("任意取值", None)
        if param:
            with contextlib.suppress(ValueError):
                grid = self._current_sweep_param_grid()
                for value in grid.get(param, []):
                    self.sweep_combo_filter_value_combo.addItem(self._format_sweep_value(value), float(value))
        value_index = self.sweep_combo_filter_value_combo.findText(preferred_text)
        self.sweep_combo_filter_value_combo.setCurrentIndex(value_index if value_index >= 0 else 0)
        self.sweep_combo_filter_value_combo.blockSignals(False)

    def _sweep_filter_param_changed(self) -> None:
        self._populate_sweep_filter_values()
        self._apply_sweep_combo_filter()

    def _sweep_row_matches_filter(self, row: int) -> bool:
        param = str(self.sweep_combo_filter_param_combo.currentData() or "")
        if not param:
            return True
        data = self._sweep_combo_row_data(row)
        combo = data.get("combo")
        if not isinstance(combo, dict) or param not in combo:
            return False
        wanted = self.sweep_combo_filter_value_combo.currentData()
        if wanted is None:
            return True
        left = safe_float(combo.get(param), 0.0)
        right = safe_float(wanted, 0.0)
        tolerance = max(1e-15, abs(right) * 1e-9)
        return abs(left - right) <= tolerance

    def _apply_sweep_combo_filter(self) -> None:
        only = self.sweep_combo_filter_only_checkbox.isChecked()
        self.sweep_combo_list.setUpdatesEnabled(False)
        try:
            for row in range(self.sweep_combo_list.rowCount()):
                self.sweep_combo_list.setRowHidden(row, bool(only and not self._sweep_row_matches_filter(row)))
        finally:
            self.sweep_combo_list.setUpdatesEnabled(True)
            self._update_sweep_summary_label()

    def _select_sweep_filter_matches(self, checked: bool) -> None:
        if self.sweep_combo_list.rowCount() == 0:
            self._refresh_sweep_combos(silent=True)
        self.sweep_combo_list.blockSignals(True)
        self.sweep_combo_list.setUpdatesEnabled(False)
        try:
            for row in range(self.sweep_combo_list.rowCount()):
                if not self._sweep_row_matches_filter(row):
                    continue
                item = self._sweep_combo_check_item(row)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.sweep_combo_list.blockSignals(False)
            self.sweep_combo_list.setUpdatesEnabled(True)
            self._update_sweep_summary_label()

    def _checked_sweep_combo_indices(self) -> list[int]:
        indices: list[int] = []
        for row in range(self.sweep_combo_list.rowCount()):
            item = self._sweep_combo_check_item(row)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            data = self._sweep_combo_row_data(row)
            index = safe_int(data.get("index", -1), -1)
            if index >= 0 and index not in indices:
                indices.append(index)
        return indices

    def _update_sweep_summary_label(self) -> None:
        total = self.sweep_combo_list.rowCount()
        visible = sum(1 for row in range(total) if not self.sweep_combo_list.isRowHidden(row))
        checked = len(self._checked_sweep_combo_indices())
        status_counts: dict[str, int] = {}
        for row in range(total):
            data = self._sweep_combo_row_data(row)
            status = str(data.get("status", "pending"))
            status_counts[status] = status_counts.get(status, 0) + 1
        parts = [f"组合 {total} 个"]
        if visible != total:
            parts.append(f"显示 {visible} 个")
        parts.append(f"已勾选 {checked} 个")
        for key, label in (
            ("running", "运行中"),
            ("success", "成功"),
            ("skipped", "已跳过"),
            ("failed", "失败"),
            ("stopped", "已停止"),
        ):
            count = status_counts.get(key, 0)
            if count:
                parts.append(f"{label} {count}")
        if self.sweep_combo_grid_summary:
            parts.append(self.sweep_combo_grid_summary)
        self.sweep_summary_label.setText("  |  ".join(parts))

    def _set_sweep_combo_status(self, combo_index: int, status: str, detail: str) -> None:
        self.sweep_combo_statuses[combo_index] = (status, detail)
        if status == "running":
            self.sweep_current_combo_index = combo_index
        sorting = self.sweep_combo_list.isSortingEnabled()
        self.sweep_combo_list.setUpdatesEnabled(False)
        self.sweep_combo_list.setSortingEnabled(False)
        row = -1
        try:
            row = self._find_sweep_combo_row(combo_index)
            if row >= 0:
                data = self._sweep_combo_row_data(row)
                combo = data.get("combo")
                if isinstance(combo, dict):
                    self._apply_sweep_combo_row_status(row, combo_index, combo, status, detail)
        finally:
            self.sweep_combo_list.setSortingEnabled(sorting)
            self.sweep_combo_list.setUpdatesEnabled(True)
        if row >= 0:
            item = self._sweep_combo_check_item(row)
            if item is not None:
                self.sweep_combo_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._apply_sweep_combo_filter()

    def _reset_sweep_combo_statuses(self) -> None:
        self.sweep_combo_statuses.clear()
        self.sweep_current_combo_index = None
        sorting = self.sweep_combo_list.isSortingEnabled()
        self.sweep_combo_list.setUpdatesEnabled(False)
        self.sweep_combo_list.setSortingEnabled(False)
        try:
            for row in range(self.sweep_combo_list.rowCount()):
                data = self._sweep_combo_row_data(row)
                combo = data.get("combo")
                index = safe_int(data.get("index", row), row, minimum=0)
                if isinstance(combo, dict):
                    self._apply_sweep_combo_row_status(row, index, combo, "pending")
        finally:
            self.sweep_combo_list.setSortingEnabled(sorting)
            self.sweep_combo_list.setUpdatesEnabled(True)
        self._update_sweep_summary_label()

    def _scan_sweep_completed_statuses(self) -> None:
        if self.sweep_disk_scan_active:
            return
        try:
            grid = self._current_sweep_param_grid()
            combos = list_sweep_combos(grid)
            scan_path = require_path(combo_text(self.sweep_scan_dir_edit), "扫描工作目录")
        except ValueError as error:
            QMessageBox.warning(self, "扫描配置不可用", str(error))
            return
        if not scan_path.exists() or not scan_path.is_dir():
            QMessageBox.warning(self, "扫描目录不存在", f"扫描工作目录不存在：{scan_path}")
            return

        combo_entries = [(index, sweep_combo_label(index), sweep_combo_dir_name(index)) for index, _combo in enumerate(combos)]
        self.sweep_disk_scan_active = True
        self.sweep_progress_bar.setRange(0, max(1, len(combo_entries)))
        self.sweep_progress_bar.setValue(0)
        self.sweep_progress_bar.setFormat(f"0 / {len(combo_entries)}")
        self.sweep_progress_label.setText("扫描进度：正在扫描已有结果")
        self.scan_sweep_completed_btn.setText("扫描中...")
        self._update_enabled_state()

        def emit_progress(done: int, total: int, message: str) -> None:
            self.window_signals.sweep_disk_scan_progress.emit(done, total, message)

        try:
            future = self.scan_executor.submit(scan_sweep_disk_statuses, combo_entries, scan_path, emit_progress)
        except Exception:
            self.sweep_disk_scan_active = False
            self.scan_sweep_completed_btn.setText("扫描已完成")
            self.sweep_progress_bar.setFormat("扫描提交失败")
            self.sweep_progress_label.setText("扫描进度：提交失败")
            self._queue_console_text(f"[{now_text()}] 扫描 sweep 目录任务提交失败：\n{traceback.format_exc()}\n")
            self._set_status("扫描 sweep 目录提交失败")
            self._update_enabled_state()
            return
        future.add_done_callback(self._on_sweep_disk_scan_done)

    def _on_sweep_disk_scan_done(self, future: Future) -> None:
        error = ""
        result: dict[str, Any] = {}
        try:
            result = future.result()
        except Exception:
            error = traceback.format_exc()
        with contextlib.suppress(RuntimeError):
            self.window_signals.sweep_disk_scan_finished.emit(result, error)

    def _set_sweep_disk_scan_progress(self, done: int, total: int, message: str) -> None:
        if not self.sweep_disk_scan_active:
            return
        total = max(1, safe_int(total, 1, minimum=1))
        value = max(0, min(safe_int(done, 0, minimum=0), total))
        self.sweep_progress_bar.setRange(0, total)
        self.sweep_progress_bar.setValue(value)
        self.sweep_progress_bar.setFormat(f"{value} / {total}")
        self.sweep_progress_label.setText(f"扫描进度：{message}")

    def _sweep_disk_scan_finished(self, result: dict[str, Any], error: str) -> None:
        self.sweep_disk_scan_active = False
        self.scan_sweep_completed_btn.setText("扫描已完成")
        if error:
            self.sweep_progress_bar.setFormat("扫描失败")
            self.sweep_progress_label.setText("扫描进度：扫描失败")
            self._queue_console_text(f"[{now_text()}] 扫描 sweep 目录失败：\n{error}\n")
            self._set_status("扫描 sweep 目录失败")
            self._update_enabled_state()
            return

        statuses = result.get("statuses", {})
        if isinstance(statuses, dict):
            self.sweep_combo_statuses = {
                safe_int(index, -1): tuple(value)  # type: ignore[arg-type]
                for index, value in statuses.items()
                if safe_int(index, -1) >= 0 and isinstance(value, (list, tuple)) and len(value) >= 2
            }
        self._refresh_sweep_combos(silent=True)
        counts = result.get("counts", {}) if isinstance(result.get("counts", {}), dict) else {}
        completed_count = safe_int(counts.get("success", 0), 0, minimum=0)
        failed_count = safe_int(counts.get("failed", 0), 0, minimum=0)
        stopped_count = safe_int(counts.get("stopped", 0), 0, minimum=0)
        message = f"已扫描 sweep 目录：完成 {completed_count}，失败 {failed_count}，停止 {stopped_count}"
        self.sweep_progress_bar.setValue(self.sweep_progress_bar.maximum())
        self.sweep_progress_bar.setFormat("扫描完成")
        self.sweep_progress_label.setText(f"扫描进度：{message}")
        self.statusBar().showMessage(message)
        self._queue_console_text(f"[{now_text()}] {message}：{result.get('scan_dir', '')}\n")
        self._update_enabled_state()

    def _select_all_sweep_combos(self) -> None:
        if self.sweep_combo_list.rowCount() == 0:
            self._refresh_sweep_combos(silent=True)
        self.sweep_combo_list.blockSignals(True)
        self.sweep_combo_list.setUpdatesEnabled(False)
        try:
            for row in range(self.sweep_combo_list.rowCount()):
                if self.sweep_combo_list.isRowHidden(row):
                    continue
                item = self._sweep_combo_check_item(row)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Checked)
            self.sweep_combo_list.selectAll()
        finally:
            self.sweep_combo_list.blockSignals(False)
            self.sweep_combo_list.setUpdatesEnabled(True)
            self._update_sweep_summary_label()

    def _clear_sweep_combo_selection(self) -> None:
        self.sweep_combo_list.blockSignals(True)
        self.sweep_combo_list.setUpdatesEnabled(False)
        try:
            for row in range(self.sweep_combo_list.rowCount()):
                item = self._sweep_combo_check_item(row)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Unchecked)
            self.sweep_combo_list.clearSelection()
        finally:
            self.sweep_combo_list.blockSignals(False)
            self.sweep_combo_list.setUpdatesEnabled(True)
            self._update_sweep_summary_label()

    def _refresh_sweep_combos(self, silent: bool = False) -> bool:
        self._apply_sweep_tool_paths()
        current_data = self._sweep_combo_row_data(self.sweep_combo_list.currentRow())
        current_combo_index = safe_int(current_data.get("index", -1), -1)
        checked_indices = set(self._checked_sweep_combo_indices())
        try:
            grid = self._current_sweep_param_grid()
            combo_count = sweep_combo_count(grid)
            if combo_count > SWEEP_COMBO_UI_LIMIT:
                raise OverflowError(
                    f"当前参数网格会生成 {combo_count:,} 个组合，超过界面安全上限 "
                    f"{SWEEP_COMBO_UI_LIMIT:,}。请缩小参数范围或拆分扫描。"
                )
            combos = list_sweep_combos(grid)
        except (ValueError, OverflowError) as error:
            self.sweep_combo_grid_summary = ""
            self.sweep_combo_list.blockSignals(True)
            self.sweep_combo_list.setUpdatesEnabled(False)
            self.sweep_combo_list.setSortingEnabled(False)
            self.sweep_combo_list.clearContents()
            self.sweep_combo_list.setRowCount(0)
            self.sweep_combo_list.blockSignals(False)
            self.sweep_combo_list.setUpdatesEnabled(True)
            self.sweep_preview_text.clear()
            self._update_sweep_filter_options({})
            self._update_enabled_state()
            self.sweep_summary_label.setText("参数网格不可用")
            if not silent:
                QMessageBox.warning(self, "参数网格不可用", str(error))
            return False

        param_keys = sorted(grid.keys())
        self.sweep_combo_list.blockSignals(True)
        self.sweep_combo_list.setUpdatesEnabled(False)
        try:
            self.sweep_combo_list.setSortingEnabled(False)
            self.sweep_combo_list.clearContents()
            self._set_sweep_combo_headers(param_keys)
            self.sweep_combo_list.setRowCount(len(combos))
            for row, combo in enumerate(combos):
                status, detail = self.sweep_combo_statuses.get(row, ("pending", ""))
                self._apply_sweep_combo_row_status(row, row, combo, status, detail)
                item = self._sweep_combo_check_item(row)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Checked if row in checked_indices else Qt.CheckState.Unchecked)
        finally:
            self.sweep_combo_list.setSortingEnabled(True)
            self.sweep_combo_list.blockSignals(False)
            self.sweep_combo_list.setUpdatesEnabled(True)

        target_row = self._find_sweep_combo_row(current_combo_index)
        if target_row < 0 and combos:
            target_row = 0
        if target_row >= 0:
            self.sweep_combo_list.setCurrentCell(target_row, 0)
            self.sweep_combo_list.selectRow(target_row)

        parts = [f"{key}×{len(values)}" for key, values in sorted(grid.items())]
        self.sweep_combo_grid_summary = "，".join(parts)
        self._update_sweep_filter_options(grid)
        self._apply_sweep_combo_filter()
        self._update_sweep_preview()
        self._update_enabled_state()
        return True

    def _selected_sweep_combo(self) -> tuple[int, dict[str, float], int]:
        if self.sweep_combo_list.rowCount() == 0 and not self._refresh_sweep_combos(silent=True):
            raise ValueError("请先填写有效的参数网格。")
        row = self.sweep_combo_list.currentRow()
        if row < 0:
            checked_indices = set(self._checked_sweep_combo_indices())
            for candidate_row in range(self.sweep_combo_list.rowCount()):
                data = self._sweep_combo_row_data(candidate_row)
                if safe_int(data.get("index", -1), -1) in checked_indices:
                    row = candidate_row
                    self.sweep_combo_list.setCurrentCell(row, 0)
                    break
        if row < 0 and self.sweep_combo_list.rowCount():
            row = 0
            self.sweep_combo_list.setCurrentCell(row, 0)
        if row < 0:
            raise ValueError("当前没有可用的参数组合。")
        data = self._sweep_combo_row_data(row)
        combo = data.get("combo")
        if not isinstance(combo, dict):
            raise ValueError("当前参数组合不可用，请刷新组合。")
        return safe_int(data.get("index", 0), 0, minimum=0), combo, self.sweep_combo_list.rowCount()

    def _selected_sweep_combo_indices(self, include_all: bool = False) -> list[int]:
        if self.sweep_combo_list.rowCount() == 0 and not self._refresh_sweep_combos(silent=True):
            raise ValueError("请先填写有效的参数网格。")
        rows: list[int] = []
        if include_all:
            rows = list(range(self.sweep_combo_list.rowCount()))
        else:
            checked = set(self._checked_sweep_combo_indices())
            if checked:
                for row in range(self.sweep_combo_list.rowCount()):
                    data = self._sweep_combo_row_data(row)
                    if safe_int(data.get("index", -1), -1) in checked:
                        rows.append(row)
            else:
                for item in self.sweep_combo_list.selectedItems():
                    if item.row() not in rows:
                        rows.append(item.row())
        if not rows and not include_all:
            current_row = self.sweep_combo_list.currentRow()
            if current_row >= 0:
                rows = [current_row]
        indices: list[int] = []
        for row in rows:
            data = self._sweep_combo_row_data(row)
            index = safe_int(data.get("index", -1), -1)
            if index >= 0 and index not in indices:
                indices.append(index)
        if not indices:
            raise ValueError("请先在组合表中选择至少一个组合。")
        return sorted(indices)

    def _update_sweep_preview(self) -> None:
        self._apply_sweep_tool_paths()
        try:
            grid = self._current_sweep_param_grid()
            index, combo, _total = self._selected_sweep_combo()
        except ValueError:
            return
        lines = [
            f";; {sweep_combo_label(index)}: {sweep_combo_summary(combo)}",
            ";; 创建 rpvar（幂等，可重复执行）",
            *sweep_define_commands(grid),
            "",
            ";; 应用当前组合并刷新 UDF 参数缓存",
            *sweep_set_commands(combo),
            sweep_reload_command(),
            "",
            ";; 可选：打印当前缓存值",
            sweep_print_command(),
        ]
        self.sweep_preview_text.setPlainText("\n".join(lines))

    def _read_sweep_buttons(self) -> list[dict[str, str]]:
        raw = self.settings.value("sweep_buttons", "")
        items: Any = []
        has_saved_value = False
        if isinstance(raw, str) and raw.strip():
            has_saved_value = True
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                has_saved_value = False
                items = []
        elif isinstance(raw, list):
            has_saved_value = True
            items = raw
        buttons = [normalize_sweep_button(item) for item in items if isinstance(item, dict)]
        return buttons if has_saved_value else default_sweep_buttons()

    def _save_sweep_buttons(self, buttons: list[dict[str, str]], refresh: bool = False) -> None:
        cleaned = [normalize_sweep_button(item) for item in buttons]
        self.sweep_buttons = cleaned
        self.settings.setValue("sweep_buttons", json.dumps(cleaned, ensure_ascii=False))
        if refresh:
            self._refresh_sweep_buttons()

    def _restore_sweep_buttons(self) -> None:
        self._save_sweep_buttons(self._read_sweep_buttons(), refresh=True)

    def _refresh_sweep_buttons(self) -> None:
        self._clear_grid_widgets(self.sweep_button_grid)
        self.sweep_run_buttons = []
        self.sweep_edit_buttons = []
        self.sweep_delete_buttons = []
        self.sweep_button_empty_label.setVisible(not self.sweep_buttons)
        action_labels = dict(SWEEP_BUTTON_ACTIONS)
        for index, button_data in enumerate(self.sweep_buttons):
            name = button_data["name"]
            action = button_data["action"]
            label = action_labels.get(action, action)
            tile, run_button, edit_button, delete_button = self._custom_button_tile(
                name,
                label,
                "sweepRunButton",
                label,
                lambda row=index: self._run_sweep_button(row),
                lambda row=index: self._edit_sweep_button(row),
                lambda row=index: self._delete_sweep_button(row),
            )
            self.sweep_run_buttons.append(run_button)
            self.sweep_edit_buttons.append(edit_button)
            self.sweep_delete_buttons.append(delete_button)
            self.sweep_button_grid.addWidget(tile, index // 2, index % 2)
            self.sweep_button_grid.setColumnStretch(index % 2, 1)
        self._update_enabled_state()

    def _sweep_button_dialog(self, button: dict[str, Any] | None = None) -> SweepButtonEditorDialog:
        return SweepButtonEditorDialog(self, button=button)

    def _add_sweep_button(self) -> None:
        dialog = self._sweep_button_dialog({"name": "新扫描模块", "action": "preview_selected_combo"})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.sweep_buttons.append(dialog.button_data())
        self._save_sweep_buttons(self.sweep_buttons, refresh=True)

    def _edit_sweep_button(self, index: int) -> None:
        if index < 0 or index >= len(self.sweep_buttons):
            return
        dialog = self._sweep_button_dialog(self.sweep_buttons[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.sweep_buttons[index] = dialog.button_data()
        self._save_sweep_buttons(self.sweep_buttons, refresh=True)

    def _delete_sweep_button(self, index: int) -> None:
        if index < 0 or index >= len(self.sweep_buttons):
            return
        name = self.sweep_buttons[index]["name"]
        reply = QMessageBox.question(
            self,
            "删除扫描模块",
            f"删除扫描模块按钮“{name}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self.sweep_buttons[index]
        self._save_sweep_buttons(self.sweep_buttons, refresh=True)

    def _reset_sweep_buttons(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认模块",
            "恢复默认扫描模块会覆盖当前模块按钮配置。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._save_sweep_buttons(default_sweep_buttons(), refresh=True)

    def _run_sweep_button(self, index: int) -> None:
        if index < 0 or index >= len(self.sweep_buttons):
            return
        self._apply_sweep_tool_paths()
        action = self.sweep_buttons[index]["action"]
        if action == "preview_selected_combo":
            self._refresh_sweep_combos(silent=True)
            self._update_sweep_preview()
            self.statusBar().showMessage("已刷新当前组合命令预览")
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再运行扫描模块。")
            return
        try:
            grid = self._current_sweep_param_grid()
        except ValueError as error:
            QMessageBox.warning(self, "参数网格无效", str(error))
            return
        if action == "define_rpvars":
            self._submit("参数扫描：创建 rpvar", self.controller.define_sweep_rpvars, grid)
            return
        if action == "reload_params":
            self._submit("参数扫描：刷新参数", self.controller.reload_sweep_params)
            return
        if action == "print_params":
            self._submit("参数扫描：打印参数", self.controller.print_sweep_params)
            return
        if action == "apply_selected_combo":
            try:
                self._refresh_sweep_combos(silent=True)
                combo_index, combo, total = self._selected_sweep_combo()
            except ValueError as error:
                QMessageBox.warning(self, "参数组合不可用", str(error))
                return
            self._submit(
                "参数扫描：应用当前组合",
                self.controller.apply_sweep_combo_from_grid,
                grid,
                combo,
                combo_index,
                total,
            )
            return
        if action == "run_selected_combo":
            self._run_sweep_selected_workflow()
            return
        if action == "run_all_combos":
            self._run_sweep_all_workflow()

    def _read_sweep_workflows(self) -> list[dict[str, Any]]:
        raw = self.settings.value("sweep_workflows", "")
        items: Any = []
        has_saved_value = False
        if isinstance(raw, str) and raw.strip():
            has_saved_value = True
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                has_saved_value = False
                items = []
        elif isinstance(raw, list):
            has_saved_value = True
            items = raw
        workflows = [normalize_workflow(item) for item in items if isinstance(item, dict)]
        workflows = [item for item in workflows if item["steps"]]
        if not has_saved_value:
            return default_sweep_workflows()
        existing = {workflow["name"] for workflow in workflows}
        for default in default_sweep_workflows():
            if default["name"].startswith("扫描") and default["name"] not in existing:
                workflows.append(default)
                existing.add(default["name"])
        return workflows

    def _save_sweep_workflows(self, workflows: list[dict[str, Any]], current_index: int = 0) -> None:
        cleaned = [normalize_workflow(item) for item in workflows]
        cleaned = [item for item in cleaned if item["steps"]]
        self.settings.setValue("sweep_workflows", json.dumps(cleaned, ensure_ascii=False))
        self.sweep_workflow_combo.blockSignals(True)
        self.sweep_workflow_combo.clear()
        for item in cleaned:
            self.sweep_workflow_combo.addItem(item["name"])
        if cleaned:
            self.sweep_workflow_combo.setCurrentIndex(max(0, min(current_index, len(cleaned) - 1)))
        self.sweep_workflow_combo.blockSignals(False)
        self._refresh_sweep_batch_workflow_combos(cleaned)
        self._refresh_sweep_workflow_buttons(cleaned)

    def _restore_sweep_workflows(self) -> None:
        self._save_sweep_workflows(self._read_sweep_workflows())

    def _refresh_sweep_batch_workflow_combos(self, workflows: list[dict[str, Any]] | None = None) -> None:
        workflows = workflows if workflows is not None else self._read_sweep_workflows()

        def populate(target: QComboBox, setting_key: str, default_name: str) -> None:
            current_data = target.currentData()
            current_name = str(target.currentText() or "")
            saved_name = str(self.settings.value(setting_key, "") or "")
            desired = current_name or saved_name or default_name
            if isinstance(current_data, int) and 0 <= current_data < len(workflows):
                desired = current_name or workflows[current_data]["name"]
            target.blockSignals(True)
            target.clear()
            target.addItem("不执行", -1)
            for index, workflow in enumerate(workflows):
                target.addItem(workflow["name"], index)
            selected = -1
            for index, workflow in enumerate(workflows):
                if workflow["name"] == desired:
                    selected = index
                    break
            use_none = desired == "不执行"
            if selected < 0 and not use_none and workflows:
                for index, workflow in enumerate(workflows):
                    if workflow["name"] == default_name:
                        selected = index
                        break
            if use_none:
                target.setCurrentIndex(0)
            elif selected >= 0:
                target.setCurrentIndex(selected + 1)
            else:
                target.setCurrentIndex(0)
            target.blockSignals(False)

        populate(self.sweep_init_workflow_combo, "sweep_init_workflow", "扫描初始化：标准初始化")
        populate(self.sweep_post_workflow_combo, "sweep_post_workflow", "扫描后处理：保存 Data + 导出 XY")

    def _add_sweep_workflow(self) -> None:
        dialog = self._workflow_dialog({"name": "新扫描工作流", "steps": [{"type": "iterate", "count": 100}]})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        workflows = self._read_sweep_workflows()
        workflows.append(dialog.workflow())
        self._save_sweep_workflows(workflows, len(workflows) - 1)

    def _edit_sweep_workflow(self) -> None:
        workflows = self._read_sweep_workflows()
        index = self.sweep_workflow_combo.currentIndex()
        if index < 0 or index >= len(workflows):
            return
        dialog = self._workflow_dialog(workflows[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        workflows[index] = dialog.workflow()
        self._save_sweep_workflows(workflows, index)

    def _delete_sweep_workflow(self) -> None:
        workflows = self._read_sweep_workflows()
        index = self.sweep_workflow_combo.currentIndex()
        if index < 0 or index >= len(workflows):
            return
        reply = QMessageBox.question(
            self,
            "删除扫描工作流",
            f"删除扫描工作流“{workflows[index]['name']}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del workflows[index]
        self._save_sweep_workflows(workflows, max(0, index - 1))

    def _refresh_sweep_workflow_buttons(self, workflows: list[dict[str, Any]] | None = None) -> None:
        workflows = workflows if workflows is not None else self._read_sweep_workflows()
        self._clear_grid_widgets(self.sweep_workflow_button_grid)
        self.sweep_workflow_buttons = []
        self.sweep_workflow_empty_label.setVisible(not workflows)
        for index, workflow in enumerate(workflows):
            button = QPushButton(workflow["name"])
            button.setMinimumHeight(38)
            button.setToolTip("\n".join(workflow_step_summary(step) for step in workflow["steps"]))
            button.clicked.connect(lambda _checked=False, row=index: self._run_sweep_workflow_button(row))
            self.sweep_workflow_buttons.append(button)
            self.sweep_workflow_button_grid.addWidget(button, index // 2, index % 2)
            self.sweep_workflow_button_grid.setColumnStretch(index % 2, 1)
        self._update_enabled_state()

    def _selected_sweep_workflow(self, index: int | None = None) -> tuple[int, dict[str, Any]]:
        workflows = self._read_sweep_workflows()
        row = self.sweep_workflow_combo.currentIndex() if index is None else index
        if row < 0 or row >= len(workflows):
            raise ValueError("请先创建或选择一个扫描工作流。")
        return row, workflows[row]

    def _workflow_from_batch_combo(self, combo: QComboBox, label: str) -> dict[str, Any]:
        data = combo.currentData()
        if data == -1:
            return {"name": f"不执行{label}", "steps": []}
        workflows = self._read_sweep_workflows()
        index = safe_int(data, -1)
        if index < 0 or index >= len(workflows):
            return {"name": f"不执行{label}", "steps": []}
        return workflows[index]

    def _selected_sweep_batch_workflows(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return (
            self._workflow_from_batch_combo(self.sweep_init_workflow_combo, "初始化流程"),
            self._workflow_from_batch_combo(self.sweep_post_workflow_combo, "后处理流程"),
        )

    def _set_batch_workflow_combo_index(self, combo: QComboBox, workflow_index: int) -> None:
        for row in range(combo.count()):
            if combo.itemData(row) == workflow_index:
                combo.setCurrentIndex(row)
                return

    def _run_sweep_workflow_button(self, index: int) -> None:
        self.sweep_workflow_combo.setCurrentIndex(index)
        self._set_batch_workflow_combo_index(self.sweep_post_workflow_combo, index)
        self._run_sweep_selected_workflow()

    def _sweep_launch_config(self) -> dict[str, Any]:
        scan_dir = combo_text(self.sweep_scan_dir_edit)
        base_case = combo_text(self.sweep_base_case_edit)
        work_dir = combo_text(self.work_dir_edit)
        if not work_dir:
            work_dir = scan_dir
        if not work_dir and base_case:
            work_dir = str(Path(base_case).expanduser().resolve().parent)
        if not work_dir:
            work_dir = str(DEFAULT_WORK_DIR if DEFAULT_WORK_DIR.exists() else TOOL_ROOT)
        if scan_dir and work_dir == scan_dir:
            Path(work_dir).expanduser().mkdir(parents=True, exist_ok=True)
        case_file = base_case or combo_text(self.case_file_edit)
        scm_file = self._selected_scm_path(prefer_launch=True)
        if self.load_scm_on_start_checkbox.isChecked() and not scm_file:
            raise ValueError("已勾选启动后加载 SCM，请先选择或输入 SCM 文件。")
        return {
            "work_dir": work_dir,
            "case_file": case_file,
            "dimension_text": self.dim_combo.currentText(),
            "processor_count": self.cores_spin.value(),
            "show_gui": self.gui_checkbox.isChecked(),
            "load_scm_on_start": self.load_scm_on_start_checkbox.isChecked(),
            "scm_file": scm_file,
        }

    def _begin_sweep_progress(self, total: int, message: str) -> None:
        self.sweep_active = True
        self.sweep_paused = False
        self.sweep_current_combo_index = None
        total = max(1, safe_int(total, 1, minimum=1))
        self.sweep_progress_bar.setRange(0, total)
        self.sweep_progress_bar.setValue(0)
        self.sweep_progress_bar.setFormat(f"0 / {total}")
        self.sweep_progress_label.setText(f"扫描进度：{message}")
        self._update_enabled_state()

    def _set_sweep_progress(self, done: int, total: int, message: str) -> None:
        total = max(1, safe_int(total, 1, minimum=1))
        value = max(0, min(safe_int(done, 0, minimum=0), total))
        self.sweep_progress_bar.setRange(0, total)
        self.sweep_progress_bar.setValue(value)
        self.sweep_progress_bar.setFormat(f"{value} / {total}")
        self.sweep_progress_label.setText(f"扫描进度：{message}")

    def _finish_sweep_progress(self, success: bool, message: str = "") -> None:
        if not self.sweep_active:
            return
        if success and self.sweep_progress_bar.maximum() > 0:
            self.sweep_progress_bar.setValue(self.sweep_progress_bar.maximum())
            self.sweep_progress_bar.setFormat(
                f"{self.sweep_progress_bar.maximum()} / {self.sweep_progress_bar.maximum()}"
            )
        elif message:
            self.sweep_progress_bar.setFormat(message)
        self.sweep_progress_label.setText(f"扫描进度：{message or ('完成' if success else '已停止')}")
        self.sweep_active = False
        self.sweep_paused = False
        self._update_enabled_state()

    def _request_sweep_calculation_interrupt(self, label: str) -> None:
        if not self.controller.has_session or not self.calculation_active:
            return
        self.calculation_stop_requested = True
        self.progress_bar.setFormat("正在停止...")
        try:
            future = self.interrupt_executor.submit(self.controller.stop_calculation)
        except Exception:
            self._queue_console_text(f"[{now_text()}] {label}：中断计算任务提交失败。\n{traceback.format_exc()}\n")
            self._set_status("中断计算任务提交失败")
            return
        future.add_done_callback(self._on_interrupt_done)
        self._queue_console_text(f"[{now_text()}] {label}：已请求中断当前 Fluent 计算。\n")

    def _pause_sweep(self) -> None:
        if not self.sweep_active:
            return
        self.sweep_paused = True
        self.controller.request_sweep_pause()
        self.sweep_progress_label.setText("扫描进度：已请求暂停")
        self._update_enabled_state()

    def _resume_sweep(self) -> None:
        if not self.sweep_active:
            return
        self.sweep_paused = False
        self.controller.request_sweep_resume()
        self.sweep_progress_label.setText("扫描进度：继续执行")
        self._update_enabled_state()

    def _retry_sweep_current(self) -> None:
        if self.sweep_active:
            self.sweep_paused = False
            self.controller.request_sweep_retry()
            self._request_sweep_calculation_interrupt("重试当前组合")
            self.sweep_progress_label.setText("扫描进度：正在请求重试当前组合")
            self._update_enabled_state()
            return
        try:
            combo_index, _combo, _total = self._selected_sweep_combo()
            self._check_only_sweep_combo(combo_index)
        except ValueError as error:
            QMessageBox.warning(self, "参数组合不可用", str(error))
            return
        self._run_sweep_selected_workflow()

    def _stop_sweep(self) -> None:
        if not self.sweep_active:
            return
        self.controller.request_sweep_stop()
        self._request_sweep_calculation_interrupt("停止参数扫描")
        self.sweep_progress_label.setText("扫描进度：正在停止")
        self._update_enabled_state()

    def _check_only_sweep_combo(self, combo_index: int) -> None:
        self.sweep_combo_list.blockSignals(True)
        for row in range(self.sweep_combo_list.rowCount()):
            item = self._sweep_combo_check_item(row)
            data = self._sweep_combo_row_data(row)
            checked = safe_int(data.get("index", -1), -1) == combo_index
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            if checked:
                self.sweep_combo_list.setCurrentCell(row, 0)
        self.sweep_combo_list.blockSignals(False)
        self._update_sweep_summary_label()

    def _run_sweep_selected_workflow(self) -> None:
        try:
            self._apply_sweep_tool_paths()
            grid = self._current_sweep_param_grid()
            self._refresh_sweep_combos(silent=True)
            combo_indices = self._selected_sweep_combo_indices()
            init_workflow, post_workflow = self._selected_sweep_batch_workflows()
            launch_config = self._sweep_launch_config()
        except ValueError as error:
            QMessageBox.warning(self, "扫描配置不可用", str(error))
            return
        self._save_settings()
        iteration_count = len(combo_indices) * (
            self.sweep_iterations_spin.value()
            + (self._workflow_iteration_count(init_workflow) or 0)
            + (self._workflow_iteration_count(post_workflow) or 0)
        )
        if iteration_count:
            self._begin_calculation_progress(iteration_count)
        self._begin_sweep_progress(len(combo_indices), f"准备执行 {len(combo_indices)} 个组合")
        submitted = self._submit(
            f"参数扫描：选中 {len(combo_indices)} 个组合",
            self.controller.run_sweep_batch,
            grid,
            combo_indices,
            init_workflow,
            post_workflow,
            combo_text(self.sweep_scan_dir_edit),
            combo_text(self.sweep_base_case_edit),
            self.sweep_iterations_spin.value(),
            launch_config,
            self.skip_completed_sweep_checkbox.isChecked(),
        )
        if not submitted:
            if self.calculation_active:
                self._finish_calculation_progress(False)
            self._finish_sweep_progress(False, "未启动")

    def _run_sweep_all_workflow(self) -> None:
        try:
            self._apply_sweep_tool_paths()
            grid = self._current_sweep_param_grid()
            self._refresh_sweep_combos(silent=True)
            combo_indices = self._selected_sweep_combo_indices(include_all=True)
            init_workflow, post_workflow = self._selected_sweep_batch_workflows()
            launch_config = self._sweep_launch_config()
        except ValueError as error:
            QMessageBox.warning(self, "扫描配置不可用", str(error))
            return
        if not combo_indices:
            QMessageBox.warning(self, "没有组合", "当前参数网格没有生成任何组合。")
            return
        self._save_settings()
        iteration_count = len(combo_indices) * (
            self.sweep_iterations_spin.value()
            + (self._workflow_iteration_count(init_workflow) or 0)
            + (self._workflow_iteration_count(post_workflow) or 0)
        )
        if iteration_count:
            self._begin_calculation_progress(iteration_count)
        self._begin_sweep_progress(len(combo_indices), f"准备执行全部 {len(combo_indices)} 个组合")
        submitted = self._submit(
            f"参数扫描：全部 {len(combo_indices)} 个组合",
            self.controller.run_sweep_batch,
            grid,
            combo_indices,
            init_workflow,
            post_workflow,
            combo_text(self.sweep_scan_dir_edit),
            combo_text(self.sweep_base_case_edit),
            self.sweep_iterations_spin.value(),
            launch_config,
            self.skip_completed_sweep_checkbox.isChecked(),
        )
        if not submitted:
            if self.calculation_active:
                self._finish_calculation_progress(False)
            self._finish_sweep_progress(False, "未启动")

    def _save_settings(self) -> None:
        if self.output_visible_checkbox.isChecked():
            self._remember_output_splitter_state(force=True)
        self._remember_combo("work_dir", self.work_dir_edit)
        self._remember_combo("case_file", self.case_file_edit)
        self._remember_combo("file_path", self.file_path_edit)
        self._remember_combo("udf_dir", self.udf_dir_edit)
        self._remember_combo("post_output_dir", self.post_output_dir_edit)
        self._remember_combo("init_zone_type", self.init_zone_type_edit)
        self._remember_combo("init_zone_name", self.init_zone_name_edit)
        self._remember_combo("init_phase", self.init_phase_edit)
        self._append_combo_items(self.init_zone_type_edit, COMMON_INIT_ZONE_TYPES)
        self._append_combo_items(self.init_phase_edit, COMMON_INIT_PHASES)
        self._remember_on_demand_function(combo_text(self.on_demand_function_edit))
        self._remember_scm_path(self._selected_scm_path(prefer_launch=True))
        self.settings.setValue("dimension", self.dim_combo.currentText())
        self.settings.setValue("cores", self.cores_spin.value())
        self.settings.setValue("show_gui", self.gui_checkbox.isChecked())
        self.settings.setValue("load_scm_on_start", self.load_scm_on_start_checkbox.isChecked())
        self.settings.setValue("command_mode", self._command_mode())
        self._remember_command_text()
        self._save_command_buttons(self.command_buttons)
        self.settings.setValue("sweep_param_grid_text", self.sweep_grid_editor.toPlainText())
        self._remember_combo("sweep_module_path", self.sweep_module_path_edit)
        self._remember_combo("sweep_config_path", self.sweep_config_path_edit)
        self._remember_combo("sweep_scan_dir", self.sweep_scan_dir_edit)
        self._remember_combo("sweep_base_case", self.sweep_base_case_edit)
        self.settings.setValue("sweep_iterations", self.sweep_iterations_spin.value())
        self.settings.setValue("sweep_skip_completed", self.skip_completed_sweep_checkbox.isChecked())
        self.settings.setValue("sweep_init_workflow", self.sweep_init_workflow_combo.currentText())
        self.settings.setValue("sweep_post_workflow", self.sweep_post_workflow_combo.currentText())
        self._save_sweep_buttons(self.sweep_buttons)
        self._save_sweep_workflows(self._read_sweep_workflows(), self.sweep_workflow_combo.currentIndex())
        remember_text_history(self.settings, "post_command", combo_plain_text(self.post_command_edit))
        self._save_plot_buttons(self.plot_buttons)
        self.settings.setValue("output_visible", self.output_visible_checkbox.isChecked())
        self.settings.setValue("output_below", self.output_below_checkbox.isChecked())
        self.settings.setValue("topmost", self.topmost_btn.isChecked())
        self.settings.setValue("quick_iterations", self.iterations_spin.value())
        self.settings.setValue("current_tab", self.action_tabs.currentIndex())
        self.settings.setValue("sweep_preview_visible", self.sweep_preview_toggle.isChecked())
        self.settings.setValue("sweep_advanced_visible", self.sweep_advanced_box.isChecked())

    def _selected_scm_path(self, prefer_launch: bool = False) -> str:
        if prefer_launch:
            return combo_text(self.launch_scm_file_edit) or combo_text(self.command_scm_file_edit)
        return combo_text(self.command_scm_file_edit) or combo_text(self.launch_scm_file_edit)

    def _set_scm_path(self, path: str | Path) -> None:
        value = str(path or "")
        set_combo_text(self.launch_scm_file_edit, value)
        set_combo_text(self.command_scm_file_edit, value)

    def _remember_scm_path(self, path: str = "") -> str:
        current = clean_entry(path)
        self.settings.setValue("scm_file", current)
        items = remember_history(self.settings, "scm_file", current)
        populate_combo(self.launch_scm_file_edit, items, current)
        populate_combo(self.command_scm_file_edit, items, current)
        return current

    def _default_post_dir(self) -> Path:
        if self.controller.work_dir is not None:
            return self.controller.work_dir / "post"
        work_text = combo_text(self.work_dir_edit)
        if work_text:
            return Path(work_text).expanduser() / "post"
        return TOOL_ROOT / "post"

    def _selected_post_dir(self) -> Path:
        text = combo_text(self.post_output_dir_edit)
        return Path(text).expanduser().resolve() if text else self._default_post_dir().resolve()

    def _browse_post_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择后处理输出目录",
            dialog_start_path(combo_text(self.post_output_dir_edit), self._default_post_dir()),
        )
        if directory:
            set_combo_text(self.post_output_dir_edit, directory)
            self._remember_combo("post_output_dir", self.post_output_dir_edit)
            self._refresh_post_results()

    def _post_image_files(self, directory: Path) -> list[Path]:
        if not directory.exists() or not directory.is_dir():
            return []
        suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        candidates: list[tuple[float, Path]] = []
        try:
            children = list(directory.iterdir())
        except OSError:
            return []
        for path in children:
            try:
                if path.is_file() and path.suffix.lower() in suffixes:
                    candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        return [path for _mtime, path in sorted(candidates, key=lambda item: item[0], reverse=True)]

    def _append_post_result(self, text: str) -> None:
        self.post_result_text.append(f"[{now_text()}] {text}")

    def _refresh_post_results(self, update_window: bool = True) -> None:
        try:
            directory = self._selected_post_dir()
        except Exception as error:
            self.post_image_paths = []
            self.current_post_image_path = None
            self.post_summary_label.setText("目录不可用")
            self._append_post_result(f"后处理目录不可用：{type(error).__name__}: {error}")
            return
        if not combo_text(self.post_output_dir_edit):
            set_combo_text(self.post_output_dir_edit, str(directory))
        self.post_refresh_token += 1
        token = self.post_refresh_token
        self.post_refresh_active = True
        self.refresh_post_btn.setText("扫描中...")
        self.post_summary_label.setText(f"正在扫描：{directory}")
        self._update_enabled_state()
        try:
            future = self.io_executor.submit(self._post_image_files, directory)
        except Exception:
            self.post_refresh_active = False
            self.refresh_post_btn.setText("刷新结果")
            self._update_enabled_state()
            self._queue_console_text(f"[{now_text()}] 后处理目录扫描任务提交失败：\n{traceback.format_exc()}\n")
            self._set_status("后处理目录扫描提交失败")
            return

        future.add_done_callback(
            lambda fut, scan_token=token, scan_dir=directory, should_update=update_window: (
                self._on_post_results_scan_done(scan_token, scan_dir, should_update, fut)
            )
        )

    def _on_post_results_scan_done(
        self, token: int, directory: Path, update_window: bool, future: Future
    ) -> None:
        error = ""
        image_paths: list[str] = []
        try:
            image_paths = [str(path) for path in future.result()]
        except Exception:
            error = traceback.format_exc()
        with contextlib.suppress(RuntimeError):
            self.window_signals.post_results_scanned.emit(
                token,
                str(directory),
                image_paths,
                error,
                update_window,
            )

    def _post_results_scanned(
        self, token: int, directory_text: str, image_paths: list[str], error: str, update_window: bool
    ) -> None:
        if token != self.post_refresh_token:
            return
        self.post_refresh_active = False
        self.refresh_post_btn.setText("刷新结果")
        directory = Path(directory_text)
        if error:
            self.post_image_paths = []
            self.current_post_image_path = None
            self.post_summary_label.setText(f"扫描失败：{directory}")
            self._append_post_result(f"扫描失败：{directory}")
            self._queue_console_text(f"[{now_text()}] 后处理目录扫描失败：\n{error}\n")
            self._set_status("后处理目录扫描失败")
            self._update_enabled_state()
            return
        previous_path = str(self.current_post_image_path or "")
        self.post_image_paths = [Path(path) for path in image_paths]
        self.post_summary_label.setText(f"目录：{directory}    图片 {len(self.post_image_paths)} 张")
        if self.post_image_paths:
            if not previous_path or previous_path not in {str(path) for path in self.post_image_paths}:
                self.current_post_image_path = self.post_image_paths[0]
        else:
            self.current_post_image_path = None
        if update_window and self.post_results_window is not None:
            self.post_results_window.refresh_from_paths(self.post_image_paths)
        self._append_post_result(f"已扫描：{directory}，图片 {len(self.post_image_paths)} 张")
        self._update_enabled_state()

    def _selected_post_image_path(self) -> Path | None:
        return self.current_post_image_path

    def _open_post_results_window(self) -> None:
        self._refresh_post_results(update_window=True)
        if self.post_results_window is None:
            window = PostResultsWindow(self)
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.destroyed.connect(lambda _obj=None: self._clear_post_results_window())
            self.post_results_window = window
        self.post_results_window.refresh_from_paths(self.post_image_paths)
        self.post_results_window.show()
        self.post_results_window.raise_()
        self.post_results_window.activateWindow()

    def _clear_post_results_window(self) -> None:
        self.post_results_window = None

    def _open_post_image_window(self, image_path: str) -> None:
        path = Path(image_path)
        window = PostImageWindow(self, path)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.post_windows.append(window)
        window.destroyed.connect(lambda _obj=None, target=window: self._remove_post_window(target))
        window.show()
        window.raise_()
        window.activateWindow()
        self._append_post_result(f"弹出图形窗口：{path}")

    def _remove_post_window(self, window: PostImageWindow) -> None:
        with contextlib.suppress(ValueError):
            self.post_windows.remove(window)

    def _post_picture_path(self) -> Path:
        directory = self._selected_post_dir()
        name = clean_entry(self.post_picture_name_edit.text())
        if not name:
            name = f"fluent_post_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = Path(name)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            path = path.with_suffix(".png")
        if not path.is_absolute():
            path = directory / path
        return path.resolve()

    def _read_plot_buttons(self) -> list[dict[str, str]]:
        raw = self.settings.value("post_plot_buttons", "")
        items: Any = []
        has_saved_value = False
        if isinstance(raw, str) and raw.strip():
            has_saved_value = True
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                has_saved_value = False
                items = []
        elif isinstance(raw, list):
            has_saved_value = True
            items = raw
        buttons = [normalize_plot_button(item) for item in items if isinstance(item, dict)]
        buttons = [item for item in buttons if item["code"]]
        return buttons if has_saved_value else default_plot_buttons()

    def _save_plot_buttons(self, buttons: list[dict[str, str]], refresh: bool = False) -> None:
        cleaned = [normalize_plot_button(item) for item in buttons]
        cleaned = [item for item in cleaned if item["code"]]
        self.plot_buttons = cleaned
        self.settings.setValue("post_plot_buttons", json.dumps(cleaned, ensure_ascii=False))
        if refresh:
            self._refresh_plot_buttons()

    def _restore_plot_buttons(self) -> None:
        self._save_plot_buttons(self._read_plot_buttons(), refresh=True)

    def _refresh_plot_buttons(self) -> None:
        self._clear_grid_widgets(self.plot_button_grid)
        self.plot_run_buttons = []
        self.plot_edit_buttons = []
        self.plot_delete_buttons = []
        self.plot_button_empty_label.setVisible(not self.plot_buttons)

        for index, button_data in enumerate(self.plot_buttons):
            name = button_data["name"]
            tile, run_button, edit_button, delete_button = self._custom_button_tile(
                name,
                button_data["code"][:1200],
                "plotRunButton",
                "",
                lambda row=index: self._run_plot_button(row),
                lambda row=index: self._edit_plot_button(row),
                lambda row=index: self._delete_plot_button(row),
            )

            self.plot_run_buttons.append(run_button)
            self.plot_edit_buttons.append(edit_button)
            self.plot_delete_buttons.append(delete_button)

            self.plot_button_grid.addWidget(tile, index, 0)
        self.plot_button_grid.setColumnStretch(0, 1)
        self._update_enabled_state()

    def _plot_button_dialog(self, button: dict[str, Any] | None = None) -> PlotButtonEditorDialog:
        return PlotButtonEditorDialog(self, button=button, templates=default_plot_buttons())

    def _add_plot_button(self) -> None:
        dialog = self._plot_button_dialog({"name": "新绘图", "code": DEFAULT_PLOT_BUTTONS[1]["code"]})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.plot_buttons.append(dialog.button_data())
        self._save_plot_buttons(self.plot_buttons, refresh=True)

    def _edit_plot_button(self, index: int) -> None:
        if index < 0 or index >= len(self.plot_buttons):
            return
        dialog = self._plot_button_dialog(self.plot_buttons[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.plot_buttons[index] = dialog.button_data()
        self._save_plot_buttons(self.plot_buttons, refresh=True)

    def _delete_plot_button(self, index: int) -> None:
        if index < 0 or index >= len(self.plot_buttons):
            return
        name = self.plot_buttons[index]["name"]
        reply = QMessageBox.question(
            self,
            "删除绘图按钮",
            f"删除绘图按钮“{name}”吗？这会从本工具设置中移除它绑定的 Python 代码。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self.plot_buttons[index]
        self._save_plot_buttons(self.plot_buttons, refresh=True)

    def _reset_plot_buttons(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认模板",
            "恢复默认模板会覆盖当前绘图按钮配置。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._save_plot_buttons(default_plot_buttons(), refresh=True)

    def _prepare_post_python_scope(self) -> None:
        directory = self._selected_post_dir()
        directory.mkdir(parents=True, exist_ok=True)
        set_combo_text(self.post_output_dir_edit, str(directory))
        self._remember_combo("post_output_dir", self.post_output_dir_edit)

        def editor_post_path(name: str = "post.png") -> Path:
            path = Path(clean_entry(name) or "post.png")
            if not path.is_absolute():
                path = directory / path
            return unique_file_path(path.resolve())

        def editor_save_picture(path: str | Path) -> Path:
            target = Path(path)
            return self.controller.save_picture(str(target))

        def editor_refresh_post() -> None:
            self.pending_post_refresh = True

        def editor_show_image(path: str | Path) -> Path:
            target = Path(path).expanduser()
            if not target.is_absolute():
                target = directory / target
            self.window_signals.post_image_ready.emit(str(target.resolve()))
            return target.resolve()

        self.controller._python_scope.update(
            {
                "post_dir": directory,
                "post_path": editor_post_path,
                "save_picture": editor_save_picture,
                "show_image": editor_show_image,
                "open_image": editor_show_image,
                "refresh_post": editor_refresh_post,
            }
        )

    def _run_plot_button(self, index: int) -> None:
        if index < 0 or index >= len(self.plot_buttons):
            return
        button = self.plot_buttons[index]
        code = button["code"].strip()
        if not code:
            QMessageBox.information(self, "没有脚本", "请先编辑这个绘图按钮的 Python 代码。")
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再运行绘图按钮。")
            return
        self._prepare_post_python_scope()
        self.pending_post_refresh = True
        self._append_post_result(f"运行绘图按钮：{button['name']}")
        self._submit(f"运行绘图按钮：{button['name']}", self.controller.execute_python, code)

    def _browse_sweep_tool_file(self, target_combo: QComboBox, title: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            dialog_start_path(
                combo_text(target_combo),
                combo_text(self.sweep_config_path_edit),
                combo_text(self.sweep_module_path_edit),
                SWEEP_TOOLS_DIR,
            ),
            "Python Files (*.py);;All Files (*)",
        )
        if path:
            set_combo_text(target_combo, path)
            key = "sweep_module_path" if target_combo is self.sweep_module_path_edit else "sweep_config_path"
            self._remember_combo(key, target_combo)
            self._apply_sweep_tool_paths()

    def _browse_sweep_scan_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择扫描工作目录",
            dialog_start_path(combo_text(self.sweep_scan_dir_edit), self._default_sweep_scan_dir()),
        )
        if directory:
            set_combo_text(self.sweep_scan_dir_edit, directory)
            self._remember_combo("sweep_scan_dir", self.sweep_scan_dir_edit)

    def _browse_sweep_base_case(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择扫描基准 Case",
            dialog_start_path(combo_text(self.sweep_base_case_edit), combo_text(self.case_file_edit), combo_text(self.work_dir_edit)),
            "Fluent Case (*.cas *.cas.h5 *.cas.gz *.cas.h5.gz);;All Files (*)",
        )
        if path:
            set_combo_text(self.sweep_base_case_edit, path)
            self._remember_combo("sweep_base_case", self.sweep_base_case_edit)

    def _browse_work_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择工作目录",
            dialog_start_path(combo_text(self.work_dir_edit), combo_text(self.file_path_edit)),
        )
        if directory:
            set_combo_text(self.work_dir_edit, directory)
            self._remember_combo("work_dir", self.work_dir_edit)

    def _browse_case_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Case 文件",
            dialog_start_path(combo_text(self.case_file_edit), combo_text(self.work_dir_edit)),
            "Fluent Case (*.cas *.cas.h5 *.cas.gz *.cas.h5.gz);;All Files (*)",
        )
        if path:
            set_combo_text(self.case_file_edit, path)
            set_combo_text(self.file_path_edit, path)
            self._remember_combo("case_file", self.case_file_edit)
            self._remember_combo("file_path", self.file_path_edit)

    def _browse_scm_file(self, target_combo: QComboBox) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 SCM 文件",
            dialog_start_path(
                combo_text(target_combo),
                self._selected_scm_path(prefer_launch=target_combo is self.launch_scm_file_edit),
                combo_text(self.work_dir_edit),
            ),
            "Fluent Scheme (*.scm);;All Files (*)",
        )
        if path:
            self._set_scm_path(path)
            self._remember_scm_path(path)

    def _browse_file_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Case/Data 文件",
            dialog_start_path(combo_text(self.file_path_edit), combo_text(self.case_file_edit), combo_text(self.work_dir_edit)),
            "Fluent Case/Data (*.cas *.cas.h5 *.cas.gz *.cas.h5.gz *.dat *.dat.h5 *.dat.gz *.dat.h5.gz);;All Files (*)",
        )
        if path:
            set_combo_text(self.file_path_edit, path)
            self._remember_combo("file_path", self.file_path_edit)

    def _browse_file_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择保存路径",
            dialog_start_path(combo_text(self.file_path_edit), combo_text(self.work_dir_edit), fallback_name="case-data.cas.h5"),
            "Fluent Case/Data (*.cas *.cas.h5 *.dat *.dat.h5);;All Files (*)",
        )
        if path:
            set_combo_text(self.file_path_edit, path)
            self._remember_combo("file_path", self.file_path_edit)

    def _browse_udf_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择 UDF 文件夹",
            dialog_start_path(combo_text(self.udf_dir_edit), combo_text(self.work_dir_edit)),
        )
        if directory:
            set_combo_text(self.udf_dir_edit, directory)
            self._remember_combo("udf_dir", self.udf_dir_edit)

    def _open_path_location(self, combo: QComboBox, label: str) -> None:
        text = combo_text(combo)
        if not text:
            QMessageBox.information(self, "没有路径", f"请先选择或输入{label}。")
            return

        path = Path(text).expanduser()
        folder: Path | None = None
        if path.exists():
            folder = path if path.is_dir() else path.parent
        else:
            for parent in (path.parent, *path.parents):
                if parent.exists() and parent.is_dir():
                    folder = parent
                    break

        if folder is None:
            QMessageBox.warning(self, "路径不可用", f"找不到可打开的文件夹：{path}")
            return
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception as error:
            QMessageBox.warning(self, "打开失败", f"{type(error).__name__}: {error}")

    def _use_case_path_for_file(self) -> None:
        path = combo_text(self.case_file_edit)
        if not path:
            QMessageBox.information(self, "没有 Case", "启动页 Case 路径为空。")
            return
        set_combo_text(self.file_path_edit, path)
        self._remember_combo("file_path", self.file_path_edit)

    def _use_work_dir_for_file(self) -> None:
        work_dir = combo_text(self.work_dir_edit)
        if not work_dir:
            QMessageBox.information(self, "没有工作目录", "启动页工作目录为空。")
            return
        path = Path(work_dir).expanduser() / "case-data.cas.h5"
        set_combo_text(self.file_path_edit, path)
        self._remember_combo("file_path", self.file_path_edit)

    def _start_fluent(self) -> None:
        self._save_settings()
        scm_file = self._selected_scm_path(prefer_launch=True)
        if self.load_scm_on_start_checkbox.isChecked() and not scm_file:
            QMessageBox.warning(self, "缺少 SCM", "已勾选启动后加载 SCM，请先选择或输入 SCM 文件。")
            return
        try:
            work_path = require_path(combo_text(self.work_dir_edit), "工作目录")
            if not work_path.exists() or not work_path.is_dir():
                raise FileNotFoundError(f"工作目录不存在：{work_path}")
            case_text = combo_text(self.case_file_edit)
            if case_text:
                case_path = require_path(case_text, "Case 文件")
                if not case_path.exists() or not case_path.is_file():
                    raise FileNotFoundError(f"Case 文件不存在：{case_path}")
            if self.load_scm_on_start_checkbox.isChecked():
                scm_path = require_path(scm_file, "SCM 文件")
                if not scm_path.exists() or not scm_path.is_file():
                    raise FileNotFoundError(f"SCM 文件不存在：{scm_path}")
        except Exception as error:
            QMessageBox.warning(self, "启动配置不可用", f"{type(error).__name__}: {error}")
            return
        if scm_file:
            self._set_scm_path(scm_file)
            self._remember_scm_path(scm_file)
        self._submit(
            "启动 Fluent",
            self.controller.launch,
            combo_text(self.work_dir_edit),
            combo_text(self.case_file_edit),
            self.dim_combo.currentText(),
            self.cores_spin.value(),
            self.gui_checkbox.isChecked(),
            self.load_scm_on_start_checkbox.isChecked(),
            scm_file,
        )

    def _stop_fluent(self) -> None:
        if not self.controller.has_session:
            QMessageBox.information(self, "Fluent 未启动", "当前没有需要停止的 Fluent 实例。")
            return
        self._submit("停止 Fluent", self.controller.shutdown)

    def _stop_calculation(self) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再停止计算。")
            return
        self._set_status("正在请求停止计算")
        self.calculation_stop_requested = True
        self.progress_bar.setFormat("正在停止...")
        try:
            future = self.interrupt_executor.submit(self.controller.stop_calculation)
        except Exception:
            self.calculation_stop_requested = False
            self._queue_console_text(f"[{now_text()}] 停止计算任务提交失败：\n{traceback.format_exc()}\n")
            self._set_status("停止计算任务提交失败")
            self._update_enabled_state()
            return
        future.add_done_callback(self._on_interrupt_done)

    def _on_interrupt_done(self, future: Future) -> None:
        error = ""
        try:
            future.result()
        except Exception:
            error = traceback.format_exc()
        with contextlib.suppress(RuntimeError):
            self.window_signals.interrupt_finished.emit(error)

    def _interrupt_finished(self, error: str) -> None:
        if error:
            self.calculation_stop_requested = False
            self._queue_console_text(f"[{now_text()}] 停止计算请求失败：\n{error}\n")
            self._set_status("停止计算请求失败")
            self._update_enabled_state()
            return
        self._queue_console_text(f"[{now_text()}] 已发送停止计算请求。\n")
        self._set_status("已请求停止计算")
        self._update_enabled_state()

    def _run_post_command(self) -> None:
        command = combo_plain_text(self.post_command_edit)
        if not command:
            QMessageBox.information(self, "没有命令", "请先输入后处理 TUI 命令。")
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再运行后处理命令。")
            return
        remember_text_history(self.settings, "post_command", command)
        populate_combo(self.post_command_edit, read_text_history(self.settings, "post_command"), "")
        self._append_post_result(f"运行后处理命令：{command}")
        if "save-picture" in command.lower():
            self.pending_post_refresh = True
        self._submit("运行后处理命令", self.controller.execute_tui, command)

    def _save_post_picture(self) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再保存后处理图片。")
            return
        try:
            directory = self._selected_post_dir()
            directory.mkdir(parents=True, exist_ok=True)
            set_combo_text(self.post_output_dir_edit, str(directory))
            self._remember_combo("post_output_dir", self.post_output_dir_edit)
            path = self._post_picture_path()
        except Exception as error:
            QMessageBox.warning(self, "保存路径不可用", f"{type(error).__name__}: {error}")
            return
        self.pending_post_refresh = True
        self._append_post_result(f"保存当前图形窗口：{path}")
        self._submit("保存后处理图片", self.controller.save_picture, str(path))

    def _post_object_kind(self) -> str:
        return str(self.post_object_type_combo.currentData() or "xy_plot")

    def _post_object_ref(self) -> str:
        text = combo_text(self.post_object_ref_combo)
        if self.post_object_ref_combo.currentIndex() >= 0 and text == self.post_object_ref_combo.currentText():
            data = self.post_object_ref_combo.currentData()
            if data and text == self.post_object_ref_combo.itemText(self.post_object_ref_combo.currentIndex()):
                return clean_entry(str(data))
        match = re.match(r"^\s*\d+\s*:\s*(.+)$", text)
        return clean_entry(match.group(1) if match else text)

    def _post_object_target_path(self, action: str) -> Path:
        directory = self._selected_post_dir()
        directory.mkdir(parents=True, exist_ok=True)
        set_combo_text(self.post_output_dir_edit, str(directory))
        self._remember_combo("post_output_dir", self.post_output_dir_edit)
        target_text = clean_entry(self.post_object_target_edit.text())
        ref_text = self._post_object_ref() or self._post_object_kind()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ref_text).strip("._") or self._post_object_kind()
        if not target_text:
            suffix = ".png" if action == "save_image" else post_object_data_suffix(self._post_object_kind())
            target_text = f"{safe_name}{suffix}"
        path = Path(target_text)
        if action == "save_image" and path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            path = path.with_suffix(".png")
        if action == "write_data" and not path.suffix:
            path = path.with_suffix(post_object_data_suffix(self._post_object_kind()))
        if not path.is_absolute():
            path = directory / path
        return path.resolve()

    def _post_object_type_changed(self) -> None:
        self.post_object_ref_combo.clear()
        self.post_object_target_edit.clear()
        self._update_enabled_state()

    def _refresh_post_object_names(self) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再刷新后处理对象。")
            return
        if self.busy:
            self._queue_console_text(f"[{now_text()}] 当前正在执行任务，稍后再刷新后处理对象。\n")
            return
        kind = self._post_object_kind()
        self.post_object_refresh_token += 1
        token = self.post_object_refresh_token
        self.post_object_refresh_active = True
        self.refresh_post_objects_btn.setText("刷新中...")
        self._set_status("正在刷新后处理对象")
        self.app_signals.busy_changed.emit(True)
        try:
            future = self.executor.submit(self.controller.list_post_objects, kind)
        except Exception:
            error = traceback.format_exc()
            self.post_object_refresh_active = False
            self.refresh_post_objects_btn.setText("刷新列表")
            self._queue_console_text(f"[{now_text()}] 刷新后处理对象提交失败：\n{error}\n")
            self._set_status("刷新后处理对象提交失败")
            self.app_signals.busy_changed.emit(False)
            QMessageBox.warning(self, "刷新失败", "刷新任务无法启动，请查看输出日志。")
            return

        future.add_done_callback(
            lambda fut, refresh_token=token, object_kind=kind: (
                self._on_post_objects_loaded(refresh_token, object_kind, fut)
            )
        )

    def _on_post_objects_loaded(self, token: int, kind: str, future: Future) -> None:
        error = ""
        items: list[str] = []
        try:
            items = [str(item) for item in (future.result() or [])]
        except Exception:
            error = traceback.format_exc()
        with contextlib.suppress(RuntimeError):
            self.window_signals.post_objects_loaded.emit(token, kind, items, error)

    def _post_objects_loaded(self, token: int, kind: str, items: list[str], error: str) -> None:
        if token != self.post_object_refresh_token:
            return
        self.post_object_refresh_active = False
        self.refresh_post_objects_btn.setText("刷新列表")
        self.app_signals.busy_changed.emit(False)
        if error:
            self._queue_console_text(f"[{now_text()}] 刷新后处理对象失败：\n{error}\n")
            self._set_status("刷新后处理对象失败")
            QMessageBox.warning(self, "刷新失败", "无法读取后处理对象列表，请查看输出日志。")
            return
        current = self._post_object_ref()
        self.post_object_ref_combo.blockSignals(True)
        self.post_object_ref_combo.clear()
        for index, name in enumerate(items):
            self.post_object_ref_combo.addItem(f"{index}: {name}", name)
        if current:
            self.post_object_ref_combo.setCurrentText(current)
        self.post_object_ref_combo.blockSignals(False)
        self._append_post_result(f"已读取 {post_object_type_label(kind)} 对象 {len(items)} 个")
        self._set_status("后处理对象已刷新")
        self._update_enabled_state()

    def _run_post_object_action(self, action: str) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再操作后处理对象。")
            return
        kind = self._post_object_kind()
        ref = self._post_object_ref()
        if not ref:
            QMessageBox.warning(self, "缺少对象", "请先输入或选择 Fluent 中已有的对象名称/编号。")
            return
        target = ""
        if action in {"save_image", "write_data"}:
            try:
                target = str(self._post_object_target_path(action))
            except Exception as error:
                QMessageBox.warning(self, "输出路径不可用", f"{type(error).__name__}: {error}")
                return
        if action == "save_image":
            self.pending_post_refresh = True
        if action == "write_data":
            self._append_post_result(f"导出后处理数据：{post_object_type_label(kind)} / {ref} -> {target}")
        elif action == "save_image":
            self._append_post_result(f"保存后处理对象图片：{post_object_type_label(kind)} / {ref} -> {target}")
        else:
            self._append_post_result(f"显示后处理对象：{post_object_type_label(kind)} / {ref}")
        label = {"display": "显示后处理对象", "save_image": "保存后处理对象图片", "write_data": "导出后处理对象数据"}[action]
        self._submit(label, self.controller.run_post_object_action, kind, ref, action, target)

    def _selected_file_path(self, fallback_combo: QComboBox | None = None) -> str:
        path = combo_text(self.file_path_edit)
        if not path and fallback_combo is not None:
            path = combo_text(fallback_combo)
            if path:
                set_combo_text(self.file_path_edit, path)
        return path

    def _submit_file_action(self, label: str, func: Callable[[str], None], path: str) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", f"请先启动 Fluent，再{label}。")
            return
        if not clean_entry(path):
            QMessageBox.warning(self, "缺少路径", "请先选择或输入文件路径。")
            return
        self._remember_combo("file_path", self.file_path_edit)
        self._submit(label, func, path)

    def _read_case(self) -> None:
        path = self._selected_file_path(self.case_file_edit)
        if path:
            set_combo_text(self.case_file_edit, path)
            self._remember_combo("case_file", self.case_file_edit)
        self._submit_file_action("读取 Case", self.controller.read_case, path)

    def _read_data(self) -> None:
        self._submit_file_action("读取 Data", self.controller.read_data, self._selected_file_path())

    def _write_case(self) -> None:
        if not combo_text(self.file_path_edit):
            self._browse_file_save()
        self._submit_file_action("保存 Case", self.controller.write_case, combo_text(self.file_path_edit))

    def _write_data(self) -> None:
        if not combo_text(self.file_path_edit):
            self._browse_file_save()
        self._submit_file_action("保存 Data", self.controller.write_data, combo_text(self.file_path_edit))

    def _write_case_data(self) -> None:
        if not combo_text(self.file_path_edit):
            self._browse_file_save()
        self._submit_file_action("保存 Case+Data", self.controller.write_case_data, combo_text(self.file_path_edit))

    def _build_udf(self) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再编译并加载 UDF。")
            return
        source_text = combo_text(self.udf_dir_edit)
        if not source_text:
            QMessageBox.warning(self, "缺少 UDF 文件夹", "请先选择包含 .c/.h/.hpp 的 UDF 源码文件夹。")
            return
        try:
            source_path = require_path(source_text, "UDF 文件夹")
            if not source_path.exists() or not source_path.is_dir():
                raise FileNotFoundError(f"UDF 文件夹不存在：{source_path}")
        except Exception as error:
            QMessageBox.warning(self, "UDF 文件夹不可用", f"{type(error).__name__}: {error}")
            return
        self._remember_combo("udf_dir", self.udf_dir_edit)
        self._submit("编译并加载 UDF", self.controller.build_and_load_udf, source_text)

    def _execute_on_demand(self) -> None:
        function_name = combo_text(self.on_demand_function_edit)
        if not function_name:
            QMessageBox.warning(self, "缺少函数名", "请先输入 Execute On Demand 函数名。")
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再执行 On Demand。")
            return
        self._remember_on_demand_function(function_name)
        self._submit("Execute On Demand", self.controller.execute_on_demand, function_name)

    def _load_scm(self) -> None:
        path = self._selected_scm_path()
        if not path:
            QMessageBox.warning(self, "缺少 SCM", "请先选择或输入 SCM 文件路径。")
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再加载 SCM。")
            return
        self._set_scm_path(path)
        self._remember_scm_path(path)
        self._submit("加载 SCM", self.controller.load_scm, path)

    def _run_quick_command(self, label: str, command: str) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再执行快捷命令。")
            return
        self._submit(label, self.controller.execute_tui, command)

    def _initialize(self) -> None:
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再初始化。")
            return
        zone_type = self._remember_combo("init_zone_type", self.init_zone_type_edit)
        zone_name = self._remember_combo("init_zone_name", self.init_zone_name_edit)
        phase = self._remember_combo("init_phase", self.init_phase_edit)
        self._append_combo_items(self.init_zone_type_edit, COMMON_INIT_ZONE_TYPES)
        self._append_combo_items(self.init_phase_edit, COMMON_INIT_PHASES)
        self._submit("初始化", self.controller.standard_initialize, zone_type, zone_name, phase)

    def _begin_calculation_progress(self, iterations: int) -> None:
        expected = safe_int(iterations, 1, minimum=1)
        self.calculation_active = True
        self.calculation_expected = expected
        self.calculation_completed_offset = 0
        self.calculation_first_iteration = None
        self.calculation_last_iteration = None
        self.calculation_stop_requested = False
        self.progress_parse_tail = ""
        self.progress_bar.setRange(0, expected)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 / {expected}")

    def _set_calculation_progress(self, done: int) -> None:
        if not self.calculation_active or self.calculation_expected <= 0:
            return
        value = max(0, min(done, self.calculation_expected))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{value} / {self.calculation_expected}")

    def _finish_calculation_progress(self, success: bool) -> None:
        if not self.calculation_active:
            return
        if success and not self.calculation_stop_requested:
            self._set_calculation_progress(self.calculation_expected)
            self.progress_bar.setFormat(f"{self.calculation_expected} / {self.calculation_expected}")
        else:
            current = self.progress_bar.value()
            self.progress_bar.setFormat(f"中断于 {current} / {self.calculation_expected}")
        self.calculation_active = False
        self.calculation_stop_requested = False

    def _iteration_count_from_command(self, command: str, mode: str) -> int | None:
        pattern = PYTHON_ITERATE_RE if mode == "python" else TUI_ITERATE_RE
        match = pattern.search(command)
        if not match:
            return None
        return safe_int(match.group(1), 0, minimum=1)

    def _workflow_iteration_count(self, workflow: dict[str, Any]) -> int | None:
        total = 0
        for step in workflow.get("steps", []):
            step_type = str(step.get("type", "tui"))
            if step_type == "iterate":
                total += safe_int(step.get("count", 1), 1, minimum=1)
            elif step_type == "tui":
                total += self._iteration_count_from_command(str(step.get("command", "")), "tui") or 0
            elif step_type == "python":
                total += self._iteration_count_from_command(str(step.get("code", "")), "python") or 0
        return total or None

    def _iterate(self) -> None:
        self.settings.setValue("quick_iterations", self.iterations_spin.value())
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再开始计算。")
            return
        self._begin_calculation_progress(self.iterations_spin.value())
        self._submit("开始计算", self.controller.start_calculation, self.iterations_spin.value())

    def _workflow_dialog(self, workflow: dict[str, Any] | None = None) -> WorkflowEditorDialog:
        def setting_text_items(key: str) -> list[str]:
            raw = self.settings.value(key, [])
            if isinstance(raw, (list, tuple)):
                return [clean_text(str(item)) for item in raw if clean_text(str(item))]
            if raw:
                return [clean_text(item) for item in str(raw).splitlines() if clean_text(item)]
            return []

        def add_unique(target: list[str], seen: set[str], values: list[str]) -> None:
            for item in values:
                text = clean_text(item)
                marker = text.lower()
                if text and marker not in seen:
                    target.append(text)
                    seen.add(marker)

        command_items: list[str] = []
        command_seen: set[str] = set()
        add_unique(command_items, command_seen, list(DEFAULT_COMMAND_PRESETS))
        add_unique(command_items, command_seen, setting_text_items("command_presets"))
        add_unique(command_items, command_seen, read_text_history(self.settings, "command"))

        python_items: list[str] = []
        python_seen: set[str] = set()
        add_unique(python_items, python_seen, list(DEFAULT_PYFLUENT_PRESETS))
        add_unique(python_items, python_seen, setting_text_items("python_command_presets"))
        add_unique(python_items, python_seen, read_text_history(self.settings, "python_command"))
        on_demand_items = read_history(self.settings, "on_demand_function")
        for item in DEFAULT_ON_DEMAND_FUNCTIONS:
            if item.lower() not in {existing.lower() for existing in on_demand_items}:
                on_demand_items.append(item)
        scm_items = read_history(self.settings, "scm_file")
        related_workflows = self._read_workflows()
        with contextlib.suppress(Exception):
            related_workflows.extend(self._read_sweep_workflows())
        if workflow is not None:
            related_workflows.append(normalize_workflow(workflow))
        for saved_workflow in related_workflows:
            for step in saved_workflow["steps"]:
                if step["type"] == "tui":
                    value = clean_entry(str(step.get("command", "")))
                    if value and value.lower() not in {existing.lower() for existing in command_items}:
                        command_items.append(value)
                elif step["type"] == "python":
                    value = clean_text(str(step.get("code", "")))
                    if value and value.lower() not in python_seen:
                        python_items.append(value)
                        python_seen.add(value.lower())
                elif step["type"] == "execute_on_demand":
                    value = clean_entry(str(step.get("function", "")))
                    if value and value.lower() not in {existing.lower() for existing in on_demand_items}:
                        on_demand_items.append(value)
                elif step["type"] == "load_scm":
                    value = clean_entry(str(step.get("path", "")))
                    if value and value.lower() not in {existing.lower() for existing in scm_items}:
                        scm_items.append(value)
        preset_groups = self._workflow_preset_groups(command_items, python_items, on_demand_items, scm_items)
        return WorkflowEditorDialog(
            self,
            workflow=workflow,
            command_items=command_items,
            python_items=python_items,
            on_demand_items=on_demand_items,
            scm_items=scm_items,
            preset_groups=preset_groups,
        )

    def _workflow_preset_groups(
        self,
        command_items: list[str],
        python_items: list[str],
        on_demand_items: list[str],
        scm_items: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        automation_workflows = self._read_workflows()
        sweep_workflows = self._read_sweep_workflows()
        sweep_button_presets: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            grid = self._current_sweep_param_grid()
            for item in self.sweep_buttons:
                action = item.get("action")
                if action == "define_rpvars":
                    sweep_button_presets.append(
                        {"label": item["name"], "step": {"type": "tui", "command": "\n".join(sweep_define_commands(grid))}}
                    )
                elif action == "reload_params":
                    sweep_button_presets.append(
                        {"label": item["name"], "step": {"type": "tui", "command": sweep_reload_command()}}
                    )
                elif action == "print_params":
                    sweep_button_presets.append(
                        {"label": item["name"], "step": {"type": "tui", "command": sweep_print_command()}}
                    )
        groups: dict[str, list[dict[str, Any]]] = {
            "快捷操作": [
                {"label": "检查网格", "step": {"type": "mesh_check"}},
                {
                    "label": "标准初始化",
                    "step": {
                        "type": "initialize",
                        "from_zone_type": combo_text(self.init_zone_type_edit) or DEFAULT_INIT_ZONE_TYPE,
                        "from_zone_name": combo_text(self.init_zone_name_edit) or DEFAULT_INIT_ZONE_NAME,
                        "phase": combo_text(self.init_phase_edit) or DEFAULT_INIT_PHASE,
                    },
                },
                {"label": f"计算 {self.iterations_spin.value()} 步", "step": {"type": "iterate", "count": self.iterations_spin.value()}},
            ],
            "TUI 预设": [{"label": item, "step": {"type": "tui", "command": item}} for item in command_items],
            "PyFluent 预设": [{"label": item, "step": {"type": "python", "code": item}} for item in python_items],
            "On Demand": [{"label": item, "step": {"type": "execute_on_demand", "function": item}} for item in on_demand_items],
            "SCM": [{"label": item, "step": {"type": "load_scm", "path": item}} for item in scm_items],
            "命令按钮": [
                {
                    "label": item["name"],
                    "step": {"type": "python", "code": item["command"]}
                    if item["mode"] == "python"
                    else {"type": "tui", "command": item["command"]},
                }
                for item in self.command_buttons
                if item.get("command")
            ],
            "后处理按钮": [
                {"label": item["name"], "step": {"type": "python", "code": item["code"]}}
                for item in self.plot_buttons
                if item.get("code")
            ],
            "流程页创建的自动化流程": [
                {"label": f"{workflow['name']}（{len(workflow['steps'])} 步）", "steps": workflow["steps"]}
                for workflow in automation_workflows
                if workflow.get("steps")
            ],
            "扫描页创建的流程": [
                {"label": f"{workflow['name']}（{len(workflow['steps'])} 步）", "steps": workflow["steps"]}
                for workflow in sweep_workflows
                if workflow.get("steps")
            ],
            "扫描模块按钮": sweep_button_presets,
            "后处理对象": [
                {"label": "显示已有 XY 图", "step": {"type": "post_object", "kind": "xy_plot", "action": "display", "ref": "0"}},
                {
                    "label": "保存已有 XY 图图片",
                    "step": {
                        "type": "post_object",
                        "kind": "xy_plot",
                        "action": "save_image",
                        "ref": "0",
                        "target": "xy_plot.png",
                    },
                },
                {
                    "label": "导出已有 XY 图数据",
                    "step": {
                        "type": "post_object",
                        "kind": "xy_plot",
                        "action": "write_data",
                        "ref": "0",
                        "target": "xy_plot.xy",
                    },
                },
                {"label": "显示已有等值图", "step": {"type": "post_object", "kind": "contour", "action": "display", "ref": "0"}},
            ],
            "参数扫描": [
                {"label": "刷新扫描 UDF 参数", "step": {"type": "tui", "command": sweep_reload_command()}},
                {"label": "打印扫描 UDF 参数", "step": {"type": "tui", "command": sweep_print_command()}},
                {
                    "label": "保存 Data 到组合文件夹",
                    "step": {"type": "python", "code": "write_data(combo_data)"},
                },
                {
                    "label": "导出 xy-plot-r-mm 数据",
                    "step": {
                        "type": "post_object",
                        "kind": "xy_plot",
                        "action": "write_data",
                        "ref": "xy-plot-r-mm",
                        "target": "{combo_dir}/xy-plot-r-mm.xy",
                    },
                },
                {
                    "label": "导出 xy-plot-t 数据",
                    "step": {
                        "type": "post_object",
                        "kind": "xy_plot",
                        "action": "write_data",
                        "ref": "xy-plot-t",
                        "target": "{combo_dir}/xy-plot-t.xy",
                    },
                },
            ],
        }
        return {label: items for label, items in groups.items() if items}

    def _add_workflow(self) -> None:
        dialog = self._workflow_dialog({"name": "新流程", "steps": [{"type": "mesh_check"}]})
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        workflows = self._read_workflows()
        workflows.append(dialog.workflow())
        self._save_workflows(workflows, len(workflows) - 1)

    def _edit_workflow(self) -> None:
        workflows = self._read_workflows()
        index = self.workflow_combo.currentIndex()
        if index < 0 or index >= len(workflows):
            return
        dialog = self._workflow_dialog(workflows[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        workflows[index] = dialog.workflow()
        self._save_workflows(workflows, index)

    def _delete_workflow(self) -> None:
        workflows = self._read_workflows()
        index = self.workflow_combo.currentIndex()
        if index < 0 or index >= len(workflows):
            return
        reply = QMessageBox.question(
            self,
            "删除流程",
            f"删除流程“{workflows[index]['name']}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del workflows[index]
        self._save_workflows(workflows, max(0, index - 1))

    def _refresh_workflow_buttons(self, workflows: list[dict[str, Any]] | None = None) -> None:
        workflows = workflows if workflows is not None else self._read_workflows()
        while self.workflow_button_grid.count():
            item = self.workflow_button_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.workflow_buttons = []
        self.workflow_empty_label.setVisible(not workflows)
        for index, workflow in enumerate(workflows):
            button = QPushButton(workflow["name"])
            button.setMinimumHeight(38)
            button.setToolTip("\n".join(workflow_step_summary(step) for step in workflow["steps"]))
            button.clicked.connect(lambda _checked=False, row=index: self._run_workflow(row))
            self.workflow_buttons.append(button)
            self.workflow_button_grid.addWidget(button, index // 2, index % 2)
        self._update_enabled_state()

    def _run_workflow(self, index: int) -> None:
        workflows = self._read_workflows()
        if index < 0 or index >= len(workflows):
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再运行流程。")
            return
        iteration_count = self._workflow_iteration_count(workflows[index])
        if iteration_count:
            self._begin_calculation_progress(iteration_count)
        self._submit(f"流程：{workflows[index]['name']}", self.controller.run_workflow, workflows[index])

    def _use_preset_command(self) -> None:
        preset = combo_plain_text(self.preset_combo)
        if preset:
            set_combo_text(self.command_edit, preset)
            line_edit = self.command_edit.lineEdit()
            if line_edit is not None:
                line_edit.setFocus()
                line_edit.selectAll()

    def _run_preset_command(self) -> None:
        self._use_preset_command()
        self._send_command()

    def _clear_command_input(self) -> None:
        set_combo_text(self.command_edit, "")
        line_edit = self.command_edit.lineEdit()
        if line_edit is not None:
            line_edit.setFocus()

    def _add_preset_command(self) -> None:
        command = combo_plain_text(self.command_edit)
        if not command:
            QMessageBox.information(self, "没有命令", "请先在命令输入框中输入一条命令。")
            return
        items = [item for item in self._read_command_presets() if item.lower() != command.lower()]
        items.insert(0, command)
        self._save_command_presets(items, command)
        self.statusBar().showMessage("已添加命令预设")

    def _remove_preset_command(self) -> None:
        preset = combo_plain_text(self.preset_combo)
        if not preset:
            QMessageBox.information(self, "没有预设", "当前没有可删除的预设指令。")
            return
        items = [item for item in self._read_command_presets() if item.lower() != preset.lower()]
        self._save_command_presets(items)
        self.statusBar().showMessage("已删除命令预设")

    def _send_command(self) -> None:
        command = combo_plain_text(self.command_edit)
        if not command:
            return
        if not self.controller.has_session:
            QMessageBox.warning(self, "Fluent 未启动", "请先启动 Fluent，再发送命令。")
            return
        history_key = self._command_history_key()
        remember_text_history(self.settings, history_key, command)
        populate_combo(self.command_edit, read_text_history(self.settings, history_key), "")
        self._update_command_placeholder()
        mode = self._command_mode()
        iteration_count = self._iteration_count_from_command(command, mode)
        if iteration_count:
            self._begin_calculation_progress(iteration_count)
        if mode == "python":
            self._submit("执行 PyFluent 语句", self.controller.execute_python, command)
        else:
            self._submit("发送 TUI 命令", self.controller.execute_tui, command)

    def _error_summary(self, detail: str) -> str:
        lines = [line.strip() for line in str(detail or "").splitlines() if line.strip()]
        if not lines:
            return "未知错误。"
        for line in reversed(lines):
            if re.match(r"^[A-Za-z_][\w.]*Error\b|^[A-Za-z_][\w.]*Exception\b|^RuntimeError\b", line):
                return line[:420]
        return lines[-1][:420]

    def _show_error_dialog(self, title: str, message: str, detail: str = "") -> None:
        now = time.monotonic()
        if self._error_dialog_open or now - self._last_error_dialog_at < 1.0:
            return
        self._error_dialog_open = True
        self._last_error_dialog_at = now
        try:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(title)
            box.setText(message)
            if detail:
                box.setDetailedText(str(detail)[-20000:])
            box.exec()
        finally:
            self._error_dialog_open = False

    def _submit(self, label: str, func: Callable[..., None], *args: Any) -> bool:
        if self.busy:
            self._queue_console_text(f"[{now_text()}] 当前正在执行任务，稍后再试：{label}\n")
            self._set_status(f"正在执行：{self.current_task_label or label}")
            return False
        self.current_task_label = label
        self._set_status(f"正在执行：{label}")
        self._queue_console_text(f"[{now_text()}] 开始：{label}\n")
        self.app_signals.busy_changed.emit(True)
        try:
            future = self.executor.submit(func, *args)
        except Exception:
            error = traceback.format_exc()
            self._queue_console_text(f"[{now_text()}] {label} 提交失败：\n{error}\n")
            self._set_status(f"{label} 提交失败")
            self.current_task_label = ""
            self.app_signals.busy_changed.emit(False)
            self._show_error_dialog("任务提交失败", f"{label} 无法启动。", error)
            return False
        future.add_done_callback(lambda fut, task_label=label: self._on_future_done(task_label, fut))
        return True

    def _on_future_done(self, label: str, future: Future) -> None:
        error = ""
        try:
            future.result()
        except Exception:
            error = traceback.format_exc()
        with contextlib.suppress(RuntimeError):
            self.window_signals.task_finished.emit(label, error)

    def _task_finished(self, label: str, error: str) -> None:
        if error:
            self._queue_console_text(f"[{now_text()}] {label} 失败：\n{error}\n")
            self._set_status(f"{label} 失败")
            self._show_error_dialog(f"{label} 失败", self._error_summary(error), error)
        else:
            self._queue_console_text(f"[{now_text()}] 完成：{label}\n")
        if self.calculation_active:
            self._finish_calculation_progress(not error)
        if label.startswith("参数扫描："):
            stopped = "停止" in self.sweep_progress_label.text()
            self._finish_sweep_progress(not error and not stopped, "失败" if error else ("已停止" if stopped else "完成"))
        if self.pending_post_refresh:
            self.pending_post_refresh = False
            try:
                self._refresh_post_results()
            except Exception:
                self._queue_console_text(f"[{now_text()}] 刷新后处理结果失败：\n{traceback.format_exc()}\n")
                self._set_status("刷新后处理结果失败")
        if self.current_task_label == label:
            self.current_task_label = ""
        self.app_signals.busy_changed.emit(False)

    def _parse_progress_line(self, line: str) -> None:
        if not self.calculation_active or self.calculation_expected <= 0:
            return
        if line.lstrip().startswith("["):
            return
        match = ITERATION_LINE_RE.match(line)
        if not match:
            return
        iteration = safe_int(match.group(1), -1)
        if iteration < 0:
            return
        if self.calculation_first_iteration is None:
            self.calculation_first_iteration = iteration
        if self.calculation_last_iteration is not None:
            if iteration == self.calculation_last_iteration:
                return
            if iteration < self.calculation_last_iteration:
                completed = max(0, self.calculation_last_iteration - self.calculation_first_iteration + 1)
                self.calculation_completed_offset += completed
                self.calculation_first_iteration = iteration
        self.calculation_last_iteration = iteration
        done = self.calculation_completed_offset + iteration - self.calculation_first_iteration + 1
        self._set_calculation_progress(done)

    def _parse_progress_text(self, text: str) -> None:
        if not self.calculation_active:
            return
        data = self.progress_parse_tail + str(text or "")
        lines = data.splitlines()
        if data and not data.endswith(("\n", "\r")):
            self.progress_parse_tail = lines.pop() if lines else data
        else:
            self.progress_parse_tail = ""
        for line in lines:
            self._parse_progress_line(line)

    def _queue_console_text(self, text: str) -> None:
        if not text:
            return
        value = str(text)
        self._parse_progress_text(value)
        self.console_buffer.append(value)
        self.console_buffer_chars += len(value)
        while self.console_buffer_chars > CONSOLE_BUFFER_HARD_LIMIT and self.console_buffer:
            dropped = self.console_buffer.popleft()
            self.console_buffer_chars = max(0, self.console_buffer_chars - len(dropped))
        if not self.console_flush_timer.isActive():
            self.console_flush_timer.start()
        elif self.console_buffer_chars >= CONSOLE_FORCE_FLUSH_CHARS:
            self.console_flush_timer.start(0)

    def _take_console_chunk(self, max_chars: int) -> str:
        parts: list[str] = []
        taken = 0
        limit = max(1, int(max_chars))
        while self.console_buffer and taken < limit:
            item = self.console_buffer.popleft()
            room = limit - taken
            if len(item) <= room:
                parts.append(item)
                taken += len(item)
            else:
                parts.append(item[:room])
                self.console_buffer.appendleft(item[room:])
                taken += room
                break
        self.console_buffer_chars = max(0, self.console_buffer_chars - taken)
        return "".join(parts)

    def _flush_console_buffer(self) -> None:
        self.console_flush_timer.setInterval(CONSOLE_FLUSH_MS)
        if not self.console_buffer:
            return
        text = self._take_console_chunk(CONSOLE_FLUSH_CHUNK_CHARS)
        self._append_console(text)
        if self.console_buffer:
            self.console_flush_timer.start(0)

    def _clear_console(self) -> None:
        self.console_buffer.clear()
        self.console_buffer_chars = 0
        self.console.clear()

    def _console_kind(self, text: str) -> str:
        line = str(text or "")
        if CONSOLE_COMMAND_RE.search(line):
            return "command"
        if CONSOLE_ERROR_RE.search(line):
            return "error"
        if CONSOLE_WARNING_RE.search(line):
            return "warning"
        if line.startswith("[") and re.match(r"^\[\d{2}:\d{2}:\d{2}\]", line):
            return "event"
        return "normal"

    def _append_console(self, text: str) -> None:
        self.console.setUpdatesEnabled(False)
        scrollbar = self.console.verticalScrollBar()
        auto_scroll = scrollbar.value() >= max(0, scrollbar.maximum() - 8)
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        edit_block_started = False
        try:
            cursor.beginEditBlock()
            edit_block_started = True
            current_kind = ""
            chunks: list[str] = []

            def flush_chunks() -> None:
                nonlocal chunks
                if chunks:
                    cursor.insertText("".join(chunks), self.console_formats[current_kind or "normal"])
                    chunks = []

            for line in str(text or "").splitlines(keepends=True):
                if not line:
                    continue
                line_kind = self._console_kind(line.rstrip("\r\n"))
                if line_kind != current_kind:
                    flush_chunks()
                    current_kind = line_kind
                chunks.append(line)
            flush_chunks()
            cursor.endEditBlock()
            edit_block_started = False
            self.console.setTextCursor(cursor)
        finally:
            if edit_block_started:
                with contextlib.suppress(Exception):
                    cursor.endEditBlock()
            self.console.setUpdatesEnabled(True)
        if auto_scroll:
            self.console.ensureCursorVisible()

    def _set_status(self, text: str) -> None:
        display_text = str(text or "")
        self.status_label.setToolTip(display_text)
        if len(display_text) > 38:
            display_text = f"{display_text[:35]}..."
        self.status_label.setText(display_text)
        lowered = str(text or "").lower()
        if any(token in lowered for token in ("失败", "error", "failed", "traceback")):
            state = "error"
        elif any(token in lowered for token in ("就绪", "已", "完成", "ready", "success")):
            state = "ready"
        elif any(token in lowered for token in ("正在", "启动", "编译", "读取", "保存", "加载", "busy")):
            state = "busy"
        else:
            state = "idle"
        if self.status_label.property("status") != state:
            self.status_label.setProperty("status", state)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
        self.statusBar().showMessage(text)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if hasattr(self, "header_busy_progress"):
            self.header_busy_progress.setVisible(busy)
        self._update_enabled_state()

    def _update_enabled_state(self) -> None:
        has_session = self.controller.has_session
        sweep_running = self.sweep_active
        scan_running = self.sweep_disk_scan_active
        self.start_btn.setEnabled(not self.busy and not has_session)
        self.stop_btn.setEnabled(not self.busy and has_session)
        self.build_udf_btn.setEnabled(not self.busy and has_session)
        self.execute_on_demand_btn.setEnabled(not self.busy and has_session)
        self.send_btn.setEnabled(not self.busy and has_session)
        self.load_scm_btn.setEnabled(not self.busy and has_session)
        self.mesh_check_btn.setEnabled(not self.busy and has_session)
        self.initialize_btn.setEnabled(not self.busy and has_session)
        self.iterate_btn.setEnabled(not self.busy and has_session)
        self.stop_calc_btn.setEnabled(has_session and self.calculation_active)
        for button in self.workflow_buttons:
            button.setEnabled(not self.busy and has_session)
        self.add_workflow_btn.setEnabled(not self.busy)
        self.edit_workflow_btn.setEnabled(not self.busy and self.workflow_combo.count() > 0)
        self.delete_workflow_btn.setEnabled(not self.busy and self.workflow_combo.count() > 0)
        self.workflow_combo.setEnabled(not self.busy and self.workflow_combo.count() > 0)
        self.load_sweep_config_btn.setEnabled(not self.busy and not scan_running)
        self.save_sweep_grid_btn.setEnabled(not self.busy and not scan_running)
        self.preview_sweep_combos_btn.setEnabled(not self.busy and not scan_running)
        self.sweep_module_path_edit.setEnabled(not self.busy and not scan_running)
        self.browse_sweep_module_path_btn.setEnabled(not self.busy and not scan_running)
        self.open_sweep_module_path_btn.setEnabled(not self.busy)
        self.sweep_config_path_edit.setEnabled(not self.busy and not scan_running)
        self.browse_sweep_config_path_btn.setEnabled(not self.busy and not scan_running)
        self.open_sweep_config_path_btn.setEnabled(not self.busy)
        self.sweep_grid_editor.setEnabled(not self.busy and not scan_running)
        self.sweep_scan_dir_edit.setEnabled(not self.busy and not scan_running)
        self.browse_sweep_scan_dir_btn.setEnabled(not self.busy and not scan_running)
        self.open_sweep_scan_dir_btn.setEnabled(not self.busy)
        self.sweep_base_case_edit.setEnabled(not self.busy and not scan_running)
        self.browse_sweep_base_case_btn.setEnabled(not self.busy and not scan_running)
        self.open_sweep_base_case_btn.setEnabled(not self.busy)
        self.sweep_init_workflow_combo.setEnabled(not self.busy and not scan_running)
        self.sweep_post_workflow_combo.setEnabled(not self.busy and not scan_running)
        self.sweep_iterations_spin.setEnabled(not self.busy and not scan_running)
        self.skip_completed_sweep_checkbox.setEnabled(not self.busy and not scan_running)
        self.sweep_combo_list.setEnabled(not self.busy or sweep_running)
        self.sweep_preview_text.setEnabled(not self.busy)
        self.sweep_preview_toggle.setEnabled(not self.busy)
        self.sweep_advanced_box.setEnabled(not self.busy)
        self.sweep_advanced_tabs.setEnabled(not self.busy)
        has_sweep_combos = self.sweep_combo_list.rowCount() > 0
        self.sweep_combo_filter_param_combo.setEnabled(has_sweep_combos and (not self.busy or sweep_running))
        self.sweep_combo_filter_value_combo.setEnabled(has_sweep_combos and (not self.busy or sweep_running))
        self.sweep_combo_filter_only_checkbox.setEnabled(has_sweep_combos and (not self.busy or sweep_running))
        self.sweep_combo_filter_select_btn.setEnabled(not self.busy and not scan_running and has_sweep_combos)
        self.sweep_combo_filter_unselect_btn.setEnabled(not self.busy and not scan_running and has_sweep_combos)
        self.select_all_sweep_combos_btn.setEnabled(not self.busy and not scan_running and has_sweep_combos)
        self.clear_sweep_selection_btn.setEnabled(not self.busy and not scan_running and has_sweep_combos)
        self.scan_sweep_completed_btn.setEnabled(not self.busy and not scan_running and has_sweep_combos)
        self.reset_sweep_status_btn.setEnabled(not self.busy and not scan_running and has_sweep_combos)
        self.pause_sweep_btn.setEnabled(sweep_running and not self.sweep_paused)
        self.resume_sweep_btn.setEnabled(sweep_running and self.sweep_paused)
        self.retry_sweep_btn.setEnabled(sweep_running or (not self.busy and has_sweep_combos))
        self.stop_sweep_btn.setEnabled(sweep_running)
        self.add_sweep_button_btn.setEnabled(not self.busy)
        self.reset_sweep_buttons_btn.setEnabled(not self.busy)
        for index, button in enumerate(self.sweep_run_buttons):
            action = self.sweep_buttons[index]["action"] if index < len(self.sweep_buttons) else ""
            action_can_autostart = action in {"run_selected_combo", "run_all_combos"}
            button.setEnabled(not self.busy and (has_session or action == "preview_selected_combo" or action_can_autostart))
        for button in self.sweep_edit_buttons:
            button.setEnabled(not self.busy)
        for button in self.sweep_delete_buttons:
            button.setEnabled(not self.busy)
        self.add_sweep_workflow_btn.setEnabled(not self.busy)
        self.edit_sweep_workflow_btn.setEnabled(not self.busy and self.sweep_workflow_combo.count() > 0)
        self.delete_sweep_workflow_btn.setEnabled(not self.busy and self.sweep_workflow_combo.count() > 0)
        self.sweep_workflow_combo.setEnabled(not self.busy and self.sweep_workflow_combo.count() > 0)
        self.run_sweep_workflow_btn.setEnabled(
            not self.busy and not scan_running and self.sweep_workflow_combo.count() > 0 and has_sweep_combos
        )
        self.run_all_sweep_workflow_btn.setEnabled(
            not self.busy and not scan_running and self.sweep_workflow_combo.count() > 0 and has_sweep_combos
        )
        for button in self.sweep_workflow_buttons:
            button.setEnabled(not self.busy and has_sweep_combos)
        self.command_edit.setEnabled(not self.busy)
        self.command_scm_file_edit.setEnabled(not self.busy)
        self.browse_command_scm_btn.setEnabled(not self.busy)
        self.open_command_scm_btn.setEnabled(not self.busy)
        self.iterations_spin.setEnabled(not self.busy)
        self.init_zone_type_edit.setEnabled(not self.busy)
        self.init_zone_name_edit.setEnabled(not self.busy)
        self.init_phase_edit.setEnabled(not self.busy)
        self.on_demand_function_edit.setEnabled(not self.busy)
        self.preset_combo.setEnabled(not self.busy)
        self.use_preset_btn.setEnabled(not self.busy)
        self.run_preset_btn.setEnabled(not self.busy and has_session)
        self.add_preset_btn.setEnabled(not self.busy)
        self.remove_preset_btn.setEnabled(not self.busy)
        self.clear_command_btn.setEnabled(not self.busy)
        self.add_command_button_btn.setEnabled(not self.busy)
        self.add_command_button_from_input_btn.setEnabled(not self.busy)
        self.reset_command_buttons_btn.setEnabled(not self.busy)
        for button in self.command_run_buttons:
            button.setEnabled(not self.busy and has_session)
        for button in self.command_edit_buttons:
            button.setEnabled(not self.busy)
        for button in self.command_delete_buttons:
            button.setEnabled(not self.busy)
        self.post_output_dir_edit.setEnabled(not self.busy and not self.post_refresh_active)
        self.browse_post_dir_btn.setEnabled(not self.busy and not self.post_refresh_active)
        self.open_post_dir_btn.setEnabled(not self.busy)
        self.refresh_post_btn.setEnabled(not self.busy and not self.post_refresh_active)
        self.post_command_edit.setEnabled(not self.busy)
        self.run_post_command_btn.setEnabled(not self.busy and has_session)
        self.post_picture_name_edit.setEnabled(not self.busy)
        self.save_picture_btn.setEnabled(not self.busy and has_session)
        self.post_object_type_combo.setEnabled(not self.busy)
        self.post_object_ref_combo.setEnabled(not self.busy)
        self.post_object_target_edit.setEnabled(not self.busy)
        self.refresh_post_objects_btn.setEnabled(
            not self.busy and has_session and not self.post_object_refresh_active
        )
        self.display_post_object_btn.setEnabled(not self.busy and has_session)
        self.save_post_object_image_btn.setEnabled(not self.busy and has_session)
        self.write_post_object_data_btn.setEnabled(not self.busy and has_session)
        self.open_post_results_btn.setEnabled(not self.busy)
        self.add_plot_button_btn.setEnabled(not self.busy)
        self.reset_plot_buttons_btn.setEnabled(not self.busy)
        for button in self.plot_run_buttons:
            button.setEnabled(not self.busy and has_session)
        for button in self.plot_edit_buttons:
            button.setEnabled(not self.busy)
        for button in self.plot_delete_buttons:
            button.setEnabled(not self.busy)
        for button in (
            self.read_case_btn,
            self.read_data_btn,
            self.write_case_btn,
            self.write_data_btn,
            self.write_case_data_btn,
        ):
            button.setEnabled(not self.busy and has_session)
        for button in (
            self.open_work_btn,
            self.open_case_btn,
            self.open_launch_scm_btn,
            self.open_file_btn,
            self.open_udf_btn,
            self.file_use_case_btn,
            self.file_use_work_btn,
        ):
            button.setEnabled(not self.busy)
        for widget in (
            self.work_dir_edit,
            self.case_file_edit,
            self.browse_work_btn,
            self.browse_case_btn,
            self.clear_case_btn,
            self.dim_combo,
            self.cores_spin,
            self.gui_checkbox,
            self.load_scm_on_start_checkbox,
        ):
            widget.setEnabled(not self.busy and not has_session)
        launch_scm_enabled = (
            not self.busy and not has_session and self.load_scm_on_start_checkbox.isChecked()
        )
        for widget in (
            self.launch_scm_file_edit,
            self.browse_launch_scm_btn,
            self.clear_launch_scm_btn,
        ):
            widget.setEnabled(launch_scm_enabled)
        for widget in (
            self.file_path_edit,
            self.browse_file_btn,
            self.save_file_btn,
            self.udf_dir_edit,
            self.browse_udf_btn,
            self.open_udf_btn,
        ):
            widget.setEnabled(not self.busy)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self.output_layout_initialized:
            self.output_layout_initialized = True
            QTimer.singleShot(0, self._apply_output_layout)
        if self.topmost_btn.isChecked():
            QTimer.singleShot(0, lambda: self._apply_topmost_native(True, report_error=False))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)

    def _on_close_shutdown_done(self, future: Future) -> None:
        try:
            future.result()
        except Exception:
            print("PyFluent Lite close shutdown failed:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_settings()
        has_running_work = any(
            (
                self.busy,
                self.sweep_active,
            )
        )
        if has_running_work:
            reply = QMessageBox.question(
                self,
                "任务仍在执行",
                "当前仍有任务或后台扫描在执行。现在退出可能中断任务，仍要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        close_fluent = False
        if self.controller.has_session:
            reply = QMessageBox.question(
                self,
                "关闭 Fluent",
                "退出工具时关闭当前 Fluent 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.StandardButton.Yes:
                close_fluent = True

        if close_fluent:
            try:
                future = self.executor.submit(self.controller.shutdown)
                future.add_done_callback(self._on_close_shutdown_done)
            except Exception:
                print("PyFluent Lite failed to schedule Fluent shutdown on close:", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)

        self.executor.shutdown(wait=False, cancel_futures=not close_fluent)
        self.interrupt_executor.shutdown(wait=False, cancel_futures=True)
        self.scan_executor.shutdown(wait=False, cancel_futures=True)
        self.io_executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


def install_exception_hook(app: QApplication) -> None:
    notifier = ExceptionNotifier()
    notifier.setParent(app)
    dialog_open = False

    def show_exception(summary: str, detail: str) -> None:
        nonlocal dialog_open
        if dialog_open:
            return
        dialog_open = True
        try:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("未处理异常")
            box.setText(f"程序遇到未处理异常，已写入错误输出。\n\n{summary}")
            box.setDetailedText(detail[-20000:])
            box.exec()
        finally:
            dialog_open = False

    notifier.unhandled_exception.connect(show_exception)

    def report_exception(exc_type, exc_value, exc_traceback, context: str = "") -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        if context:
            detail = f"{context}\n\n{detail}"
        summary = f"{exc_type.__name__}: {exc_value}"
        print(detail, file=sys.stderr)
        if QApplication.instance() is app:
            notifier.unhandled_exception.emit(summary, detail)

    def handle_thread_exception(args) -> None:  # type: ignore[no-untyped-def]
        report_exception(args.exc_type, args.exc_value, args.exc_traceback, "后台线程未处理异常")

    def handle_unraisable(unraisable) -> None:  # type: ignore[no-untyped-def]
        exc_type = type(unraisable.exc_value)
        context = f"对象析构或回调中出现未处理异常：{unraisable.object!r}"
        report_exception(exc_type, unraisable.exc_value, unraisable.exc_traceback, context)

    sys.excepthook = report_exception
    threading.excepthook = handle_thread_exception
    sys.unraisablehook = handle_unraisable


def main() -> int:
    app = QApplication(sys.argv)
    apply_application_font(app)
    install_exception_hook(app)
    available_styles = {name.lower(): name for name in QStyleFactory.keys()}
    style_name = (
        available_styles.get("windowsvista")
        or available_styles.get("windows")
        or available_styles.get("fusion")
    )
    if style_name:
        app.setStyle(style_name)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("pyfluent_qt_lite")
    window = MainWindow()
    window.show()
    return app.exec()
