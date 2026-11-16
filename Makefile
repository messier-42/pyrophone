UV ?= uv
PYCABE_PATH ?= ../PyCABE

-include Makefile.config

.PHONY: build venv dev dev-cabe test lint typecheck check clean nix-shell

build:
	$(UV) build

venv:
	$(UV) venv --allow-existing .venv

dev: venv
	$(UV) pip install --python .venv/bin/python --group dev -e .

dev-cabe: venv
	$(UV) pip install --python .venv/bin/python --group dev -e "$(PYCABE_PATH)" -e '.[cabe]'

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/ruff check src tests
	.venv/bin/ruff format --check src tests

typecheck:
	.venv/bin/python -m mypy

check: test lint typecheck

clean:
	rm -rf dist .venv .*_cache uv.lock
	find . -iname __pycache__ | xargs rm -rf

nix-shell:
	nix-shell
