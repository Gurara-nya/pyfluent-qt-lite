@echo off
cd /d F:\pyfluent_qt_lit
if not exist "F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\run" mkdir "F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\run"
set CODEX_COMBO256_COMBO_INDEX=256
set CODEX_BATCH_MAX_ATTEMPTS=3
C:\Python314\python.exe -u F:\pyfluent_qt_lit\tools\codex_mesh_independence_batch.py >> F:\pyfluent_qt_lit\fluent_outputs\mesh_independence_700__20260522-20260523\run\batch_process.cmd.log 2>&1
