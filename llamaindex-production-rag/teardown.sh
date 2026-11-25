#!/usr/bin/env bash
# Delete the resource group and purge the soft-deleted Azure OpenAI account.
set -euo pipefail
set -a; . ./.env; set +a
az group delete -n "$RG" --yes
az cognitiveservices account purge -n "$ACCOUNT" -g "$RG" -l "$LOCATION" || true
az group exists -n "$RG"
