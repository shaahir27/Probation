@echo off
rem make.cmd - Windows wrapper for Probation development targets

set TARGET=%1
if "%TARGET%"=="" set TARGET=help

set PYTHONPATH=%~dp0backend\src;%PYTHONPATH%

if exist "%~dp0.venv311\Scripts\python.exe" (
    set PYTHON="%~dp0.venv311\Scripts\python.exe"
    set PYTEST="%~dp0.venv311\Scripts\pytest.exe"
    set RUFF="%~dp0.venv311\Scripts\ruff.exe"
    set MYPY="%~dp0.venv311\Scripts\mypy.exe"
    set UVICORN="%~dp0.venv311\Scripts\uvicorn.exe"
) else (
    set PYTHON=python
    set PYTEST=pytest
    set RUFF=ruff
    set MYPY=mypy
    set UVICORN=uvicorn
)

if "%TARGET%"=="help" (
    echo Probation - Development Commands ^(Windows^)
    echo   make.cmd setup                Install dependencies
    echo   make.cmd check                Run ruff, mypy, and pytest
    echo   make.cmd test                 Run tests with coverage
    echo   make.cmd synth [PERSONA] [SEED] Generate synthetic persona
    echo   make.cmd backtest [FAMILY]    Run replay backtest
    echo   make.cmd serve                Run backend server
    echo   make.cmd web                  Run frontend dev server
    echo   make.cmd eval [SUITE]         Run eval suite
    echo   make.cmd ledger-verify        Verify ledger hash chain
    echo   make.cmd budget               Show LLM budget and spend
    exit /b 0
)

if "%TARGET%"=="setup" (
    %PYTHON% -m pip install -e ./backend[dev]
    cd frontend && npm install && cd ..
    %PYTHON% -m probation.cli db init
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="check" (
    echo Running ruff check...
    %RUFF% check backend || exit /b 1
    echo Running ruff format check...
    %RUFF% format --check backend || exit /b 1
    echo Running mypy...
    %MYPY% --config-file backend/pyproject.toml backend/src/probation || exit /b 1
    echo Running pytest...
    %PYTEST% -q backend/tests -m "not live" || exit /b 1
    echo All checks passed!
    exit /b 0
)

if "%TARGET%"=="test" (
    %PYTEST% -q backend/tests --cov=probation --cov-report=term-missing
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="serve" (
    %UVICORN% probation.api.app:app --app-dir "%~dp0backend\src" --host 0.0.0.0 --port 8000 --reload
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="web" (
    cd frontend && npm run dev
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="ledger-verify" (
    %PYTHON% -m probation.cli ledger verify
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="budget" (
    %PYTHON% -m probation.cli budget show
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="synth" goto :synth
if "%TARGET%"=="backtest" goto :backtest
if "%TARGET%"=="eval" goto :eval

echo Unknown target: %TARGET%
exit /b 1

:synth
set P=%2
if "%P%"=="" set P=1
set S=%3
if "%S%"=="" set S=1
%PYTHON% -m probation.cli synth generate --persona %P% --seed %S%
exit /b %ERRORLEVEL%

:backtest
set F=%2
if "%F%"=="" set F=email_action
%PYTHON% -m probation.cli backtest --family %F%
exit /b %ERRORLEVEL%

:eval
set S=%2
if "%S%"=="" set S=main
%PYTHON% -m probation.cli eval --suite %S%
exit /b %ERRORLEVEL%

