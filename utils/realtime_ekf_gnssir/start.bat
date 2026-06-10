@echo off
setlocal
python "%~dp0run.py" --config "%~dp0config\app.yaml" %*
