#!/bin/sh
# Open three shell panes in the caller's current directory.
set -eu

support_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYROPHONE_NIX_SHELL="$support_dir/../../../shell.nix"
export PYROPHONE_SHELL_INIT="$support_dir/shell.sh"

# Source the demo's shell settings instead of the user's Bash startup files.
shell_command="nix-shell \"\$PYROPHONE_NIX_SHELL\" --run 'exec bash --noprofile --rcfile \"\$PYROPHONE_SHELL_INIT\" -i'"
session=$(tmux new-session -d -P -F '#{session_id}' -c "$PWD" \
    -e "PYROPHONE_NIX_SHELL=$PYROPHONE_NIX_SHELL" -e "PATH=$PATH" \
    -e "PYROPHONE_SHELL_INIT=$PYROPHONE_SHELL_INIT" "$shell_command")
tmux set-option -t "$session" default-command "$shell_command"
top_pane=$(tmux display-message -p -t "$session:" '#{pane_id}')
bottom_pane=$(tmux split-window -v -l 100% -t "$top_pane" -c "$PWD" -P -F '#{pane_id}')
tmux split-window -h -l 66% -t "$top_pane" -c "$PWD"
tmux select-pane -t "$bottom_pane"

if [ -n "${TMUX:-}" ]; then
    exec tmux switch-client -t "$session"
fi
exec tmux attach-session -t "$session"
