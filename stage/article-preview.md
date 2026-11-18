# The xz Backdoor (CVE-2024-3094): SBOM Triage for Images and Lambda Layers, and Where SBOMs Go Blind

*Sunday 31 March 2024. Slug `xz-backdoor-cve-2024-3094-sbom-triage-images-lambda-layers`*

**Excerpt:** Which xz versions count, a version check that does not flag Debian's fix, and why a Pillow Lambda layer carries a liblzma no SBOM lists. Tested with Syft 1.1.0 on March 2024 images, without downloading a backdoored binary.

On Friday 29 March 2024, Andres Freund reported on the oss-security list that the upstream xz repository and release tarballs had been backdoored. By the evening CVE-2024-3094 had a CVSS score of 10.0, CISA had told everyone to go back to an uncompromised version such as 5.4.6, and Red Hat had told Fedora Rawhide users to stop using those machines. Since then, most security teams have been answering one question for every image, host and artefact they own: do we have it?

This article is about answering that question properly, from SBOMs, for container images and Lambda layers. It covers which versions count, a version check that does not flag the fix, why a package-level SBOM can miss a copy of liblzma entirely, and how to read a library's version without running the code you are worried about. The sample code was run against real images from March 2024 and a Lambda layer, and it does not download any compromised binary.

## What is affected, as of 31 March

The malicious code is in xz 5.6.0, released on 24 February, and 5.6.1, released on 9 March. The payload sat in obfuscated test files committed to the repository, but the trigger was only in the release tarballs: an extra build script that, during configure, decides whether to inject that object code into the library. Freund's report lists the conditions it checks: an x86-64 Linux target with glibc, built with gcc and the GNU linker, as part of a Debian or RPM package build. The injected code then targets sshd, which does not use liblzma directly but loads it through libsystemd on distributions that patch OpenSSH for systemd notification.

| Source | What it says |
| :--- | :--- |
| Upstream | xz 5.6.0 and 5.6.1 are compromised; go back to 5.4.x (CISA suggests 5.4.6) |
| Debian (DSA-5649-1) | No stable release affected; testing, unstable and experimental from 5.5.1alpha-0.1 to 5.6.1-1 are; fixed as 5.6.1+really5.4.5-1 |
| Red Hat / Fedora | No RHEL release affected; Fedora 41 and Rawhide received 5.6.x; Fedora 40 beta shipped xz-libs 5.6.0-1.fc40 and 5.6.0-2.fc40, where the injection is not believed to have worked, but users should still revert to 5.4.x |
| Kali | Affected if updated between 26 and 29 March |
| openSUSE | Tumbleweed and MicroOS updated between 7 and 28 March |
| Arch Linux | Installation medium, VM images and container images built between 24 February and 28 March carried 5.6.x |
| AWS | Amazon Linux and Bottlerocket not affected; AWS services do not use the affected software |

For most production fleets the answer is therefore no: stable Debian, released Ubuntu LTS versions, RHEL and Amazon Linux never shipped 5.6.x. The exposure is in places that follow fast-moving distributions: developer laptops, CI runners and build images on Debian testing or Fedora Rawhide, Arch-based containers, and anything a team built from those. That is exactly what an SBOM inventory should find quickly, if it is read correctly.

## A version check that does not flag the fix

The first scripts written on Friday searched for the strings 5.6.0 and 5.6.1. That fails in both directions. Debian's fixed package is versioned 5.6.1+really5.4.5-1, because a package version may not go backwards, so a substring search flags the fix. An unrelated package that happens to be at 5.6.1 is flagged too. And it misses 5.5.1alpha, the development release that Debian also lists as compromised. These are the results on a synthetic SBOM holding the versions from the advisories:

```text
liblzma5  5.6.1-1                naive: FLAG  rules: affected
liblzma5  5.6.0-0.2              naive: FLAG  rules: affected
liblzma5  5.5.1alpha-0.1         naive: ok    rules: suspect
liblzma5  5.6.1+really5.4.5-1    naive: FLAG  rules: not affected
liblzma5  5.4.1-0.2              naive: ok    rules: not affected
xz-libs   5.6.0-2.fc40           naive: FLAG  rules: affected
xz-libs   1:5.4.6-1              naive: ok    rules: not affected
xz-libs   5.2.5-9.amzn2023.0.2   naive: ok    rules: not affected
xz-libs   5.4.5-r0               naive: ok    rules: not affected
libfoo    5.6.1                  naive: FLAG  rules: not an xz package
```

