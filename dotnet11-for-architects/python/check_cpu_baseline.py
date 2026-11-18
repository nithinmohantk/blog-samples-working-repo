"""Will this x86-64 host start a .NET 11 process?

.NET 11 raises the minimum x86-64 instruction set from x86-64-v1 to x86-64-v2, and its precompiled
(ReadyToRun) code targets x86-64-v3 on Windows and Linux. A host below v2 fails at start-up; a host
between v2 and v3 starts, and re-compiles more code with the JIT.

    python check_cpu_baseline.py                 # this Linux host, from /proc/cpuinfo
    python check_cpu_baseline.py --flags "fpu sse2 ..."   # a flag list collected from another host
    lscpu | grep Flags | python check_cpu_baseline.py --stdin

Exit code 0: v2 or better. 1: below v2, .NET 11 will not start. 2: could not tell.
"""
from __future__ import annotations

import argparse
import json
import sys

# Names as Linux prints them in /proc/cpuinfo. SSE3 is 'pni'; LZCNT is 'abm'.
V2 = {"cx16": "CX16", "popcnt": "POPCNT", "pni": "SSE3", "ssse3": "SSSE3", "sse4_1": "SSE4.1", "sse4_2": "SSE4.2"}
V3 = {"avx": "AVX", "avx2": "AVX2", "bmi1": "BMI1", "bmi2": "BMI2", "f16c": "F16C", "fma": "FMA", "abm": "LZCNT", "movbe": "MOVBE"}


def assess(flags: set[str]) -> dict:
    missing_v2 = sorted(name for flag, name in V2.items() if flag not in flags)
    missing_v3 = sorted(name for flag, name in V3.items() if flag not in flags)
    level = "below x86-64-v2" if missing_v2 else ("x86-64-v2" if missing_v3 else "x86-64-v3")
    return {
        "level": level,
        "startsDotnet11": not missing_v2,
        "usesPrecompiledCode": not missing_v2 and not missing_v3,
        "missingForV2": missing_v2,
        "missingForV3": missing_v3,
    }


def flags_from_cpuinfo(text: str) -> set[str]:
    for line in text.splitlines():
        if line.lower().startswith("flags"):
            return set(line.split(":", 1)[1].split())
    raise ValueError("no 'flags' line found")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flags", help="space-separated CPU flags")
    parser.add_argument("--stdin", action="store_true", help="read a 'Flags:' line from standard input")
    args = parser.parse_args()
    try:
        if args.flags is not None:
            flags = set(args.flags.split())
        elif args.stdin:
            flags = flags_from_cpuinfo(sys.stdin.read())
        else:
            with open("/proc/cpuinfo", encoding="utf-8") as handle:
                flags = flags_from_cpuinfo(handle.read())
    except (OSError, ValueError) as error:
        print(f"Could not read CPU flags: {error}", file=sys.stderr)
        return 2
    result = assess(flags)
    print(json.dumps(result, indent=2))
    return 0 if result["startsDotnet11"] else 1


if __name__ == "__main__":
    sys.exit(main())
