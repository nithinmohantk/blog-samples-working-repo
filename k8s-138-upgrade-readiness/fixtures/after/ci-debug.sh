#!/usr/bin/env bash
# Opens a shell in the first pod of a deployment through the corporate proxy.
set -euo pipefail

pod="$(kubectl get pods -n "$1" -l "app=$2" -o jsonpath='{.items[0].metadata.name}')"
kubectl exec -n "$1" -it "$pod" -- sh