The fix is to work out the real upstream version first, then compare that. The rules are small but distribution-specific:

```python
def upstream_version(version: str) -> str:
    """The upstream xz version inside a distribution package version.

    1:5.6.0-1.fc40        -> 5.6.0        (epoch and RPM release removed)
    5.6.1+really5.4.5-1   -> 5.4.5        (Debian's revert: the real code is what follows +really)
    5.4.5-r0              -> 5.4.5        (Alpine)
    """
    v = version.split(":", 1)[-1]
    if "+really" in v:
        v = v.split("+really", 1)[1]
    m = re.match(r"(\d+\.\d+\.\d+(?:alpha|beta)?)", v)
    return m.group(1) if m else v
```

```python
def classify(name: str, version: str) -> Verdict | None:
    """None if the package is not part of xz; otherwise a verdict on its version."""
    if name.lower() not in PACKAGE_NAMES:
        return None
    up = upstream_version(version)
    if up in AFFECTED_UPSTREAM:
        return Verdict("affected", up, "upstream 5.6.0/5.6.1: replace with 5.4.x")
    if re.fullmatch(r"5\.5\.\d+(alpha|beta)", up):
        return Verdict("suspect", up, "5.5.x development release by the same maintainer; Debian lists 5.5.1alpha-0.1 as compromised")
    return Verdict("not affected", up, "")
```

Two choices here are judgement, not fact. The 5.5.x development releases are marked suspect rather than affected, because they came from the same maintainer and Debian includes them in its compromised range, but they were not named in the upstream advisory. And Fedora 40 beta's 5.6.0 builds count as affected, because Red Hat asks users to revert them even though the injection is not believed to have worked there. In both cases the action is the same: replace with 5.4.x.

## Reading the SBOMs

Syft writes CycloneDX and SPDX JSON, and teams usually keep whichever their tooling settled on. The triage code reads both and the tests require identical verdicts from each, which catches the common mistake of reading one format's nested components but not the other's:

```python
def packages(doc: dict):
    """(name, version, purl) for every package, whichever of the two formats the document is."""
    if doc.get("bomFormat") == "CycloneDX":
        def walk(components):
            for c in components or []:
                yield c.get("name", ""), c.get("version", ""), c.get("purl", "")
                yield from walk(c.get("components"))
        yield from walk(doc.get("components"))
    elif "spdxVersion" in doc:
        for p in doc.get("packages", []):
            purl = next((r["referenceLocator"] for r in p.get("externalRefs", [])
                         if r.get("referenceType") == "purl"), "")
            yield p.get("name", ""), p.get("versionInfo", ""), purl
    else:
        raise ValueError("neither CycloneDX nor SPDX JSON")
```

The CI job installs Syft v1.1.0, the release of 25 March 2024, and verifies its checksum before use. A supply-chain incident is a poor time to pipe an installer script into a shell:

```bash
          base=https://github.com/anchore/syft/releases/download/v1.1.0
          curl -sSfLO "$base/syft_1.1.0_linux_amd64.tar.gz"
          curl -sSfLO "$base/syft_1.1.0_checksums.txt"
          grep " syft_1.1.0_linux_amd64.tar.gz$" syft_1.1.0_checksums.txt | sha256sum -c -
          tar -xzf syft_1.1.0_linux_amd64.tar.gz -C "$HOME/bin" syft
```

These are the results for five public images as they were published in March 2024, comparing the SBOM's package entry with a scan of every liblzma file in the image's exported filesystem:

