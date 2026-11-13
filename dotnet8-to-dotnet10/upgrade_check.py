"""Runs the same code three ways and reports what differs.

    python upgrade_check.py <dotnet 8 SDK root> <dotnet 10 SDK root> <output dir> [recorded.json]

  A  .NET 8 SDK, target net8.0     where the service is today
  B  .NET 10 SDK, target net8.0    step one: new SDK, same runtime
  C  .NET 10 SDK, target net10.0   step two: new target

If a recorded.json is given, the run fails when any observation differs from it.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

here = pathlib.Path(__file__).resolve().parent
sdk8, sdk10, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
recorded_path = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
out.mkdir(parents=True, exist_ok=True)
LEGS = {"A": (sdk8, "net8.0"), "B": (sdk10, "net8.0"), "C": (sdk10, "net10.0")}
DIAGNOSTIC = re.compile(r"\b(warning|error) ([A-Z]+\d+)\b")


def dotnet(root: pathlib.Path, cwd: pathlib.Path, *args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOTNET_ROOT": str(root), "PATH": f"{root}:{os.environ['PATH']}", "DOTNET_MULTILEVEL_LOOKUP": "0",
           "DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_gcServer": "", "NO_COLOR": "1"}
    env.pop("DOTNET_gcServer")
    return subprocess.run([str(root / "dotnet"), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def copy(source: pathlib.Path) -> pathlib.Path:
    target = pathlib.Path(tempfile.mkdtemp(prefix=source.name + "-")) / source.name
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("bin", "obj"))
    return target


results: dict[str, dict[str, str]] = {}


def put(name: str, leg: str, value: str) -> None:
    results.setdefault(name, {})[leg] = value


for leg, (root, framework) in LEGS.items():
    version = dotnet(root, here, "--version").stdout.strip()
    put("_sdk", leg, version)
    print(f"\n== leg {leg}: SDK {version}, {framework}", flush=True)

    # Runtime behaviour.
    project = copy(here / "src" / "Probes")
    build = dotnet(root, project, "build", "-c", "Release", f"-p:TargetFrameworks={framework}", "-tl:off", "-clp:NoSummary")
    (out / f"probes-build-{leg}.txt").write_text(build.stdout + build.stderr)
    if build.returncode != 0:
        put("_probes", leg, "build failed")
        print(build.stdout[-2000:])
    else:
        run = dotnet(root, project, "bin/Release/" + framework + "/Probes.dll", timeout=300)
        (out / f"probes-run-{leg}.txt").write_text(run.stdout + run.stderr)
        try:
            for name, value in json.loads(run.stdout[run.stdout.index("{"):]).items():
                put(name, leg, value)
        except ValueError:
            put("_probes", leg, f"run failed with exit code {run.returncode}")
            print(run.stdout[-1500:], run.stderr[-1500:])

    # What the compiler and restore say about ordinary older code.
    for sample in sorted(p for p in (here / "compile").iterdir() if p.is_dir()):
        project = copy(sample)
        build = dotnet(root, project, "build", "-c", "Release", f"-p:TargetFrameworks={framework}", "-tl:off", "-clp:NoSummary")
        (out / f"compile-{sample.name}-{leg}.txt").write_text(build.stdout + build.stderr)
        found = sorted({f"{kind} {code}" for kind, code in DIAGNOSTIC.findall(build.stdout + build.stderr)})
        value = ("builds" if build.returncode == 0 else "fails") + (": " + ", ".join(found) if found else " clean")
        if build.returncode == 0 and sample.name == "ArrayReverse":
            run = dotnet(root, project, f"bin/Release/{framework}/ArrayReverse.dll", timeout=60)
            value += f"; prints {run.stdout.strip()}"
        put(f"compile.{sample.name}", leg, value)

    # SDK behaviour that is independent of the project.
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="sln-"))
    dotnet(root, scratch, "new", "sln", "-n", "App")
    put("sdk.dotnet_new_sln_creates", leg, ", ".join(sorted(p.name for p in scratch.iterdir())) or "nothing")

legs = list(LEGS)
width = max(len(n) for n in results)
changed = 0
for name in sorted(results):
    row = results[name]
    differs = len({row.get(leg) for leg in legs}) > 1 and not name.startswith("_")
    changed += differs
    print(f"{'DIFF' if differs else 'same'}  {name:{width}}  " + "  |  ".join(f"{leg}: {row.get(leg, '-')}" for leg in legs))
print(f"\n{changed} of {sum(1 for n in results if not n.startswith('_'))} observations differ between the legs")
(out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")

if recorded_path and recorded_path.exists():
    recorded = json.loads(recorded_path.read_text())
    drift = [n for n in sorted(set(results) | set(recorded)) if not n.startswith("_") and results.get(n) != recorded.get(n)]
    for name in drift:
        print(f"NOT AS RECORDED  {name}: {results.get(name)} (recorded {recorded.get(name)})")
    print(f"{len(drift)} observations differ from recorded.json")
    sys.exit(1 if drift else 0)
