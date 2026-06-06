@echo off
setlocal
cd /d F:\pyfluent_qt_lit

set CODEX_COMBO256_WORK=F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat\fw1250_rerun_20260524
set CODEX_COMBO256_RUN_ROOT=F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run\fw1250_rerun_20260524

if not exist "%CODEX_COMBO256_WORK%" mkdir "%CODEX_COMBO256_WORK%"
if not exist "%CODEX_COMBO256_RUN_ROOT%" mkdir "%CODEX_COMBO256_RUN_ROOT%"

set CODEX_COMBO256_BASE_CASE=D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5
set CODEX_COMBO256_MESH_DIR=D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1250
set CODEX_COMBO256_MESH_FILE=D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1250\d40-nofuel-standard-v2-fw1250-fluent.msh
set CODEX_COMBO256_UDF_DIR=D:\Workshop\UDF\dpm-cal-udf
set CODEX_COMBO256_COMBO_INDEX=256
set CODEX_COMBO256_DIMENSION=2D
set CODEX_COMBO256_CORES=16
set CODEX_COMBO256_ITERATIONS=700
set CODEX_COMBO256_OUTPUT_TAG=nofuel-standard-v2-fw1250-rerun1-iter700
set CODEX_COMBO256_RUN_ID=fw1250_rerun1_700
set CODEX_COMBO256_STATE=%CODEX_COMBO256_RUN_ROOT%\fw1250_rerun1_state.json
set CODEX_COMBO256_LOG=%CODEX_COMBO256_RUN_ROOT%\fw1250_rerun1_fluent.log
set CODEX_COMBO256_PREPARED_CASE=%CODEX_COMBO256_WORK%\standard-bl12um-h290um-nofuel-standard-v2-fw1250-rerun1-iter700.cas.h5
set CODEX_COMBO256_DATA_FILE=%CODEX_COMBO256_WORK%\combo-256-nofuel-standard-v2-fw1250-rerun1-iter700.dat.h5
set CODEX_COMBO256_STDOUT=%CODEX_COMBO256_RUN_ROOT%\fw1250_rerun1_stdout.log
set CODEX_COMBO256_STDERR=%CODEX_COMBO256_RUN_ROOT%\fw1250_rerun1_stderr.log

C:\Python314\python.exe -u F:\pyfluent_qt_lit\tools\codex_combo256_single_runner.py > "%CODEX_COMBO256_STDOUT%" 2> "%CODEX_COMBO256_STDERR%"
endlocal