```text
debian:bookworm-20240311-slim
  SBOM:  liblzma5 5.4.1-0.2 (not affected)
  bytes: liblzma.so.5.4.1 = 5.4.1
ubuntu:jammy-20240227
  SBOM:  liblzma5 5.2.5-2ubuntu1 (not affected)
  bytes: liblzma.so.5.2.5 = 5.2.5
alpine:3.19.1
  SBOM:  no xz package
  bytes: no liblzma file
amazonlinux:2023.3.20240312.0
  SBOM:  xz-libs 5.2.5-9.amzn2023.0.2 (not affected)
  bytes: liblzma.so.5.2.5 = 5.2.5
python:3.12.2-slim-bookworm
  SBOM:  liblzma5 5.4.1-0.2 (not affected)
  bytes: liblzma.so.5.4.1 = 5.4.1
```

None of them is affected, which matches the advisories. Two details are worth noting. Alpine's base image has no xz package at all, because BusyBox provides the command. And in every image the package database and the file agree, which is what makes the package-level SBOM trustworthy for these images. That agreement does not hold everywhere.

![Table comparing Syft SBOM entries with a byte scan of liblzma files for five March 2024 container images and a Lambda layer with Pillow 10.2.0; the layer's SBOM lists only Pillow while the byte scan finds a vendored liblzma 5.4.5](img1.jpg)
*The SBOM and the bytes agree for every image, but not for the layer.*

## Where an SBOM goes blind

Python wheels built for manylinux bundle the C libraries they need, renamed with a hash so they cannot clash with the system's copies. A Lambda layer built from such wheels carries those libraries, and no package database records them. Pillow is a common example. The sample builds a layer the way most teams do:

```python
layer_dir = work / "layer"
run(sys.executable, "-m", "pip", "install", "-q", "--target", str(layer_dir / "python"), "--only-binary=:all:",
    "--platform", "manylinux2014_x86_64", "--python-version", "3.12", "--implementation", "cp", "pillow==10.2.0")
layer_zip = work / "pillow-layer.zip"
run("bash", "-c", f"cd {layer_dir} && zip -qr {layer_zip} python")
cdx, _ = syft(
```

And this is what each method sees:

```text
Syft packages in the layer: pillow
xz packages in the layer SBOM: 0
liblzma file: python/pillow.libs/liblzma-d1e41b3a.so.5.4.5 (270,265 bytes), embedded version 5.4.5
```

Syft records Pillow as a Python package, which is correct, but the liblzma inside it is invisible: it is not a package, it is a file inside one. Pillow 10.2.0 carries liblzma 5.4.5, so this layer is safe, but the method that confirmed it was reading the file, not the SBOM. The same applies to anything that vendors compression libraries: other Python wheels, statically linked Go and Rust binaries, Java native bundles and appliance images.

## Reading a version without loading the library

The obvious way to ask a shared library for its version is to load it and call `lzma_version_string()`, through ctypes, a short C program, or the `xz` binary next to it. For this incident that is the wrong move. The injected code runs while the library is being loaded and its symbols are resolved, before any function is called, so loading a suspect copy executes the backdoor's setup code on the machine doing the triage. Reading the file is safe:

```python
NAME = re.compile(r"(^|/)liblzma[^/]*\.so(\.[0-9.]+)?$")
# LZMA_VERSION_STRING is stored as a NUL-terminated string, e.g. b"\x005.4.5\x00".
VERSION = re.compile(rb"\x00(5\.\d+\.\d+(?:alpha|beta)?)\x00")
ELF = b"\x7fELF"


@dataclass(frozen=True)
class LibraryCopy:
    container: str
    path: str
    size: int
    versions: tuple[str, ...]      # every candidate string found; exactly one is the normal case


def versions_in(data: bytes) -> tuple[str, ...]:
    if not data.startswith(ELF):
        return ()
    return tuple(sorted({m.group(1).decode() for m in VERSION.finditer(data)}))


def _from_zip
```

liblzma keeps its version as a NUL-terminated string in read-only data. Across the five images and the Pillow layer, the pattern found exactly one candidate in each library and it matched the package version every time, as the table above shows. The file name is a hint but not evidence: the soname link is just `liblzma.so.5`, and vendored copies carry a hash in the name. The unit tests check that a misleadingly named file is still reported with the version in its bytes.

This is a version check, not a malware detector. A compromised 5.6.1 build reports 5.6.1 like a clean one. The detection scripts published since Friday look for the injected function's byte pattern; they answer a different question, whether this particular build had the injection applied, which matters for forensics on a host that was running sshd but not for deciding what to remove.

## Triage, step by step

![Flow from SBOM and byte scan to an upstream version, then to a verdict: affected for 5.6.0 and 5.6.1, suspect for 5.5.x development releases, not affected for 5.4.x and the +really5.4.5 revert, with the action for each](img2.jpg)
*One set of rules for every copy, wherever it was found.*

- **Inventory.** Generate or collect an SBOM for every image in your registries, every Lambda layer and every function package. Keep both the SBOM and the scan output; the next advisory will ask the same question.
- **Scan the bytes as well.** Run the liblzma file scan over the same artefacts. Anything it finds that the SBOM does not list is vendored and needs its own owner.
- **Classify on the upstream version.** Use rules like the ones above, not a substring search.
- **Act on affected copies.** Rebuild on a base with 5.4.x and redeploy. Do not patch running containers.
- **Escalate hosts, not images.** A host that ran sshd with an affected x86-64 glibc build is a security incident: isolate, investigate and rotate credentials, as CISA asks. A container image that was never started with sshd is a rebuild.
- **Check the build estate.** CI runners and developer images on rolling distributions are the likeliest place to find 5.6.x, and they hold signing keys and deployment credentials.

> **DO NOT PULL AFFECTED IMAGES TO TEST**  
> Testing a scanner against a real compromised image means downloading and unpacking the backdoored library. The sample covers affected versions with synthetic SBOMs and fake ELF stubs instead. If you need a positive control for binary detection, use a detection script's published byte pattern in an isolated environment, not a production runner.

## Lambda specifically

AWS has said that Amazon Linux is not affected, and AWS-provided Lambda runtimes are built on it, so a function using a managed runtime with no layers needs no action for its base. What remains is what you add: layers, function packages and container images built on other distributions. Lambda functions do not run sshd, so the published exploit path does not apply inside them. The compromised library is still malicious code from an untrusted source, and the only sensible response is to replace it. Container-image functions built on Debian testing or an Arch base from the affected window are the most likely positives.

## Making the next answer quicker

Most of the time spent on Friday and Saturday was not analysis. It was finding out what existed: which images were still deployed, which base each was built on, which layers each function used. The incident is a useful prompt to make that inventory permanent rather than rebuilding it under pressure for the next advisory.

- **Generate the SBOM at build time and keep it with the digest.** An SBOM produced in the pipeline describes exactly what was shipped. Store it next to the image digest or layer version, not in a spreadsheet keyed by tag, because tags move.
- **Index by package URL.** A query such as every artefact with `pkg:deb/debian/liblzma5` should return in seconds. A table of digest, purl and version in any database is enough to start.
- **Record what is deployed, not only what is built.** Registries keep years of images. The useful answer is which affected digests are running now, in which accounts and Regions, and who owns them.
- **Add a byte scan for native libraries.** Run it on layers, function packages and images, and store its output beside the SBOM, so vendored copies are part of the same query.
- **Track base-image lineage.** Knowing that forty images derive from one internal base turns forty investigations into one rebuild.
- **Measure the time to answer.** How long it takes to say whether you have a given package, at a given version, in production is a better indicator of supply-chain readiness than the number of SBOMs generated.

## Decision framework

| Finding | Action |
| :--- | :--- |
| Package xz 5.6.0 or 5.6.1 in an image | Rebuild on a 5.4.x base and redeploy; quarantine the old image |
| Same, on a host that ran sshd | Incident: isolate, investigate, rotate credentials, rebuild |
| Debian 5.5.x alpha or beta | Replace with 5.4.x; treat as affected for reporting |
| Debian 5.6.1+really5.4.5-1 | Fixed; no action |
| Fedora 40 beta xz-libs 5.6.0 | Revert to 5.4.x as Red Hat advises |
| liblzma found by byte scan but not in the SBOM | Find the package that vendors it, check its version, and add byte scanning to the pipeline |
| Amazon Linux base, managed Lambda runtime | No action for the base; scan layers and packages |

> **HOW THIS WAS CHECKED**  
> The sample ran in GitHub Actions ([run](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44400012484)) with Syft v1.1.0 (checksum verified), Python 3.12 and pytest 8.1.1 (packages as of 30 March 2024). The images are the dated Docker Hub tags shown above and the layer uses Pillow 10.2.0, the release current on 31 March 2024. All 12 unit tests passed and the output above is copied from that run. No image or package containing xz 5.6.x was downloaded; affected versions were tested with synthetic SBOMs and stub ELF files. Advisory details are as published by Debian, Red Hat, CISA and AWS on 29 and 30 March 2024.

## Key takeaways

- CVE-2024-3094 affects xz 5.6.0 and 5.6.1; stable Debian, released Ubuntu LTS versions, RHEL and Amazon Linux never shipped them.
- Compare upstream versions, not substrings: Debian's fix is 5.6.1+really5.4.5-1, and 5.5.1alpha is in Debian's compromised range.
- Package-level SBOMs miss libraries vendored inside wheels and binaries; a Pillow layer carries its own liblzma that no package database lists.
- Read a suspect library's version from its bytes; loading it runs the injected code.
- Images get rebuilt; hosts that ran sshd with an affected build get treated as incidents.

If your own inventory turned up liblzma in a place no SBOM listed, let me know in the comments below where it was.

> **GET THE CODE**  
> [https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/xz-cve-2024-3094-sbom-triage](https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/xz-cve-2024-3094-sbom-triage)

## Glossary

- **CVE-2024-3094**: The identifier for the malicious code in xz 5.6.0 and 5.6.1.
- **xz / liblzma**: The XZ Utils compression tools and the shared library they provide.
- **SBOM**: Software bill of materials: a machine-readable list of the components in an artefact.
- **CycloneDX**: An SBOM format from OWASP, commonly written as JSON.
- **SPDX**: An SBOM format from the Linux Foundation, also an ISO standard.
- **Syft**: Anchore's open-source tool for generating SBOMs from images, directories and archives.
- **purl**: Package URL: a standard identifier such as pkg:deb/debian/liblzma5@5.4.1-0.2.
- **Vendored library**: A copy of a library bundled inside another package instead of installed by the system.
- **manylinux wheel**: A Python binary package built to run on most Linux distributions, with its C libraries bundled.
- **IFUNC**: A glibc mechanism that picks a function implementation when a library is loaded.
- **Epoch**: A prefix such as 1: in a package version that overrides normal version ordering.
- **+really**: Debian's convention for reverting to an older upstream version under a higher package version.

## References & Further Reading

- [backdoor in upstream xz/liblzma leading to ssh server compromise](https://www.openwall.com/lists/oss-security/2024/03/29/4): Andres Freund, oss-security, 29 March 2024
- [Reported Supply Chain Compromise Affecting XZ Utils](https://www.cisa.gov/news-events/alerts/2024/03/29/reported-supply-chain-compromise-affecting-xz-utils-data-compression-library-cve-2024-3094): CISA alert, 29 March 2024
- [DSA-5649-1 xz-utils security update](https://www.debian.org/security/dsa-5649): Debian, 29 March 2024
- [Urgent security alert for Fedora 41 and Rawhide users](https://www.redhat.com/en/blog/urgent-security-alert-fedora-41-and-rawhide-users): Red Hat, updated 30 March 2024
- [AWS security bulletin for CVE-2024-3094](https://aws.amazon.com/security/security-bulletins/AWS-2024-002): Amazon Linux and Bottlerocket not affected
- [Syft v1.1.0](https://github.com/anchore/syft/releases/tag/v1.1.0): The SBOM generator used here
- [CycloneDX specification](https://cyclonedx.org/specification/overview/): SBOM format
- [SPDX](https://spdx.dev/): SBOM format
- [Sample code for this article](https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/xz-cve-2024-3094-sbom-triage): Advisory rules, SBOM readers, byte-level liblzma scan and tests
