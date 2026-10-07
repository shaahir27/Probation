@echo off
rem make.cmd - Windows wrapper for Probation development targets

set TARGET=%1
if "%TARGET%"=="" set TARGET=help

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
    pip install -e ./backend
    cd frontend && npm install && cd ..
    python -m probation.cli db init
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="check" (
    echo Running ruff check...
    ruff check backend || exit /b 1
    echo Running ruff format check...
    ruff format --check backend || exit /b 1
    echo Running mypy...
    mypy --config-file backend/pyproject.toml backend/src/probation || exit /b 1
    echo Running pytest...
    pytest -q backend/tests -m "not live" || exit /b 1
    echo All checks passed!
    exit /b 0
)

if "%TARGET%"=="test" (
    pytest -q backend/tests --cov=probation --cov-report=term-missing
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="serve" (
    uvicorn probation.api.app:app --host 0.0.0.0 --port 8000 --reload
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="web" (
    cd frontend && npm run dev
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="ledger-verify" (
    python -m probation.cli ledger verify
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="budget" (
    python -m probation.cli budget show
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="synth" (
    set P=%2
    if "%P%"=="" set P=1
    set S=%3
    if "%S%"=="" set S=1
    python -m probation.cli synth generate --persona %P% --seed %S%
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="backtest" (
    set F=%2
    if "%F%"=="" set F=email_action
    python -m probation.cli backtest --family %F%
    exit /b %ERRORLEVEL%
)

if "%TARGET%"=="eval" (
    set S=%2
    if "%S%"=="" set S=main
    python -m probation.cli eval --suite %S%
    exit /b %ERRORLEVEL%
)

echo Unknown target: %TARGET%
exit /b 1
