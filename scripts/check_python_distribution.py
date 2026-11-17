#!/usr/bin/env python3
"""Build/qualify wheel and sdist without installing anything into the checkout.

Building needs the declared setuptools/wheel tools already installed. Runtime
qualification installs the wheel with --no-index --no-deps into a disposable
venv, exercises its actual console script from an unrelated directory, and
restores using only the bundled reader and Python's standard library. No network
dependency installation, native-platform emulation or browser test is performed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("app.css", "app.js", "index.html")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def clean_environment():
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONSAFEPATH"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def execute(command, cwd, *, input_text=None, env=None, timeout=120):
    result = subprocess.run(
        [str(value) for value in command],
        cwd=cwd,
        env=clean_environment() if env is None else env,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            "Command failed ("
            + str(result.returncode)
            + "): "
            + str(command)
            + "\n"
            + result.stdout[-4000:]
            + "\n"
            + result.stderr[-4000:]
        )
    return result


def build_python_artifacts(root, output):
    output.mkdir(parents=True, exist_ok=True)
    check(
        not list(output.glob("*.whl")) and not list(output.glob("*.tar.gz")),
        "Build output already contains distributions; choose a new output directory",
    )
    with tempfile.TemporaryDirectory(prefix="archivist-build-") as temporary:
        copied = Path(temporary) / "checkout"
        shutil.copytree(
            root,
            copied,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                ".ruff_cache",
                ".pytest_cache",
                "__pycache__",
                "*.pyc",
                "*.pyo",
                "*.egg-info",
                "build",
                "dist",
            ),
        )
        script = """
import json, sys, setuptools, wheel
from setuptools.build_meta import build_sdist, build_wheel
destination = sys.argv[1]
sdist = build_sdist(destination)
binary = build_wheel(destination)
print('DISTRIBUTION_RESULT='+json.dumps({'wheel':binary,'sdist':sdist,
    'setuptools':setuptools.__version__,'wheel_builder':wheel.__version__}))
"""
        result = execute([sys.executable, "-I", "-c", script, output], copied)
    (output / "build.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    line = next(
        line for line in result.stdout.splitlines() if line.startswith("DISTRIBUTION_RESULT=")
    )
    built = json.loads(line.split("=", 1)[1])
    return output / built["wheel"], output / built["sdist"], built


def wheel_inventory(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        check(len(names) == len(set(names)), "Wheel has duplicate paths")
        for name in names:
            relative = PurePosixPath(name)
            check(
                not relative.is_absolute() and ".." not in relative.parts and "\\" not in name,
                "Wheel has an unsafe path",
            )
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        check(len(metadata_paths) == 1, "Wheel must describe exactly one distribution")
        metadata_root = metadata_paths[0].split("/")[0]
        roots = {name.split("/")[0] for name in names}
        check(
            roots == {"archivist", metadata_root},
            "Wheel installs an unexpected top-level namespace: " + repr(sorted(roots)),
        )
        expected = {
            "archivist/__init__.py",
            "archivist/cli.py",
            "archivist/recovery.py",
            "archivist/kit_publication.py",
            *("archivist/static/" + name for name in ASSETS),
        }
        check(expected <= set(names), "Wheel is missing application modules or static assets")
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
        check(not metadata.get_all("Requires-Dist"), "Unexpected mandatory runtime dependency")
        files = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith("archivist/") and not name.endswith("/")
        }
        return {
            "name": metadata["Name"],
            "version": metadata["Version"],
            "namespace": "archivist",
            "files": files,
        }


def extract_sdist(path, destination):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        check(len(names) == len(set(names)), "Source distribution has duplicate paths")
        roots = set()
        for member in members:
            relative = PurePosixPath(member.name)
            check(
                not relative.is_absolute()
                and ".." not in relative.parts
                and "\\" not in member.name,
                "Source distribution has an unsafe path",
            )
            check(
                member.isfile() or member.isdir(),
                "Source distribution has a link or special object",
            )
            roots.add(relative.parts[0])
        check(len(roots) == 1, "Source distribution must have one root directory")
        archive.extractall(destination, filter="data")
    root = destination / roots.pop()
    for name in (
        "archivist.py",
        "pyproject.toml",
        "MANIFEST.in",
        "launchers/CLI.sh",
        "source/recovery.py",
        "source/static/index.html",
    ):
        check((root / name).is_file(), "Source distribution is missing " + name)
    return root


def qualify(wheel_path, sdist_path, report_directory):
    inventory = wheel_inventory(wheel_path)
    with tempfile.TemporaryDirectory(prefix="archivist-package-check-") as temporary:
        working = Path(temporary)
        unrelated = working / "unrelated-working-directory"
        unrelated.mkdir()
        (unrelated / "archivist.py").write_text(
            "raise RuntimeError('The unrelated working directory was imported')\n", encoding="utf-8"
        )
        environment = working / "installed-environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        console = environment / (
            "Scripts/archivist.exe" if os.name == "nt" else "bin/archivist"
        )
        installed = execute(
            [python, "-I", "-m", "pip", "install", "--no-index", "--no-deps", wheel_path], unrelated
        )
        (report_directory / "installation.log").write_text(
            installed.stdout + installed.stderr, encoding="utf-8"
        )
        check(console.is_file(), "Installed console entry point is missing")
        # POSIX entry points are real generated scripts, so -I can qualify the
        # same entry point while excluding the checkout and caller's directory.
        command = [console] if os.name == "nt" else [python, "-I", console]
        version = execute(command + ["--version"], unrelated).stdout.strip()
        check(
            execute([console, "--version"], unrelated).stdout.strip() == version,
            "Direct console launcher differs from isolated invocation",
        )
        probe = """
