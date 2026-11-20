#!/usr/bin/env bash
# Deletes the resource group created by setup.sh and purges the soft-deleted
# Foundry account so nothing keeps billing and the name is released.
set -euo pipefail
set -a; . ./.env; set +a
LOCATION="${LOCATION:-swedencentral}"
az group delete -n "$RG" --yes
az cognitiveservices account purge -n "$ACCOUNT" -g "$RG" -l "$LOCATION" || true
az group exists -n "$RG"
