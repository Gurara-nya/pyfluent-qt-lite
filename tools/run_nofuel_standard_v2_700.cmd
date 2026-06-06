@echo off
setlocal
cd /d F:\pyfluent_qt_lit

set CODEX_MESH_INDEPENDENCE_ROOT=D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2
set CODEX_COMBO256_WORK=F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat
set CODEX_BATCH_RUN_ROOT=F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run
set CODEX_COMBO256_BASE_CASE=D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5
set CODEX_COMBO256_ITERATIONS=700
set CODEX_COMBO256_CORES=16
set CODEX_COMBO256_COMBO_INDEX=256
set CODEX_BATCH_MAX_ATTEMPTS=3
set CODEX_BATCH_CONTINUE_ON_FAILURE=1

if not exist "%CODEX_COMBO256_WORK%" mkdir "%CODEX_COMBO256_WORK%"
if not exist "%CODEX_BATCH_RUN_ROOT%" mkdir "%CODEX_BATCH_RUN_ROOT%"

C:\Python314\python.exe -u F:\pyfluent_qt_lit\tools\codex_mesh_independence_batch.py >> "%CODEX_BATCH_RUN_ROOT%\batch_process.cmd.log" 2>&1
endlocal