from importlib import metadata, resources
import hashlib, json, sys
from pathlib import Path
import archivist
from archivist import recovery, web
module = Path(archivist.__file__).resolve()
assert sys.flags.isolated and module.is_relative_to(Path(sys.prefix).resolve())
assets = {}
for name in ('app.css','app.js','index.html'):
    content = resources.files('archivist').joinpath('static',name).read_bytes()
    assert content and (web.STATIC/name).read_bytes() == content
    assets[name] = {'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
print(json.dumps({'module':str(module),'prefix':sys.prefix,'isolated':bool(sys.flags.isolated),
    'version':archivist.__version__,'package_version':archivist.__package_version__,
    'metadata_version':metadata.version(sys.argv[1]),'assets':assets,
    'helper_sha256':hashlib.sha256(Path(recovery.__file__).read_bytes()).hexdigest()}))
"""
        runtime = json.loads(
            execute([python, "-I", "-c", probe, inventory["name"]], unrelated).stdout
        )
        check(
            runtime["package_version"] == inventory["version"] == runtime["metadata_version"],
            "Installed package and distribution versions differ",
        )
        check(runtime["version"] == version, "Console and imported runtime versions differ")
        for name, evidence in runtime["assets"].items():
            check(
                evidence["sha256"] == inventory["files"]["archivist/static/" + name],
                "Installed resource differs from wheel: " + name,
            )
        check(
            runtime["helper_sha256"] == inventory["files"]["archivist/recovery.py"],
            "Installed recovery reader differs from wheel",
        )

        source, workspace, bundle = (
            working / name for name in ("input", "workspace", "archive-set")
        )
        source.mkdir()
        payloads = {
            "Projects/readme.txt": b"Installed wheel recovery fixture.\n",
            "Photos/caf\u00e9.txt": "Unicode filename, ordinary bytes.\n".encode("utf-8"),
            "binary.bin": bytes(range(256)) * 8,
        }
        for name, content in payloads.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (source / "Projects/empty").mkdir()
        global_options = ["--workspace", workspace, "--quiet", "--json"]
        transcript = []

        def cli(*arguments):
            result = json.loads(
                execute(command + global_options + list(arguments), unrelated).stdout
            )
            transcript.append({"command": str(arguments[0]), "result": result})
            return result

        scan = cli("scan", source, "--backend", "filesystem", "--hash-files")
        plan = cli(
            "plan",
            scan["snapshot_id"],
            "--minimum",
            "0",
            "--target",
            "1048576",
            "--maximum",
            "2097152",
            "--codec",
            "none",
        )
        built = cli("build", plan["id"], "--output", bundle, "--yes")
        verified = cli("verify", bundle)
        check(
            built["state"] == "COMPLETE" and verified["state"] == "CONTENTS_VERIFIED",
            "Installed CLI did not complete the archive flow",
        )
        check(
            sha256(bundle / "RESTORE.py") == runtime["helper_sha256"],
            "Archive did not copy the authoritative installed recovery reader",
        )
        index = json.loads((bundle / "ARCHIVE.json").read_text(encoding="utf-8"))
        namespace = index["sources"][0]["namespace"]
        shutil.rmtree(source)
        shutil.rmtree(workspace)
        shutil.rmtree(environment)
        restored = working / "restored-without-installation"
        recovery_result = json.loads(
            execute(
                [sys.executable, "-I", "-S", bundle / "RESTORE.py", bundle, "--to", restored],
                unrelated,
            ).stdout
        )
        for name, expected in payloads.items():
            check(
                (restored / namespace / name).read_bytes() == expected,
                "Standalone restored bytes differ: " + name,
            )
        check(
            (restored / namespace / "Projects/empty").is_dir(),
            "Standalone restore lost the empty directory",
        )
        actual_files = {
            path.relative_to(restored / namespace).as_posix()
            for path in (restored / namespace).rglob("*")
            if path.is_file()
        }
        check(actual_files == set(payloads), "Standalone restore produced unexpected files")
        check(
            recovery_result["state"] == "RESTORED_VERIFIED",
            "Standalone reader did not verify restore",
        )

        sdist_root = extract_sdist(sdist_path, working / "sdist")
        source_version = execute(
            [sys.executable, "-I", sdist_root / "archivist.py", "--version"], unrelated
        ).stdout.strip()
        check(source_version == version, "Source-distribution launcher version differs")
        launcher_check = "NOT_RUN_NON_POSIX"
        if os.name != "nt":
            env = clean_environment()
            env["ARCHIVIST_PYTHON"] = sys.executable
            launched = execute(
                [
                    "/bin/sh",
                    sdist_root / "launchers/CLI.sh",
                    "--workspace",
                    working / "sdist-workspace",
                    "--quiet",
                ],
                unrelated,
                input_text="status\nquit\n",
                env=env,
            )
            check(
                "Archivist " + version in launched.stdout
                and '"version": "' + version + '"' in launched.stdout,
                "Extracted portable shell launcher did not execute status",
            )
            launcher_check = "PASS_POSIX_SHELL"
        rebuilt_directory = report_directory / "wheel-from-sdist"
        rebuilt_directory.mkdir()
        rebuilt = execute(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys; from setuptools.build_meta import build_wheel; build_wheel(sys.argv[1])",
                rebuilt_directory,
            ],
            sdist_root,
        )
        (report_directory / "sdist-rebuild.log").write_text(
            rebuilt.stdout + rebuilt.stderr, encoding="utf-8"
        )
        rebuilt_wheels = list(rebuilt_directory.glob("*.whl"))
        check(len(rebuilt_wheels) == 1, "Source distribution did not rebuild one wheel")
        rebuilt_inventory = wheel_inventory(rebuilt_wheels[0])
        check(
            rebuilt_inventory == inventory,
            "Wheel rebuilt from sdist has different application contents",
        )
        (report_directory / "cli-transcript.json").write_text(
            json.dumps(transcript, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "state": "PASS",
            "python": sys.version,
            "platform": sys.platform,
            "product_version": version,
            "distribution_name": inventory["name"],
            "distribution_version": inventory["version"],
            "wheel_namespace": inventory["namespace"],
            "wheel_application_files": len(inventory["files"]),
            "runtime_dependencies": [],
            "isolated_installed_import": runtime,
            "console_entrypoint": "PASS",
            "installed_cli_flow": ["scan", "plan", "build", "verify"],
            "standalone_restore": {
                "state": recovery_result["state"],
                "files": len(payloads),
                "logical_bytes": sum(map(len, payloads.values())),
                "empty_directories": 1,
                "source_workspace_and_venv_removed": True,
                "interpreter_flags": ["-I", "-S"],
                "helper_matches_installed_wheel": True,
            },
            "sdist_bootstrap_from_unrelated_cwd": "PASS",
            "sdist_shell_launcher": launcher_check,
            "sdist_rebuilt_wheel_contents_equal": True,
            "limits": [
                "Host-platform checks only; no native Windows/macOS qualification",
                "Static assets read through importlib.resources; no browser rendering claim",
                "Plain TAR fixture; no tape device or hardware qualification",
                "Distribution byte reproducibility is not asserted by this checker",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build", action="store_true", help="Build from a disposable copy of --root first"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument(
        "--output", type=Path, required=True, help="New scratch output/report directory"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    check(
        not (output / "qualification.json").exists() and not (output / "wheel-from-sdist").exists(),
        "Qualification output already exists; choose a new directory",
    )
    if args.build:
        check(
            args.wheel is None and args.sdist is None,
            "--build cannot be combined with artifact paths",
        )
        wheel_path, sdist_path, tools = build_python_artifacts(args.root.resolve(), output)
    else:
        check(
            args.wheel is not None and args.sdist is not None,
            "Supply both --wheel and --sdist, or --build",
        )
        wheel_path, sdist_path, tools = args.wheel.resolve(), args.sdist.resolve(), None
    result = qualify(wheel_path, sdist_path, output)
    result["checked_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["build_tools"] = tools
    result["artifacts"] = [
        {"file": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (wheel_path, sdist_path)
    ]
    (output / "qualification.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
