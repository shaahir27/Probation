# Makefile for Probation
# Authority: docs/TECH_STACK_AND_REPO.md section 3

SHELL := /bin/bash
PYTHON := python
PIP := pip
NPM := npm

.PHONY: help setup check test synth backtest serve web eval ledger-verify budget clean gmail-live

help:
	@echo "Probation - Development Commands"
	@echo "  make setup                Create venv, install deps, initialize schema"
	@echo "  make check                Run ruff lint, format check, mypy, and tests"
	@echo "  make test                 Run tests with coverage"
	@echo "  make synth PERSONA=1      Generate synthetic persona"
	@echo "  make backtest FAMILY=...  Run backtest replay for family"
	@echo "  make serve                Run FastAPI backend"
	@echo "  make web                  Run Vite frontend dev server"
	@echo "  make eval SUITE=main      Run evaluation suite"
	@echo "  make ledger-verify        Verify ledger hash chain"
	@echo "  make budget               Show LLM budget and spend"
	@echo "  make gmail-live           Run live-gated Gmail connector tests"

setup:
	$(PIP) install -e ./backend
	cd frontend && $(NPM) install
	$(PYTHON) -m probation.cli db init

check:
	$(PYTHON) scripts/check.py

test:
	$(PYTHON) scripts/check.py --tests-only --coverage

synth:
	$(PYTHON) -m probation.cli synth generate --persona-id $(or $(PERSONA),1) --seed $(or $(SEED),1) --out data/synth/$(or $(PERSONA),1)

backtest:
	$(PYTHON) -m probation.cli backtest --family $(or $(FAMILY),email_action)

serve:
	$(PYTHON) -m probation.cli serve --reload

web:
	cd frontend && $(NPM) run dev

eval:
	$(PYTHON) -m probation.cli eval run --suite $(or $(SUITE),main)

ledger-verify:
	$(PYTHON) -m probation.cli ledger verify

budget:
	$(PYTHON) -m probation.cli budget show

gmail-live:
	$(PYTHON) -m pytest -m live backend/tests/connectors

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache backend/.pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
