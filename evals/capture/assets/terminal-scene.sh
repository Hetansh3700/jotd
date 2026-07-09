#!/bin/bash
# Prints a fixed block to fill a terminal for the terminal-output scene.
# Includes a password-bullet line: a redacting capture client must drop that
# LINE (the scene forbids the bullets) while keeping the neighbors.
cat << 'EOF'
$ vault-smoke --run
auth ok    Password ••••••••••
scenario   search_burst ramping-vus
requests   4821 of 4821 completed
latency    p99 within budget
all checks passed
vault smoke scenario complete
EOF
