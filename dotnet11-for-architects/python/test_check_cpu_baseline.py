"""python test_check_cpu_baseline.py"""
import sys

from check_cpu_baseline import assess, flags_from_cpuinfo

V2 = "fpu sse sse2 cx16 popcnt pni ssse3 sse4_1 sse4_2"
V3 = V2 + " avx avx2 bmi1 bmi2 f16c fma abm movbe"
cases = [
    ("a host with every v3 flag", V3, "x86-64-v3", True, True),
    ("a v2 host without AVX2 starts and uses the JIT more", V2 + " avx", "x86-64-v2", True, False),
    ("a host without SSE4.2 does not start", "fpu sse sse2 cx16 popcnt pni ssse3 sse4_1", "below x86-64-v2", False, False),
    ("a host without POPCNT does not start", V3.replace("popcnt ", ""), "below x86-64-v2", False, False),
    ("an empty flag list does not start", "", "below x86-64-v2", False, False),
]
failed = 0
for name, flags, level, starts, precompiled in cases:
    result = assess(set(flags.split()))
    ok = (result["level"], result["startsDotnet11"], result["usesPrecompiledCode"]) == (level, starts, precompiled)
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
ok = flags_from_cpuinfo("processor : 0\nflags\t\t: fpu sse4_2 avx2\nbogomips : 1") == {"fpu", "sse4_2", "avx2"}
failed += not ok
print(f"{'ok  ' if ok else 'FAIL'}  the flags line of /proc/cpuinfo is parsed")
ok = assess(set("fpu sse".split()))["missingForV2"] == ["CX16", "POPCNT", "SSE3", "SSE4.1", "SSE4.2", "SSSE3"]
failed += not ok
print(f"{'ok  ' if ok else 'FAIL'}  missing instruction sets are named")
print(f"\n{len(cases) + 2 - failed} of {len(cases) + 2} checks passed")
sys.exit(1 if failed else 0)
