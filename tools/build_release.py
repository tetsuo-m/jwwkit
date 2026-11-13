"""Build and audit the public release archives from a separate directory."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSIONS = ("3.11", "3.12", "3.13", "3.14", "3.15")
TEMPLATE = "src/jwwkit/resources/empty_template.jww"
TEMPLATE_SHA256 = "0913d5f6755b7038c11cda8be75c2502511ce85a007f9bcc2f10df049f6eff1e"
ROOT_FILES = {"README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "MANIFEST.in", "pyproject.toml"}
RESOURCE_FILES = {"header.json", "jwf_schema.json", "text_equivalence_v1.json",
                  "halfwidth_kana_composition_v1.json", "README.md", "jww_workflow.example.toml"}
GENERATED_SDIST = {"PKG-INFO", "setup.cfg"} | {
    "src/jwwkit.egg-info/" + name for name in (
        "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt",
    )
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_metadata(tag, target):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    pattern = r"\d+\.\d+\.\d+rc[1-9]\d*" if target == "testpypi" else r"\d+\.\d+\.\d+"
    require(re.fullmatch(pattern, version) and tag == f"v{version}",
            f"Tag {tag!r} and pyproject.toml version {version!r} do not match the {target} release format")
    supported = [item for item in PYTHON_VERSIONS if SpecifierSet(project["requires-python"]).contains(item)]
    require(supported, "The declared Python range does not match any supported Windows test version")
    return version, supported


def read_public_files():
    names = (ROOT / "tools/release_files.txt").read_text(encoding="utf-8").splitlines()
    require(len(names) == len(set(names)) and ROOT_FILES <= set(names), "Invalid release file list")
    payload = {}
    for name in names:
        parts = PurePosixPath(name).parts
        require(name and not PurePosixPath(name).is_absolute() and ".." not in parts, f"Invalid path: {name}")
        if name not in ROOT_FILES | {TEMPLATE}:
            require(parts[:2] == ("src", "jwwkit") and
                    ((len(parts) == 4 and parts[2] == "resources" and parts[3] in RESOURCE_FILES)
                     or (parts[2:] == ("guides", "AGENTS.md"))
                     or (len(parts) == 5 and parts[2:4] == ("guides", "docs") and name.endswith(".md"))
                     or (parts[2] not in {"guides", "resources"} and name.endswith(".py"))),
                    f"Path is outside the public package: {name}")
        path = ROOT / name
        for parent in (path, *path.parents):
            if parent == ROOT:
                break
            require(not parent.is_symlink() and not getattr(parent.stat(), "st_file_attributes", 0) & 0x400,
                    f"Link or reparse point in build input: {name}")
        payload[name] = path.read_bytes()
    require(hashlib.sha256(payload[TEMPLATE]).hexdigest() == TEMPLATE_SHA256, "Empty template hash mismatch")
    return payload


def wheel_contents(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel file")
        return {name: archive.read(name) for name in names}


def stabilize_sdist(path, scratch, epoch):
    # Setuptools preserves source timestamps in its tarball. Use one timestamp
    # for the archive and all its members so a fresh checkout gives the same sdist.
    normalized = scratch / path.name
    with tarfile.open(path, "r:gz") as source, normalized.open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                for entry in sorted(source.getmembers(), key=lambda item: item.name):
                    require(entry.isfile() or entry.isdir(), f"Unexpected sdist member: {entry.name}")
                    entry.mtime = epoch
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ""
                    entry.mode = 0o755 if entry.isdir() else 0o644
                    entry.pax_headers = {}
                    target.addfile(entry, source.extractfile(entry) if entry.isfile() else None)
    path.write_bytes(normalized.read_bytes())


def inspect_archives(out, payload, version):
    label = f"jwwkit-{version}"
    wheel, sdist = out / f"{label}-py3-none-any.whl", out / f"{label}.tar.gz"
    require(set(out.iterdir()) == {wheel, sdist}, "Expected exactly one pure-Python wheel and one sdist")
    package = {name.removeprefix("src/"): data for name, data in payload.items() if name.startswith("src/")}
    dist_info = label + ".dist-info/"
    package.update({dist_info + "licenses/" + name: payload[name] for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")})
    wheel_files = wheel_contents(wheel)
    wheel_generated = {dist_info + name for name in ("METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD")}
    require(set(wheel_files) == set(package) | wheel_generated, "Unexpected or missing wheel files")
    require(all(wheel_files[name] == data for name, data in package.items()), "Wheel input bytes changed")
    require(b"Root-Is-Purelib: true" in wheel_files[dist_info + "WHEEL"], "Wheel is not pure Python")
    with tarfile.open(sdist, "r:gz") as archive:
        actual = {}
        for item in archive.getmembers():
            parts = PurePosixPath(item.name).parts
            require(parts and parts[0] == label and ".." not in parts and (item.isfile() or item.isdir()),
                    f"Unexpected sdist member: {item.name}")
            if item.isfile():
                name = "/".join(parts[1:])
                require(name not in actual, f"Duplicate sdist file: {name}")
                actual[name] = archive.extractfile(item).read()
        require(set(actual) == set(payload) | GENERATED_SDIST, "Unexpected or missing sdist files")
        require(all(actual[name] == data for name, data in payload.items()), "Sdist input bytes changed")
    return wheel, sdist, wheel_files, actual


def run(*args):
    subprocess.run([sys.executable, "-m", *args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target", required=True, choices=("testpypi", "pypi"))
    parser.add_argument("--out", type=Path, required=True, help="New directory for the wheel and sdist")
    parser.add_argument("--report", type=Path, required=True, help="New JSON inventory path outside --out")
    args = parser.parse_args()
    version, supported = release_metadata(args.tag, args.target)
    payload = read_public_files()
    output = args.out.resolve()
    report = args.report.resolve()
    require(not report.exists() and not report.is_relative_to(output), "Use a new report path outside --out")
    output.mkdir()
    epoch = 315532800  # Earliest portable ZIP timestamp.
    os.environ["SOURCE_DATE_EPOCH"] = str(epoch)
    with tempfile.TemporaryDirectory(prefix="jwwkit-release-") as tmp:
        workspace = Path(tmp)
        source = workspace / "source"
        for name, data in payload.items():
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        run("build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(output), str(source))
        stabilize_sdist(output / f"jwwkit-{version}.tar.gz", workspace, epoch)
        wheel, sdist, wheel_files, sdist_files = inspect_archives(output, payload, version)
        run("twine", "check", "--strict", str(wheel), str(sdist))
        with tarfile.open(sdist, "r:gz") as archive:
            archive.extractall(workspace / "sdist", filter="data")
        rebuilt = workspace / "rebuilt"
        run("build", "--no-isolation", "--wheel", "--outdir", str(rebuilt),
            str(workspace / "sdist" / f"jwwkit-{version}"))
        require(wheel_contents(rebuilt / wheel.name) == wheel_files, "Rebuilt wheel content differs")
        exact = (rebuilt / wheel.name).read_bytes() == wheel.read_bytes()
    result = {
        "version": version, "windows_test_versions": supported,
        "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (wheel, sdist)},
        "wheel_files": sorted(wheel_files), "sdist_files": sorted(sdist_files),
        "rebuilt_wheel_content_identical": True, "rebuilt_wheel_bytes_identical": exact,
    }
    with report.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
