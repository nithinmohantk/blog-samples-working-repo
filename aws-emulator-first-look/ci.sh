#!/usr/bin/env bash
# Installs AWS Emulator from AWS's Debian package, checks its signature, and runs the lab.
# Usage: ./ci.sh <output directory>     (Debian or Ubuntu on x86_64, with sudo, Python 3 and the AWS CLI)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
BASE="https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest"
EXPECTED_FINGERPRINT="98BCF336A3BE53B734E967C52E5BF49BD940F624"
work="$(mktemp -d)"
log() { printf '\n$ %s\n' "$*"; }
# The emulator's per-run keys are throwaway, but a transcript is no place for any key.
mask() { sed -E 's/(AKIA|ASIA)[A-Z0-9]{12,}/\1************/g; s/(aws_secret_access_key *= *).*/\1****/I'; }

{
  echo "== 1. download and verify"
  log "curl -fsSLO $BASE/aws-emulator_amd64.deb (and .sig)"
  curl -fsSLo "$work/aws-emulator.deb" "$BASE/aws-emulator_amd64.deb" && curl -fsSLo "$work/aws-emulator.deb.sig" "$BASE/aws-emulator_amd64.deb.sig" || exit 2
  ls -l "$work" | awk 'NR>1 {printf "%s  %s bytes\n", $9, $5}'
  sha256sum "$work/aws-emulator.deb" | sed "s|$work/||"
  curl -fsSLo "$work/aws-publishing.asc" https://downloads.aws.com/keys/gpg/current.asc
  export GNUPGHOME="$work/gnupg"; mkdir -m 700 "$GNUPGHOME"
  gpg --quiet --import "$work/aws-publishing.asc" 2>&1 | tail -n 2
  actual="$(gpg --with-colons --fingerprint ssm-publishing@amazon.com | awk -F: '/^fpr/ {print $10; exit}')"
  log "gpg --fingerprint ssm-publishing@amazon.com"
  echo "fingerprint $actual"; [ "$actual" = "$EXPECTED_FINGERPRINT" ] && echo "matches the fingerprint in the user guide" || { echo "FINGERPRINT MISMATCH"; exit 2; }
  log "gpg --verify aws-emulator.deb.sig aws-emulator.deb"
  gpg --verify "$work/aws-emulator.deb.sig" "$work/aws-emulator.deb" 2>&1 | grep -E "Good signature|BAD signature|using" || exit 2

  echo; echo "== 2. install"
  log "sudo apt-get install -y ./aws-emulator.deb"
  sudo apt-get install -y "$work/aws-emulator.deb" 2>&1 | tail -n 4
  dpkg-query -W -f='package ${Package} ${Version}\n' aws-emulator
  ls -l "$(readlink -f "$(command -v aws-emulator)")" | awk '{printf "binary %s, %.0f MiB\n", $9, $5/1048576}'
  log "aws-emulator -v"; aws-emulator -v
  log "aws-emulator --help"; aws-emulator --help 2>&1 | head -n 40
} 2>&1 | tee "$out/01-install.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || exit 2

start() { # port
  local began; began="$(date +%s.%N)"
  aws-emulator -p "$1" --telemetry off > "$out/emulator-$1.log" 2>&1 &
  echo $! > "$work/pid-$1"
  for i in $(seq 1 200); do
    curl -fsS --cacert "$HOME/.aws/emulator/$1/ca.pem" "https://127.0.0.1:$1/__admin/health" > /dev/null 2>&1 && break; sleep 0.05
  done
  printf 'port %s healthy after %.2f s\n' "$1" "$(echo "$(date +%s.%N) - $began" | bc)"
}
rss() { awk '/VmRSS/ {printf "%.0f MiB resident\n", $2/1024}' "/proc/$(cat "$work/pid-$1")/status"; }
use() { export AWS_ENDPOINT_URL="https://127.0.0.1:$1" AWS_SHARED_CREDENTIALS_FILE="$HOME/.aws/emulator/$1/emulator_credentials" AWS_CONFIG_FILE="$HOME/.aws/emulator/$1/config" \
        AWS_CA_BUNDLE="$HOME/.aws/emulator/$1/ca.pem" AWS_EC2_METADATA_DISABLED=true AWS_DISABLE_HOST_PREFIX_INJECTION=true AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
        unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE; }

{
  echo "== 3. start"
  log "aws-emulator -p 9297 --telemetry off &"
  start 9297; sleep 0.5; mask < "$out/emulator-9297.log" | head -n 20
  log "ls -l ~/.aws/emulator/9297/"; ls -l "$HOME/.aws/emulator/9297/" | awk 'NR>1 {print $1, $5, $9}'
  log "curl --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health"; curl -sS --cacert "$HOME/.aws/emulator/9297/ca.pem" https://127.0.0.1:9297/__admin/health; echo
  rss 9297
  use 9297
  log "aws sts get-caller-identity"; aws sts get-caller-identity
  log "aws s3api create-bucket --bucket first-light"; aws s3api create-bucket --bucket first-light
  log "aws s3api list-buckets --query 'Buckets[].Name'"; aws s3api list-buckets --query 'Buckets[].Name'
  log "aws dynamodb create-table --table-name ab ...   (a name that is too short)"
  aws dynamodb create-table --table-name ab --billing-mode PAY_PER_REQUEST --attribute-definitions AttributeName=id,AttributeType=S --key-schema AttributeName=id,KeyType=HASH 2>&1 | tail -n 3
} 2>&1 | mask | tee "$out/02-start.txt"

