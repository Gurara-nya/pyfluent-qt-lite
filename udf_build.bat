@echo off
setlocal
cd /d "%~dp0"
python -m pyfluent_qt_lite.udf.cli %*
