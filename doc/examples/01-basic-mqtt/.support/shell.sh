#!/bin/bash
# Sourced by each interactive demo shell, including new tmux panes/windows.
export PS1='$ '
pyrophone_demo_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MQTT_PASSWORD=$(cat -- "$pyrophone_demo_dir/.password")
export MQTT_PASSWORD
export MQTT_USERNAME=admin
export CABE_CERTIFICATE_FILE="$pyrophone_demo_dir/.cabe/client.pem"
export CABE_KEY_FILE="$pyrophone_demo_dir/.cabe/client-key.pem"
export CABE_CA_FILE="$pyrophone_demo_dir/.cabe/ca.pem"
unset pyrophone_demo_dir
alias subscribe='make subscribe'
alias publish='make publish'
