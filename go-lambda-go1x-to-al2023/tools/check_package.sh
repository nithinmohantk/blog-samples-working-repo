#!/usr/bin/env bash
# Fails the pipeline if a Lambda package will not start on provided.al2023, before anything is deployed.
# Usage: tools/check_package.sh <package.zip> <x86_64|arm64>
set -euo pipefail
zip="$1" want_arch="$2"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
unzip -q "$zip" -d "$work"
problems=0
fail() { echo "FAIL $zip: $*"; problems=$((problems + 1)); }

bin="$work/bootstrap"
if [ ! -f "$bin" ]; then
  fail "no file named bootstrap at the root of the zip (found: $(cd "$work" && ls | tr '\n' ' '))"
  exit 1
fi
[ -x "$bin" ] || fail "bootstrap is not executable (zip lost the mode bits)"

info="$(go version -m "$bin" 2>/dev/null)" || { fail "bootstrap is not a Go executable"; exit 1; }
setting() { awk -v k="$1" '$1=="build" && index($2, k"=")==1 {sub(k"=", "", $2); print $2}' <<< "$info"; }

[ "$(setting GOOS)" = linux ] || fail "GOOS is $(setting GOOS), not linux"
case "$want_arch:$(setting GOARCH)" in
  x86_64:amd64|arm64:arm64) ;;
  *) fail "GOARCH $(setting GOARCH) does not match the function architecture $want_arch" ;;
esac
[ "$(setting CGO_ENABLED)" = 0 ] || fail "built with CGO_ENABLED=$(setting CGO_ENABLED); the binary depends on the build machine's glibc"
case ",$(setting -tags)," in
  *,lambda.norpc,*) ;;
  *) echo "WARN $zip: built without -tags lambda.norpc (works, but carries the unused RPC code)" ;;
esac

[ "$problems" -eq 0 ] && echo "OK   $zip: bootstrap, linux/$(setting GOARCH), static"
exit $(( problems > 0 ))
