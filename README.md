# PyFluent Qt Lite

PyFluent Qt Lite 是一个面向 ANSYS Fluent / PyFluent 的轻量级桌面控制台。它把常用的 Fluent 启动、Case/Data 读写、TUI 命令、UDF 编译加载、后处理和参数扫描流程放进一个本地 Qt 界面里，适合需要频繁调试 Fluent case、UDF 和批量算例的小型工作流。

项目当前主要面向 Windows + Fluent + Visual Studio Build Tools 环境开发和使用。

## 功能亮点

- 单实例 Qt 桌面界面，集中管理工作目录、case 文件、Case/Data 文件、UDF 源码目录和常用 TUI 命令。
- 启动 Fluent 后可读取 Case/Data、保存 Case/Data，并在控制台区域实时查看 transcript 和工具日志。
- 内置 TUI 控制台，可发送原始 Fluent 命令，并对 `Warning:`、`Error:` 和用户命令做高亮显示。
- 支持自定义预设 TUI 指令、快捷开始/停止计算，并尝试从 Fluent 迭代表格中解析进度。
- 内置 UDF 编译器，使用 Fluent 官方 `makefile_nt.udf` + `nmake` 流程生成并加载 `libudf`。
- 后处理页可运行后处理命令、保存当前图形窗口、扫描预览输出图片，并按名称或编号操作 XY 图、等值图、矢量图、迹线图和报告/表。
- Py 编辑页提供可编辑的 PyFluent 后处理脚本模板，支持导入、导出和运行多行脚本。
- 参数扫描页集成 `tools/sweep.py`，可预览参数组合、回写 `tools/sweep_config.py`，并按组合执行自定义工作流。
- 流程编辑器可从快捷操作、命令按钮、后处理按钮、后处理对象等来源生成步骤，便于把常用动作串成半自动流程。

## 环境要求

- Python 3.10 或更新版本
- ANSYS Fluent / PyFluent 可用环境
- Windows 下编译 UDF 时需要 Visual Studio Build Tools，并能调用 `VsDevCmd.bat`
- Python 依赖：
  - `ansys-fluent-core`
  - `PySide6`

## 快速开始

```bat
cd /d <项目目录>
pip install -r requirements.txt
run.bat
```

也可以直接使用模块入口：

```bat
cd /d <项目目录>
python -m pyfluent_qt_lite
```

安装为命令行脚本后：

```bat
pip install -e .
pyfluent-qt-lite
```

## UDF 编译

GUI 中点击“编译并加载 UDF”后，工具会扫描选定的 UDF 源码目录，复制 Fluent 官方 UDF makefile，生成 host/node 的 `user_nt.udf`，然后调用 Visual Studio 开发者命令环境和 `nmake` 编译 `libudf`。

默认输出目录：

```text
<UDF 源码目录>\libudf
```

编译成功后，生成的 `libudf` 会复制到：

- `<UDF 源码目录>\libudf`
- `<当前 Fluent 工作目录>\libudf`

随后工具会在当前 Fluent session 中尝试卸载旧的 `libudf`，再加载新的 `libudf`。

也可以单独使用 CLI：

```bat
udf_build.bat scan
udf_build.bat inspect --solver 2ddp
udf_build.bat build --project-dir "D:\path\to\udf-project" --solver 2ddp
udf_build.bat build --project-dir "D:\path\to\udf-project" --solver 2ddp --dry-run
udf_build.bat clean --project-dir "D:\path\to\udf-project"
```

常用环境变量：

```bat
set PYFLUENT_LITE_FLUENT_ROOT=C:\Program Files\ANSYS Inc\v252\fluent
set PYFLUENT_LITE_FLUENT_RELEASE=C:\Program Files\ANSYS Inc\v252\fluent\fluent25.2.0
set PYFLUENT_LITE_VSDEVCMD=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat
set PYFLUENT_LITE_UDF_SOLVER=2ddp
set PYFLUENT_LITE_UDF_TARGETS=host,node
set PYFLUENT_LITE_UDF_PARALLEL_NODE=auto
```

## 参数扫描

`tools/` 目录提供了一个独立的参数扫描接口库：

- `tools/sweep.py`：生成 Fluent Scheme/TUI 命令字符串，不直接调用 Fluent，也不处理文件 I/O。
- `tools/sweep_config.py`：默认参数网格配置，可由 GUI 参数扫描页回写。
- `tools/README.md`：更完整的参数扫描接口说明和 PyFluent / journal / subprocess 示例。

典型流程是先创建 rpvar，再对每个参数组合设置变量、刷新 UDF 全局缓存、执行迭代并导出结果。

## 打包

```bat
cd /d <项目目录>
pip install -e .[build]
build.bat
```

打包脚本使用 `PyFluentLite.spec` 生成 PyInstaller 桌面应用。

## 项目结构

```text
pyfluent_qt_lite/          Qt 主程序包
pyfluent_qt_lite/udf/      内置 UDF 编译器和 CLI
tools/                     参数扫描接口与默认 PARAM_GRID 配置
pyfluent_lite_entry.py     PyInstaller 入口
PyFluentLite.spec          PyInstaller spec
run.bat                    本地运行入口
udf_build.bat              UDF 编译 CLI 入口
build.bat                  打包入口
```

## 开发检查

```bat
python -m compileall -q .
```

## 说明

这个项目是一个面向实际 Fluent 工作流的小工具，重点是把常用操作收拢到一个顺手的本地控制面板里。公开仓库不包含 Fluent case/data 文件、编译产物、运行日志或本机测试输出。
