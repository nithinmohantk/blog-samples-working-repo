"""python test_decide.py"""
import pathlib
import sys

from decide import decide, ownership_counts

cases = [
    ("a stateless API with no Kubernetes needs", {}, "Azure Container Apps", 0),
    ("the same, and the team already runs Kubernetes", {"team_operates_kubernetes_today": True}, "Azure Container Apps", 1),
    ("an operator and custom resources", {"needs_kubernetes_api": True, "team_operates_kubernetes_today": True}, "AKS Automatic", 0),
    ("network policy between services, no Kubernetes skills", {"needs_network_policy_between_services": True}, "AKS Automatic", 1),
    ("a node agent and staged upgrades", {"needs_daemonsets_or_privileged": True, "needs_own_upgrade_schedule_per_pool": True, "team_operates_kubernetes_today": True}, "AKS Standard", 0),
    ("only custom node configuration", {"needs_custom_node_configuration": True, "team_operates_kubernetes_today": True}, "AKS Standard", 1),
    ("bring your own CNI, no Kubernetes skills", {"needs_kubernetes_api": True, "needs_bring_your_own_cni": True}, "AKS Standard", 1),
]
failed = 0
for name, facts, platform, cautions in cases:
    result = decide(facts)
    ok = result["platform"] == platform and len(result["cautions"]) == cautions and result["reasons"]
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {name}: {result['platform']}, {len(result['cautions'])} caution(s)")
try:
    decide({"needs_gpu": True})
    ok = False
except ValueError:
    ok = True
failed += not ok
print(f"{'ok  ' if ok else 'FAIL'}  an unknown fact is refused, not ignored")
counts = ownership_counts(pathlib.Path(__file__).with_name("ownership.json"))
ok = counts["aca"].get("you") == 4 and counts["aks_automatic"].get("you") == 6 and counts["aks_standard"].get("you") == 12
failed += not ok
print(f"{'ok  ' if ok else 'FAIL'}  duties that are yours: {counts['aca'].get('you')} on Container Apps, {counts['aks_automatic'].get('you')} on AKS Automatic, {counts['aks_standard'].get('you')} on AKS Standard")
print(f"\n{len(cases) + 2 - failed} of {len(cases) + 2} checks passed")
sys.exit(1 if failed else 0)
