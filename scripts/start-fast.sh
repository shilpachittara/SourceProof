#!/usr/bin/env bash
export SOURCEPROOF_COMPOSE_FILE=docker-compose.fast.yml
exec "$(dirname "$0")/start.sh"
