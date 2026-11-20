.DEFAULT_GOAL := help

ROOT := $(abspath ../..)
PYTHON ?= $(ROOT)/.venv/bin/python
UV ?= uv
COMPOSE ?= docker compose
DOT ?= dot
GO ?= go
PYCABE_PATH ?= $(ROOT)/../PyCABE
KHALED_SOURCE ?= $(ROOT)/../khaled
# Optionally copy an existing Linux khaled binary instead of building it.
KHALED ?=
CLIENT ?= $(PYTHON) .support/client.py
CABE_PORT ?= 8443
LOCAL_UID := $(shell id -u)
LOCAL_GID := $(shell id -g)
# Keep overrides aligned with the hardcoded globals in script.py.
MQTT_PORT ?= 1883
INPUT_TOPIC ?= pyrophone-example/S/MARBLE
OUTPUT_TOPIC ?= pyrophone-example/C/GESTALT
# Empty selects a random ship from the fixed demo fleet.
MESSAGE ?=
ARGS ?=
# Read lazily so first-time setup does not require an existing password file.
MQTT_PASSWORD = $(file <.password)
MQTT_USERNAME ?= admin
CABE_CERTIFICATE_FILE ?= $(abspath .cabe/client.pem)
CABE_KEY_FILE ?= $(abspath .cabe/client-key.pem)
CABE_CA_FILE ?= $(abspath .cabe/ca.pem)

export CABE_PORT LOCAL_UID LOCAL_GID
export MQTT_PORT INPUT_TOPIC OUTPUT_TOPIC
export MQTT_USERNAME MQTT_PASSWORD
export CABE_CERTIFICATE_FILE CABE_KEY_FILE CABE_CA_FILE
# JSON is data: preserve dollar signs even in command-line MESSAGE overrides.
override export MESSAGE := $(value MESSAGE)

.PHONY: help setup up down run publish subscribe logs tmux credentials graphviz cabe-setup khaled-build

help:
	@printf '%s\n' \
	  'make setup up  Install example dependencies and start Mosquitto and Khaled' \
	  'make run       Run the encrypted MQTT -> decrypt -> Adder -> JQ -> encrypt -> MQTT graph' \
	  '               Pass runtime flags with ARGS=--pp-show-graph or ARGS=--pp-dump-graph' \
	  'make graphviz  Render graph.dot and graph.svg (requires Graphviz)' \
	  'make publish   Encrypt and send sample ship telemetry; override with MESSAGE=...' \
	  'make subscribe Decrypt and watch output in another terminal' \
	  'make credentials Show the MQTT admin username and password' \
	  'make logs      Show broker and key-service logs' \
	  'make down      Stop and remove the demo services' \
	  'make tmux      Launch tmux'

setup:
	$(UV) venv --allow-existing "$(ROOT)/.venv"
	$(UV) pip install --python "$(PYTHON)" -e "$(PYCABE_PATH)" -e "$(ROOT)[mqtt,cabe,jq]"

up: .password cabe-setup .cabe/khaled
	$(COMPOSE) -f .support/compose.yaml up -d --wait --wait-timeout 60

cabe-setup:
	$(PYTHON) .support/setup_cabe.py

.cabe/khaled:
	@mkdir -p .cabe
	@if [ -n "$(KHALED)" ]; then \
	  cp "$(KHALED)" "$@"; \
	else \
	  CGO_ENABLED=0 GOOS=linux GOWORK=off $(GO) -C "$(KHALED_SOURCE)" build -mod=readonly -o "$(abspath $@)" ./cmd/khaled; \
	fi

khaled-build:
	$(MAKE) -B .cabe/khaled

.password:
	@umask 077; $(PYTHON) -c 'import secrets; print(secrets.token_urlsafe(24))' > $@

credentials: .password
	@printf 'Username: admin\nPassword: '; cat .password

down:
	$(COMPOSE) -f .support/compose.yaml down

run:
	$(PYTHON) script.py $(ARGS)

graphviz:
	$(PYTHON) script.py --pp-dump-graph=graphviz > graph.dot
	$(DOT) -Tsvg graph.dot -o graph.svg

publish:
	@$(CLIENT) publish

subscribe:
	@$(CLIENT) subscribe

logs:
	$(COMPOSE) -f .support/compose.yaml logs broker khaled

tmux:
	.support/tmux.sh
