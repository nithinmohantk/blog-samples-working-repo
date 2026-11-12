"""Copy the contract into every implementation, or check that the copies are current.

    python contract/render.py            write the copies
    python contract/render.py --check    exit 1 if any copy differs from the contract
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contract"
IMPLEMENTATIONS = {
    "network-baseline-aws": {"region": "eu-west-1", "mocks": 'mock_provider "aws" {}'},
    "network-baseline-azure": {"region": "northeurope", "mocks": 'mock_provider "azurerm" {}'},
}


def expected() -> dict[pathlib.Path, str]:
    files = {}
    template = (CONTRACT / "contract.tftest.hcl.tmpl").read_text(encoding="utf-8")
    for name, settings in IMPLEMENTATIONS.items():
        module = ROOT / "modules" / name
        for shared in ("variables.tf", "outputs.tf", "locals.tf"):
            files[module / f"contract_{shared}"] = (CONTRACT / shared).read_text(encoding="utf-8")
        files[module / "tests" / "contract.tftest.hcl"] = template.replace("@@MOCKS@@", settings["mocks"]).replace("@@REGION@@", settings["region"])
    return files


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, content in expected().items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if check:
        print("contract copies are current" if not stale else "STALE: " + ", ".join(stale))
        return 1 if stale else 0
    print(f"wrote {len(expected())} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