python -m pip install --quiet boto3 "moto[server]" 2>&1 | tail -n 1
{ aws-emulator -v; aws --version; python --version; python -c "import boto3, moto; print('boto3', boto3.__version__, 'moto', moto.__version__)"; uname -srm; nproc | sed 's/$/ vCPU/'; } 2>&1 | tee "$out/versions.txt"

echo "== 4. the tour, against the emulator"
python -u lab/tour.py emulator:9297 "$out/tour-emulator.json" 2>&1 | mask | tee "$out/03-tour-emulator.txt"
{ echo "after the tour:"; rss 9297; } | tee -a "$out/03-tour-emulator.txt"

echo "== 5. the same tour, against moto"
moto_server -H 127.0.0.1 -p 5000 > "$out/moto.log" 2>&1 & moto=$!
for i in $(seq 1 40); do curl -fsS http://127.0.0.1:5000/moto-api/ > /dev/null 2>&1 && break; sleep 0.25; done
python -u lab/tour.py moto:5000 "$out/tour-moto.json" 2>&1 | tee "$out/04-tour-moto.txt"

echo "== 6. the loop, timed"
python -u lab/bench.py emulator:9297 "$out/bench-emulator.json" 2>&1 | tee "$out/05-bench.txt"
python -u lab/bench.py moto:5000 "$out/bench-moto.json" 2>&1 | tee -a "$out/05-bench.txt"
kill $moto 2>/dev/null

echo "== 7. reach: one question to every service boto3 knows"
python -u lab/coverage.py emulator:9297 "$out/coverage.json" 2>&1 | tee "$out/06-coverage.txt"
{ echo "after the survey:"; rss 9297; } | tee -a "$out/06-coverage.txt"

{
  echo "== 8. two emulators, and a restart"
  log "aws-emulator -p 9298 --telemetry off &"; start 9298
  log "python lab/instances.py isolation 9297 9298"; python lab/instances.py isolation 9297 9298
  log "kill -TERM <pid of 9297>; ls ~/.aws/emulator/*/"
  kill -TERM "$(cat "$work/pid-9297")"; sleep 2; for d in "$HOME"/.aws/emulator/*/; do printf '%s: %s file(s)\n' "$(basename "$d")" "$(ls -A "$d" | wc -l)"; done
  log "aws-emulator -p 9297 --telemetry off &"; start 9297
  log "python lab/instances.py count 9297"; python lab/instances.py count 9297
} 2>&1 | mask | tee "$out/07-instances.txt"

{
  echo "== 9. terraform against the emulator"
  tf="$work/tf"; mkdir -p "$tf"
  curl -fsSL -o "$work/terraform.zip" https://releases.hashicorp.com/terraform/1.16.5/terraform_1.16.5_linux_amd64.zip && unzip -q -o "$work/terraform.zip" -d "$work/tfbin"
  cp ../terraform-secrets-out-of-state/ephemeral/main.tf "$tf/main.tf"
  printf 'terraform {\n  required_providers {\n    aws    = { source = "hashicorp/aws" }\n    random = { source = "hashicorp/random" }\n  }\n}\n\nprovider "aws" {}\n' > "$tf/versions.tf"
  use 9297
  ( cd "$tf" && export TF_IN_AUTOMATION=1 TF_INPUT=0 CHECKPOINT_DISABLE=1
    "$work/tfbin/terraform" version | head -n 1
    log "terraform init"; "$work/tfbin/terraform" init -no-color 2>&1 | grep -E "Installing|Installed|successfully|Error" | head -n 8
    log "terraform apply -auto-approve -var name=lab/terraform"; "$work/tfbin/terraform" apply -auto-approve -no-color -var name=lab/terraform 2>&1 | tail -n 14
    log "aws secretsmanager get-secret-value --secret-id lab/terraform --query 'length(SecretString)'"
    aws secretsmanager get-secret-value --secret-id lab/terraform --query 'length(SecretString)' 2>&1 | tail -n 3
    log "terraform destroy -auto-approve"; "$work/tfbin/terraform" destroy -auto-approve -no-color -var name=lab/terraform 2>&1 | tail -n 3 )
} 2>&1 | mask | tee "$out/08-terraform.txt"

{
  echo "== 10. published fidelity scores"
  python -u lab/scores.py "$out"
} 2>&1 | tee "$out/09-fidelity.txt"

for port in 9297 9298; do kill -TERM "$(cat "$work/pid-$port")" 2>/dev/null; done
grep -l "AKIA\|ASIA" "$out"/*.txt "$out"/*.log 2>/dev/null | sed 's/^/unmasked key id left in: /'
rm -f "$out"/emulator-*.log.raw
for f in "$out"/emulator-*.log; do mask < "$f" > "$f.m" && mv "$f.m" "$f"; done
exit 0
