import json
from pathlib import Path

import pytest

import readiness

POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>orders</artifactId>
  <version>1.0.0</version>
  <properties>{props}</properties>
  <build><plugins>{plugins}</plugins></build>
</project>
"""

WRAPPER = "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/{v}/apache-maven-{v}-bin.zip\n"


def write(root: Path, rel: str, text: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def maven_repo(root: Path, props="<java.version>1.8</java.version><maven.compiler.source>${java.version}</maven.compiler.source>",
               plugins="", maven="3.9.9") -> Path:
    write(root, "pom.xml", POM.format(props=props, plugins=plugins))
    write(root, ".mvn/wrapper/maven-wrapper.properties", WRAPPER.format(v=maven))
    write(root, "src/main/java/com/example/App.java", "class App {}\n")
    return root


def codes(report):
    return {f.code for f in report.findings}


def test_java8_maven_project_is_ready_for_q(tmp_path):
    report = readiness.scan(maven_repo(tmp_path))
    assert report.java_versions == [8]
    assert report.blockers == []
    assert report.recommendation == "q-developer-java"


def test_compiler_plugin_release_is_read(tmp_path):
    plugin = ("<plugin><artifactId>maven-compiler-plugin</artifactId>"
              "<configuration><release>11</release></configuration></plugin>")
    report = readiness.scan(maven_repo(tmp_path, props="", plugins=plugin))
    assert report.java_versions == [11]


def test_frontend_plugin_blocks_q_and_points_to_transform_custom(tmp_path):
    plugin = "<plugin><groupId>com.github.eirslett</groupId><artifactId>frontend-maven-plugin</artifactId></plugin>"
    report = readiness.scan(maven_repo(tmp_path, plugins=plugin))
    assert "NON_JAVA_PLUGIN" in codes(report)
    assert report.recommendation == "aws-transform-custom"


def test_unsupported_source_version_is_a_blocker(tmp_path):
    report = readiness.scan(maven_repo(tmp_path, props="<maven.compiler.release>15</maven.compiler.release>"))
    assert "JAVA_VERSION_UNSUPPORTED" in codes(report)


def test_old_maven_wrapper_is_a_blocker(tmp_path):
    report = readiness.scan(maven_repo(tmp_path, maven="3.6.3"))
    assert "MAVEN_TOO_OLD" in codes(report)


def test_gradle_only_project_goes_to_transform_custom(tmp_path):
    write(tmp_path, "build.gradle", "plugins { id 'java' }\n")
    report = readiness.scan(tmp_path)
    assert report.build_systems == ["gradle"]
    assert report.recommendation == "aws-transform-custom"


def test_dotnet_framework_project_goes_to_transform_for_dotnet(tmp_path):
    write(tmp_path, "Web/Web.csproj",
          "<Project><PropertyGroup><TargetFrameworkVersion>v4.8</TargetFrameworkVersion></PropertyGroup></Project>")
    assert readiness.scan(tmp_path).recommendation == "aws-transform-dotnet"


def test_private_database_in_tests_and_non_utf8_are_warnings(tmp_path):
    maven_repo(tmp_path)
    write(tmp_path, "src/test/resources/application.properties",
          "spring.datasource.url=jdbc:postgresql://orders-db.corp.internal:5432/orders\n")
    write(tmp_path, "src/main/java/com/example/Legacy.java", "// caf\xe9\n".encode("latin-1"))
    report = readiness.scan(tmp_path)
    assert {"TEST_NEEDS_PRIVATE_NETWORK", "NON_UTF8"} <= codes(report)
    assert report.blockers == []


def test_build_output_is_ignored(tmp_path):
    maven_repo(tmp_path)
    write(tmp_path, "target/classes/pom.xml", "not xml")
    assert "POM_INVALID" not in codes(readiness.scan(tmp_path))


def test_valid_dependency_upgrade_file(tmp_path):
    deps = Path(__file__).parent.parent / "dependency-upgrade.yaml"
    assert readiness.validate_dependency_upgrade_file(deps) == []


@pytest.mark.parametrize("body,expected", [
    ("name: x\n", "missing required field 'dependencyManagement'"),
    ("name: x\ndependencyManagement:\n  dependencies: []\n", "'dependencyManagement.plugins' must be a list"),
    ("name: x\ndependencyManagement:\n  plugins: []\n  dependencies:\n"
     "    - identifier: a:b\n      targetVersion: '1'\n      originType: INTERNAL\n", "originType must be"),
])
def test_invalid_dependency_upgrade_files(tmp_path, body, expected):
    path = write(tmp_path, "deps.yaml", body)
    messages = [f.message for f in readiness.validate_dependency_upgrade_file(path)]
    assert any(expected in m for m in messages), messages


def test_cli_json_and_exit_code(tmp_path, capsys):
    plugin = "<plugin><groupId>com.github.eirslett</groupId><artifactId>frontend-maven-plugin</artifactId></plugin>"
    assert readiness.main([str(maven_repo(tmp_path, plugins=plugin)), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["blockers"] == 1 and out["recommendation"] == "aws-transform-custom"
