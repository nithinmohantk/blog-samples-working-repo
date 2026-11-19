"""Check a repository against the documented prerequisites for automated
code transformation on AWS, and say which tool fits.

- Amazon Q Developer Java transformation: Maven 3.8+ projects on Java 8, 11,
  17 or 21, upgraded to Java 17 or 21. Fails on plugins that package
  non-Java languages (for example frontend-maven-plugin) and on tests that
  need private network resources.
- AWS Transform custom (AWS/java-version-upgrade): Java upgrades for any
  build system, including Gradle.
- AWS Transform for .NET: .NET Framework projects ported to cross-platform .NET.

The scan reads files only. It does not build the project or call AWS.
Exit code: 0 when there are no blockers, 1 when there are, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

SKIP_DIRS = {".git", "target", "build", "node_modules", ".gradle", ".idea", "bin", "obj"}
Q_SOURCE_VERSIONS = {8, 11, 17, 21}
MIN_MAVEN = (3, 8)
JAVA_SUFFIXES = {".java", ".xml", ".properties", ".yml", ".yaml"}
PRIVATE_JDBC = re.compile(
    r"jdbc:(?:mysql|mariadb|postgresql|oracle:thin:@|sqlserver)://?(?!localhost|127\.0\.0\.1)[\w.-]+",
    re.IGNORECASE,
)
ORIGIN_TYPES = {"FIRST_PARTY", "THIRD_PARTY"}


@dataclass
class Finding:
    level: str  # BLOCKER, WARNING or INFO
    code: str
    message: str
    path: str = ""


@dataclass
class Report:
    repo: str
    build_systems: list[str] = field(default_factory=list)
    java_versions: list[int] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    recommendation: str = "manual"

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "BLOCKER"]


def _walk(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.is_file():
            yield path


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in node if _local(c.tag) == name]


def _text(node: ET.Element | None, *names: str) -> str | None:
    for name in names:
        if node is None:
            return None
        found = _children(node, name)
        node = found[0] if found else None
    return node.text.strip() if node is not None and node.text else None


def parse_java_version(value: str | None) -> int | None:
    """'1.8' -> 8, '11' -> 11, '${java.version}' -> None."""
    if not value or "${" in value:
        return None
    value = value.strip()
    if value.startswith("1."):
        value = value[2:]
    return int(value) if value.isdigit() else None


def pom_java_version(pom: ET.Element) -> int | None:
    props = {_local(c.tag): (c.text or "").strip() for p in _children(pom, "properties") for c in p}
    for key in ("maven.compiler.release", "maven.compiler.source", "java.version", "maven.compiler.target"):
        raw = props.get(key)
        if raw and raw.startswith("${") and raw.endswith("}"):
            raw = props.get(raw[2:-1])
        version = parse_java_version(raw)
        if version:
            return version
    for plugin in pom.iter():
        if _local(plugin.tag) == "plugin" and _text(plugin, "artifactId") == "maven-compiler-plugin":
            conf = _children(plugin, "configuration")
            for key in ("release", "source"):
                version = parse_java_version(_text(conf[0], key) if conf else None)
                if version:
                    return version
    return None


def pom_plugins(pom: ET.Element) -> set[str]:
    return {
        f"{_text(p, 'groupId') or 'org.apache.maven.plugins'}:{_text(p, 'artifactId')}"
        for p in pom.iter()
        if _local(p.tag) == "plugin"
    }


def maven_wrapper_version(root: Path) -> tuple[int, ...] | None:
    props = root / ".mvn" / "wrapper" / "maven-wrapper.properties"
    if not props.is_file():
        return None
    match = re.search(r"apache-maven/(\d+)\.(\d+)\.(\d+)/", props.read_text(encoding="utf-8", errors="replace"))
    return tuple(int(x) for x in match.groups()) if match else None


def validate_dependency_upgrade_file(path: Path) -> list[Finding]:
    """Check the YAML dependency upgrade file Amazon Q accepts for library upgrades."""
    rel = path.name
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [Finding("BLOCKER", "DEPS_YAML_INVALID", f"not valid YAML: {exc}", rel)]
    if not isinstance(doc, dict):
        return [Finding("BLOCKER", "DEPS_YAML_INVALID", "top level must be a mapping", rel)]
    out: list[Finding] = []
    if not doc.get("name"):
        out.append(Finding("BLOCKER", "DEPS_YAML_FIELD", "missing required field 'name'", rel))
    mgmt = doc.get("dependencyManagement")
    if not isinstance(mgmt, dict):
        return out + [Finding("BLOCKER", "DEPS_YAML_FIELD", "missing required field 'dependencyManagement'", rel)]
    for section in ("dependencies", "plugins"):
        entries = mgmt.get(section)
        if not isinstance(entries, list):
            out.append(Finding("BLOCKER", "DEPS_YAML_FIELD", f"'dependencyManagement.{section}' must be a list", rel))
            continue
        for i, entry in enumerate(entries):
            where = f"dependencyManagement.{section}[{i}]"
            if not isinstance(entry, dict):
                out.append(Finding("BLOCKER", "DEPS_YAML_FIELD", f"{where} must be a mapping", rel))
                continue
            for key in ("identifier", "targetVersion", "originType"):
                if not entry.get(key):
                    out.append(Finding("BLOCKER", "DEPS_YAML_FIELD", f"{where} is missing '{key}'", rel))
            origin = entry.get("originType")
            if origin and origin not in ORIGIN_TYPES:
                out.append(Finding("BLOCKER", "DEPS_YAML_FIELD", f"{where} originType must be FIRST_PARTY or THIRD_PARTY", rel))
    return out


def scan(root: Path, deps_file: Path | None = None) -> Report:
    root = root.resolve()
    report = Report(repo=str(root))
    files = list(_walk(root))
    poms = [f for f in files if f.name == "pom.xml"]
    gradle = [f for f in files if f.name in {"build.gradle", "build.gradle.kts"}]
    csprojs = [f for f in files if f.suffix == ".csproj"]

    if poms:
        report.build_systems.append("maven")
    if gradle:
        report.build_systems.append("gradle")
    if csprojs:
        report.build_systems.append("msbuild")

    for pom_path in poms:
        rel = str(pom_path.relative_to(root))
        try:
            pom = ET.parse(pom_path).getroot()
        except ET.ParseError as exc:
            report.findings.append(Finding("BLOCKER", "POM_INVALID", f"cannot parse: {exc}", rel))
            continue
        version = pom_java_version(pom)
        if version:
            report.java_versions.append(version)
            if version not in Q_SOURCE_VERSIONS:
                report.findings.append(Finding(
                    "BLOCKER", "JAVA_VERSION_UNSUPPORTED",
                    f"Java {version}; Amazon Q upgrades only from Java 8, 11, 17 or 21", rel))
        if "com.github.eirslett:frontend-maven-plugin" in pom_plugins(pom):
            report.findings.append(Finding(
                "BLOCKER", "NON_JAVA_PLUGIN",
                "frontend-maven-plugin packages non-Java code and causes the transformation to fail", rel))

    if poms:
        if not report.java_versions:
            report.findings.append(Finding(
                "WARNING", "JAVA_VERSION_UNKNOWN",
                "no Java version found in pom.xml; set maven.compiler.release or source"))
        wrapper = maven_wrapper_version(root)
        if wrapper is None:
            report.findings.append(Finding(
                "INFO", "MAVEN_VERSION_UNCHECKED", "no Maven wrapper; make sure the IDE uses Maven 3.8 or later"))
        elif wrapper[:2] < MIN_MAVEN:
            report.findings.append(Finding(
                "BLOCKER", "MAVEN_TOO_OLD",
                f"Maven wrapper pins {'.'.join(map(str, wrapper))}; Amazon Q needs 3.8 or later",
                ".mvn/wrapper/maven-wrapper.properties"))

    for path in files:
        if path.suffix not in JAVA_SUFFIXES:
            continue
        rel = str(path.relative_to(root))
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            report.findings.append(Finding("WARNING", "NON_UTF8", "file is not UTF-8", rel))
            continue
        if "/src/test/" in f"/{rel}" and PRIVATE_JDBC.search(text):
            report.findings.append(Finding(
                "WARNING", "TEST_NEEDS_PRIVATE_NETWORK",
                "test resource points at a non-local database; tests that need private networks fail the transformation",
                rel))

    framework_projects = [
        p for p in csprojs
        if re.search(r"<TargetFrameworkVersion>v4\.|<TargetFrameworks?>[^<]*net4\d",
                     p.read_text(encoding="utf-8", errors="replace"))
    ]

    if deps_file is not None:
        report.findings.extend(validate_dependency_upgrade_file(deps_file))

    if framework_projects:
        report.recommendation = "aws-transform-dotnet"
    elif poms and not report.blockers:
        report.recommendation = "q-developer-java"
    elif poms or gradle:
        report.recommendation = "aws-transform-custom"
    return report


def _print(report: Report) -> None:
    print(f"Repository:     {report.repo}")
    print(f"Build systems:  {', '.join(report.build_systems) or 'none found'}")
    print(f"Java versions:  {', '.join(map(str, sorted(set(report.java_versions)))) or 'unknown'}")
    print(f"Recommendation: {report.recommendation}")
    for f in report.findings:
        where = f" ({f.path})" if f.path else ""
        print(f"  {f.level:<8} {f.code}: {f.message}{where}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", type=Path)
    parser.add_argument("--deps-file", type=Path, help="dependency upgrade YAML to validate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.repo.is_dir():
        parser.error(f"{args.repo} is not a directory")
    if args.deps_file and not args.deps_file.is_file():
        parser.error(f"{args.deps_file} is not a file")
    report = scan(args.repo, args.deps_file)
    if args.json:
        print(json.dumps({**asdict(report), "blockers": len(report.blockers)}, indent=2))
    else:
        _print(report)
    return 1 if report.blockers else 0


if __name__ == "__main__":
    sys.exit(main())
