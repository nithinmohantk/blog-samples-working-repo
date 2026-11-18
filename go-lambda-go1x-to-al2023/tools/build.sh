#!/usr/bin/env bash
# Builds the same function the ways a team would on its way from go1.x to provided.al2023.
# Usage: tools/build.sh <dist directory>        (run from the sample root, on Linux x86_64, with Go and gcc)
set -euo pipefail
dist="$1"
rm -rf "$dist" && mkdir -p "$dist"
src="$(pwd)/function"
printf 'variant\tfile\tGOARCH\tCGO\ttags\tbytes\tlinking\tnewest glibc symbol\n' > "$dist/build.tsv"

build() {  # build <variant> <file name> <GOARCH> <CGO_ENABLED> <tags> <extra ldflags>
  local variant=$1 name=$2 arch=$3 cgo=$4 tags=$5 ldflags=$6
  mkdir -p "$dist/$variant"
  (cd "$src" && GOOS=linux GOARCH="$arch" CGO_ENABLED="$cgo" \
     go build -trimpath -tags "$tags" -ldflags "$ldflags" -o "$dist/$variant/$name" .)
  local bin="$dist/$variant/$name" linking glibc
  if file "$bin" | grep -q 'statically linked'; then linking=static; else linking=dynamic; fi
  glibc=$( (objdump -T "$bin" 2>/dev/null || true) | { grep -o 'GLIBC_[0-9.]*' || true; } | sort -uV | tail -1)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$variant" "$name" "$arch" "$cgo" "${tags:--}" \
    "$(stat -c %s "$bin")" "$linking" "${glibc:--}" >> "$dist/build.tsv"
  go version -m "$bin" | { grep -E 'build[[:space:]]+(CGO_ENABLED|-tags|GOARCH|-ldflags)' || true; } | sed "s|^|$variant: |" >> "$dist/buildinfo.txt"
}

# What a go1.x pipeline produced: an executable called main, with the RPC entry point compiled in.
build go1x             main      amd64 0 ""            ""
# The same build renamed: does provided.al2023 accept a binary that still carries the RPC code?
build rpc-bootstrap    bootstrap amd64 0 ""            ""
# The recommended build for provided.al2023: RPC code left out, symbol tables stripped.
build al2023-amd64     bootstrap amd64 0 lambda.norpc  "-s -w"
build al2023-arm64     bootstrap arm64 0 lambda.norpc  "-s -w"
# The two size levers taken one at a time.
build norpc-unstripped bootstrap amd64 0 lambda.norpc  ""
build rpc-stripped     bootstrap amd64 0 ""            "-s -w"
# Built on the CI runner with cgo left on, which is Go's default when a C compiler is present.
build cgo-bootstrap    bootstrap amd64 1 lambda.norpc  "-s -w"
build cgo-main         main      amd64 1 ""            ""
# A norpc build given to the old go1.x runtime.
build norpc-main       main      amd64 0 lambda.norpc  "-s -w"

column -t -s "$(printf '\t')" "$dist/build.tsv"
