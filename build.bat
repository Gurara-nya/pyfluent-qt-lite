@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --windowed --name PyFluentLite ^
  --distpath dist ^
  --workpath build ^
  --specpath . ^
  --hidden-import ansys.fluent.core ^
  --collect-submodules ansys.fluent.core ^
  --collect-data ansys.fluent.core ^
  pyfluent_lite_entry.py
