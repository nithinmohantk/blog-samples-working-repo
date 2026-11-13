"""Applies each configuration with Terraform and with OpenTofu against a local Secrets Manager emulator,
then looks for the secret in everything the tool wrote to disk.

    python run_experiments.py <terraform binary> <tofu binary> <output dir> [endpoint]

The emulator is moto. Nothing here calls AWS. The access keys are throwaway values that moto ignores.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import boto3

here = pathlib.Path(__file__).resolve().parent
terraform, tofu, out = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
endpoint = sys.argv[4] if len(sys.argv) > 4 else "http://127.0.0.1:5000"
out.mkdir(parents=True, exist_ok=True)
ENV = {
    **os.environ, "AWS_ENDPOINT_URL": endpoint, "AWS_REGION": "eu-west-1", "AWS_DEFAULT_REGION": "eu-west-1",
    "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",  # throwaway; the emulator ignores them
    "AWS_EC2_METADATA_DISABLED": "true", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "CHECKPOINT_DISABLE": "1",
}
secrets = boto3.client("secretsmanager", endpoint_url=endpoint, region_name="eu-west-1", aws_access_key_id="testing", aws_secret_access_key="testing")
KNOWN_TOKEN = "tok-synthetic-7f3a9c2e51b84d06"
# Recorded from the pinned versions: the two tools differ here.
NULL_IN_MOCKED_PLAN = {"terraform": "yes", "opentofu": "no"}
rows: list[dict] = []
unexpected = 0


def run(tool: str, cwd: pathlib.Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([tool, *args, "-no-color"], cwd=cwd, env={**ENV, **(env or {})}, capture_output=True, text=True, timeout=240)


def must(result: subprocess.CompletedProcess, what: str) -> subprocess.CompletedProcess:
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed:\n{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
    return result


def workdir(source: str) -> pathlib.Path:
    target = pathlib.Path(tempfile.mkdtemp(prefix=f"{source}-"))
    shutil.copytree(here / source, target, dirs_exist_ok=True)
    return target


def stored(name: str) -> str:
    return secrets.get_secret_value(SecretId=name)["SecretString"]


def on_disk(cwd: pathlib.Path, needle: str) -> list[str]:
    """Every file under the working directory, provider binaries excluded, that contains the secret."""
    found = []
    for path in sorted(cwd.rglob("*")):
        if path.is_file() and "providers" not in path.parts:
            if needle.encode() in path.read_bytes():
                found.append(str(path.relative_to(cwd)))
    return found


def record(tool_name: str, experiment: str, observation: str, expected: str, detail: str = "") -> None:
    global unexpected
    ok = observation == expected
    unexpected += not ok
    rows.append({"tool": tool_name, "experiment": experiment, "observed": observation, "expected": expected, "detail": detail})
    print(f"{'ok  ' if ok else 'DIFF'}  {tool_name:9}  {experiment:58}  {observation}" + (f"  (expected {expected})" if not ok else "") + (f"  [{detail}]" if detail else ""))


def plan_json(tool: str, cwd: pathlib.Path, *args: str, env: dict | None = None) -> str:
    must(run(tool, cwd, "plan", "-out=tfplan", *args, env=env), "plan")
    return must(run(tool, cwd, "show", "-json", "tfplan"), "show").stdout


for tool, label in ((terraform, "terraform"), (tofu, "opentofu")):
    version = run(tool, here, "version").stdout.splitlines()[0]
    print(f"\n== {version}")
    try:
        # 1. Classic: managed random_password into secret_string.
        name = f"sample/{label}/classic"
        cwd = workdir("classic")
        must(run(tool, cwd, "init"), "init")
        must(run(tool, cwd, "apply", "-auto-approve", f"-var=name={name}"), "apply")
        secret = stored(name)
        state = (cwd / "terraform.tfstate").read_text()
        record(label, "classic: password in the state file", f"{state.count(secret)} times", "2 times")
        record(label, "classic: password in the JSON of the next plan", "present" if secret in plan_json(tool, cwd, f"-var=name={name}") else "absent", "present")

        # 2. Migrating that same secret to a write-only argument.
        (cwd / "main.tf").write_text((here / "migrate" / "after.tf").read_text())
        migrate_plan = must(run(tool, cwd, "plan", f"-var=name={name}"), "plan").stdout
        summary = next((line.strip() for line in migrate_plan.splitlines() if line.startswith("Plan:")), "no changes")
        must(run(tool, cwd, "apply", "-auto-approve", f"-var=name={name}"), "apply")
        record(label, "migrate: old password in the new state file", "present" if secret in (cwd / "terraform.tfstate").read_text() else "absent", "absent", summary)
        backup = cwd / "terraform.tfstate.backup"
        record(label, "migrate: old password in the state backup", "present" if backup.exists() and secret in backup.read_text() else "absent", "present")
        record(label, "migrate: the stored secret was replaced by a new one", "yes" if stored(name) != secret else "no", "yes")

        # 3. Ephemeral password into a write-only argument.
        name = f"sample/{label}/ephemeral"
        cwd = workdir("ephemeral")
        must(run(tool, cwd, "init"), "init")
        first_plan = plan_json(tool, cwd, f"-var=name={name}")
        must(run(tool, cwd, "apply", "-auto-approve", f"-var=name={name}"), "apply")
        secret = stored(name)
        record(label, "ephemeral: a 32-character password reached the store", "yes" if len(secret) == 32 else "no", "yes")
        record(label, "ephemeral: password anywhere on disk after apply", ", ".join(on_disk(cwd, secret)) or "nowhere", "nowhere")
        record(label, "ephemeral: password in the JSON of the next plan", "present" if secret in plan_json(tool, cwd, f"-var=name={name}") else "absent", "absent")
        state = json.loads((cwd / "terraform.tfstate").read_text())
        version_row = next(r for r in state["resources"] if r["type"] == "aws_secretsmanager_secret_version")["instances"][0]["attributes"]
        record(label, "ephemeral: what the state holds for the write-only pair", f"value {json.dumps(version_row.get('secret_string_wo'))}, version {version_row.get('secret_string_wo_version')}", "value null, version 1")
        record(label, "ephemeral: ephemeral resource has an entry in state", "yes" if any(r.get("mode") == "ephemeral" or r["type"] == "random_password" for r in state["resources"]) else "no", "no")

        # 4. Rotation is driven by the version number and by nothing else.
        again = run(tool, cwd, "plan", "-detailed-exitcode", f"-var=name={name}")
        record(label, "rotate: a second plan with the same version", {0: "no changes", 2: "changes"}.get(again.returncode, f"error {again.returncode}"), "no changes")
        must(run(tool, cwd, "apply", "-auto-approve", f"-var=name={name}"), "apply")
        record(label, "rotate: stored password after re-applying the same version", "unchanged" if stored(name) == secret else "changed", "unchanged")
        bump = must(run(tool, cwd, "plan", f"-var=name={name}", "-var=password_version=2"), "plan").stdout
        record(label, "rotate: what the plan for version 2 proposes", next((line.strip() for line in bump.splitlines() if line.startswith("Plan:")), "no changes"), "Plan: 1 to add, 0 to change, 1 to destroy.")
        record(label, "rotate: the plan output names the write-only value", "yes" if "secret_string_wo " in bump and "write-only" not in bump.lower() else "no", "no")
        must(run(tool, cwd, "apply", "-auto-approve", f"-var=name={name}", "-var=password_version=2"), "apply")
        rotated = stored(name)
        record(label, "rotate: stored password after version 2", "changed" if rotated != secret else "unchanged", "changed")
        record(label, "rotate: either password anywhere on disk", ", ".join(on_disk(cwd, secret) + on_disk(cwd, rotated)) or "nowhere", "nowhere")

        # 5. A known secret through an ephemeral variable.
        name = f"sample/{label}/variable"
        cwd = workdir("variable")
        must(run(tool, cwd, "init"), "init")
        token_env = {"TF_VAR_api_token": KNOWN_TOKEN}
        record(label, "variable: token in the JSON of the saved plan", "present" if KNOWN_TOKEN in plan_json(tool, cwd, f"-var=name={name}", env=token_env) else "absent", "absent")
        record(label, "variable: token in the saved plan file", "present" if on_disk(cwd, KNOWN_TOKEN) else "absent", "absent")
        without = run(tool, cwd, "apply", "-auto-approve", "tfplan")
        message = next((line.strip() for line in without.stderr.splitlines() if line.startswith("Error:")), "")
        record(label, "variable: applying the saved plan without the token", "applies" if without.returncode == 0 else "refused", "refused", message[:140])
        saved = run(tool, cwd, "apply", "-auto-approve", "tfplan", env=token_env)
        record(label, "variable: applying the saved plan with the token supplied again", "applies" if saved.returncode == 0 else "refused", "applies", (saved.stderr.strip().splitlines() or [""])[0][:140])
        record(label, "variable: token reached the store", "yes" if stored(name) == KNOWN_TOKEN else "no", "yes")
        record(label, "variable: token anywhere on disk after apply", ", ".join(on_disk(cwd, KNOWN_TOKEN)) or "nowhere", "nowhere")

        # 6. Misuse is refused.
        cwd = workdir("misuse")
        must(run(tool, cwd, "init"), "init")
        refused = run(tool, cwd, "validate")
        message = next((line.strip() for line in refused.stderr.splitlines() if line.startswith("Error:")), "")
        record(label, "misuse: ephemeral value in an ordinary output", "refused" if refused.returncode != 0 else "accepted", "refused", message[:140])

        # 7. The module's tests.
        cwd = workdir("ephemeral")
        must(run(tool, cwd, "init"), "init")
        tested = run(tool, cwd, "test")
        last = (tested.stdout.strip().splitlines() or ["no output"])[-1]
        record(label, "test: module tests against a mocked AWS provider", "passes" if tested.returncode == 0 else "fails", "passes", last[:140])
        (out / f"test-{label}.txt").write_text(tested.stdout + tested.stderr)
        shutil.rmtree(cwd / "tests")
        (cwd / "tests").mkdir()
        shutil.copy(here / "probe" / "null_readback.tftest.hcl", cwd / "tests")
        probe = run(tool, cwd, "test")
        record(label, "probe: write-only value reads as null in a mocked plan", "yes" if probe.returncode == 0 else "no", NULL_IN_MOCKED_PLAN[label])
        (out / f"probe-{label}.txt").write_text(probe.stdout + probe.stderr)
    except Exception as error:  # an experiment that cannot run is a result, and the remaining tool still runs
        record(label, "run aborted", "error", "completed", str(error).strip().splitlines()[-1][:300])
        (out / f"error-{label}.txt").write_text(str(error))

(out / "experiments.json").write_text(json.dumps(rows, indent=2) + "\n")
print(f"\n{len(rows) - unexpected} of {len(rows)} observations match what was expected")
sys.exit(1 if unexpected else 0)
