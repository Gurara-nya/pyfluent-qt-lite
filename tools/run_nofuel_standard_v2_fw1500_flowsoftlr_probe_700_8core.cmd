@echo off
setlocal

set CODEX_COMBO256_WORK=F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat\fw1500_flowsoftlr_8core_recovery
set CODEX_COMBO256_RUN_ROOT=F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run\fw1500_flowsoftlr_8core_recovery

if not exist "%CODEX_COMBO256_WORK%" mkdir "%CODEX_COMBO256_WORK%"
if not exist "%CODEX_COMBO256_RUN_ROOT%" mkdir "%CODEX_COMBO256_RUN_ROOT%"

set CODEX_COMBO256_BASE_CASE=D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um-flowsoft-lr.cas.h5
set CODEX_COMBO256_MESH_DIR=D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1500
set CODEX_COMBO256_MESH_FILE=D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1500\d40-nofuel-standard-v2-fw1500-fluent.msh
set CODEX_COMBO256_UDF_DIR=D:\Workshop\UDF\dpm-cal-udf
set CODEX_COMBO256_COMBO_INDEX=256
set CODEX_COMBO256_DIMENSION=2D
set CODEX_COMBO256_CORES=8
set CODEX_COMBO256_ITERATIONS=700
set CODEX_COMBO256_OUTPUT_TAG=nofuel-standard-v2-fw1500-flowsoftlr-probe-iter700-8core
set CODEX_COMBO256_RUN_ID=fw1500_flowsoftlr_probe_700_8core
set CODEX_COMBO256_STATE=%CODEX_COMBO256_RUN_ROOT%\fw1500_flowsoftlr_probe_8core_state.json
set CODEX_COMBO256_LOG=%CODEX_COMBO256_RUN_ROOT%\fw1500_flowsoftlr_probe_8core_fluent.log
set CODEX_COMBO256_PREPARED_CASE=%CODEX_COMBO256_WORK%\standard-bl12um-h290um-flowsoft-lr-nofuel-standard-v2-fw1500-flowsoftlr-probe-iter700-8core.cas.h5
set CODEX_COMBO256_DATA_FILE=%CODEX_COMBO256_WORK%\combo-256-nofuel-standard-v2-fw1500-flowsoftlr-probe-iter700-8core.dat.h5
set CODEX_COMBO256_STDOUT=%CODEX_COMBO256_RUN_ROOT%\fw1500_flowsoftlr_probe_8core_stdout.log
set CODEX_COMBO256_STDERR=%CODEX_COMBO256_RUN_ROOT%\fw1500_flowsoftlr_probe_8core_stderr.log

C:\Python314\python.exe -u F:\pyfluent_qt_lit\tools\codex_combo256_single_runner.py > "%CODEX_COMBO256_STDOUT%" 2> "%CODEX_COMBO256_STDERR%"
