#!/usr/bin/env python3
"""Install and validate Chrome for Testing before scoped cache maintenance."""

import argparse
import contextlib
import fcntl
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from xml.parsers.expat import ExpatError

VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+", re.ASCII)
CACHE_NAME = re.compile(r"chrome-([0-9]+(?:\.[0-9]+)+)", re.ASCII)
APP_NAME = "Google Chrome for Testing.app"
BINARY_NAME = "Google Chrome for Testing"
LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
)


class UnsafeState(Exception):
    """A prerequisite for safe maintenance could not be established."""


def run_command(args, timeout=30, env=None):
    """Capture commands privately; kill and reap the process group on timeout."""
    process = subprocess.Popen(
        [str(arg) for arg in args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise UnsafeState("command timed out") from None
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def check_root(root):
    # Both components must be real directories, including before installation.
    for path in (root.parent, root):
        if path.is_symlink():
            raise UnsafeState("unsafe cache root")
        if path.exists() and not path.is_dir():
            raise UnsafeState("unsafe cache root")


@contextlib.contextmanager
def maintenance_lock(root):
    check_root(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    descriptor = os.open(root.parent / "browser-update.lock", flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise UnsafeState("unsafe lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UnsafeState("maintenance already running") from None
        yield
    finally:
        os.close(descriptor)


def cache_info(path, root):
    """Return (version, executable, app, identity) for the known macOS layout."""
    check_root(root)
    match = CACHE_NAME.fullmatch(path.name)
    if not match or path.parent != root or path.is_symlink() or not path.is_dir():
        return None
    try:
        resolved = path.resolve(strict=True)
        if resolved.parent != root.resolve(strict=True):
            return None
        app = path / APP_NAME
        info = app / "Contents" / "Info.plist"
        executable = app / "Contents" / "MacOS" / BINARY_NAME
        for item in (app, info, executable):
            if item.is_symlink() or not item.resolve(strict=True).is_relative_to(
                resolved
            ):
                return None
        if not app.is_dir() or not info.is_file() or not executable.is_file():
            return None
        if not os.access(executable, os.X_OK):
            return None
        with info.open("rb") as stream:
            metadata = plistlib.load(stream)
        if (
            not isinstance(metadata, dict)
            or metadata.get("CFBundleShortVersionString") != match[1]
        ):
            return None
        identity = path.stat()
        return match[1], executable, app, (identity.st_dev, identity.st_ino)
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException, ExpatError):
        return None


def discover(root):
    check_root(root)
    if not root.exists():
        return []
    entries = []
    for path in root.iterdir():
        info = cache_info(path, root)
        if info is not None:
            entries.append((path, info))
    return sorted(
        entries,
        key=lambda entry: (tuple(map(int, entry[1][0].split("."))), entry[1][0]),
    )


def validate_browser(executable):
    marker = "browser-update-" + uuid.uuid4().hex
    # Short paths stay within macOS Unix socket limits for the scratch daemon.
    with tempfile.TemporaryDirectory(prefix="bu-", dir="/tmp") as temporary:
        temporary = Path(temporary)
        page = temporary / "validation.html"
        page.write_text(
            f"<!doctype html><title>{marker}</title><p>{marker}</p>", encoding="utf-8"
        )
        config = temporary / "config.json"
        config.write_text("{}", encoding="utf-8")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AGENT_BROWSER_")
        }
        environment["HOME"] = str(temporary)
        command = [
            "agent-browser",
            "--config",
            config,
            "--session",
            "bu" + uuid.uuid4().hex[:10],
            "--executable-path",
            executable,
            "--profile",
            temporary / "profile",
            "--headed",
            "false",
        ]
        # Use the CLI's CDP navigation/close lifecycle, not --dump-dom teardown.
        try:
            opened = run_command(
                command + ["open", page.as_uri()], timeout=60, env=environment
            )
            if opened.returncode != 0:
                raise UnsafeState("browser launch failed")
            title = run_command(command + ["get", "title"], timeout=30, env=environment)
            if title.returncode != 0 or title.stdout.strip() != marker:
                raise UnsafeState("browser validation failed")
        finally:
            closed = run_command(command + ["close"], timeout=30, env=environment)
            if closed.returncode != 0:
                raise UnsafeState("browser close failed")


def reference_path(value, base):
    if not isinstance(value, str) or not value:
        raise UnsafeState("invalid executable reference")
    expanded = os.path.expanduser(os.path.expandvars(value))
    if not expanded or "$" in expanded or expanded.startswith("~"):
        raise UnsafeState("unresolved executable reference")
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path


def pin_from_path(value, base, root):
    path = reference_path(value, base)
    # Keep lexical cache references too, even when an internal link escapes.
    pins = set()
    for reference in (Path(os.path.abspath(path)), path.resolve()):
        try:
            relative = reference.relative_to(root.resolve())
        except ValueError:
            continue
        if relative.parts:
            match = CACHE_NAME.fullmatch(relative.parts[0])
            if match:
                pins.add(match[1])
    return pins


def referenced_versions(root, cwd):
    pins = set()
    environment_path = os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH")
    if environment_path is not None:
        pins.update(pin_from_path(environment_path, cwd, root))
    configs = {root.parent / "config.json"}
    configs.update(parent / "agent-browser.json" for parent in (cwd, *cwd.parents))
    custom_config = os.environ.get("AGENT_BROWSER_CONFIG")
    if custom_config is not None:
        custom_path = reference_path(custom_config, cwd)
        if not custom_path.exists():
            raise UnsafeState("missing browser configuration")
        configs.add(custom_path)
    for config in configs:
        if not os.path.lexists(config):
            continue
        try:
            with config.open(encoding="utf-8") as stream:
                contents = json.load(stream)
        except (OSError, ValueError):
            raise UnsafeState("unreadable browser configuration") from None
        if not isinstance(contents, dict):
            raise UnsafeState("invalid browser configuration")
        if "executablePath" in contents:
            pins.update(pin_from_path(contents["executablePath"], config.parent, root))
    return pins


def process_references(root, entries):
    result = run_command(["ps", "-axo", "pid=,command="])
    if result.returncode != 0 or not result.stdout.strip():
        raise UnsafeState("process inspection failed")
    pins = set()
    unknown_daemon = False
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            raise UnsafeState("invalid process inspection")
        if int(fields[0]) == os.getpid():
            continue
        command = fields[1]
        referenced = {info[0] for path, info in entries if str(path) in command}
        pins.update(referenced)
        try:
            arguments = shlex.split(command)
        except ValueError:
            # ps does not preserve quoting; only inspect the executable token.
            arguments = command.split()
        if not arguments:
            continue
        program = Path(arguments[0]).name
        daemon = program in {"agent-browser", "agent-browser-daemon"} or bool(
            re.fullmatch(
                r"agent-browser-(?:darwin|linux|win32)-[A-Za-z0-9_-]+", program
            )
        )
        if program in {"node", "bun", "nodejs"}:
            daemon = any(
                "/agent-browser/" in argument
                and Path(argument).name in {"daemon.js", "daemon.mjs"}
                for argument in arguments[1:]
            )
        if daemon and not referenced:
            unknown_daemon = True
    return pins, unknown_daemon


def unregister_app(app):
    if sys.platform != "darwin":
        return
    result = run_command([LSREGISTER, "-dump"])
    if result.returncode != 0:
        raise UnsafeState("application registration inspection failed")
    registered = any(
        label.strip() == "path"
        and re.sub(r"\s+\(0x[0-9a-fA-F]+\)$", "", value.strip()) == str(app)
        for label, separator, value in (
            line.partition(":") for line in result.stdout.splitlines()
        )
        if separator
    )
    if registered and run_command([LSREGISTER, "-u", app]).returncode != 0:
        raise UnsafeState("application unregister failed")


def update(root, cwd, keep=(), dry_run=False):
    with maintenance_lock(root):
        installation = run_command(["agent-browser", "install"], timeout=300)
        if installation.returncode != 0:
            raise UnsafeState("browser installation failed")
        output = re.sub(
            r"\x1b\[[0-9;]*m", "", installation.stdout + "\n" + installation.stderr
        )
        installed = set(
            re.findall(
                r"\bChrome ([0-9]+(?:\.[0-9]+)+) (?:is already installed|installed successfully)\b",
                output,
            )
        )
        if len(installed) != 1:
            raise UnsafeState("installed browser version not confirmed")
        installed_version = installed.pop()
        entries = discover(root)
        selected = [entry for entry in entries if entry[1][0] == installed_version]
        if not selected:
            raise UnsafeState("installed browser cache is invalid")
        validated_path, validated = selected[0]
        validate_browser(validated[1])
        if cache_info(validated_path, root) != validated:
            raise UnsafeState("validated browser changed")
        pins = set(keep) | {validated[0]} | referenced_versions(root, cwd)
        running, unknown = process_references(root, entries)
        pins.update(running)
        print(f"keep {validated[0]} (validated)")
        for path, info in entries:
            version = info[0]
            if tuple(map(int, version.split("."))) >= tuple(
                map(int, validated[0].split("."))
            ):
                if version != validated[0]:
                    print(f"keep {version} (not older)")
                continue
            # Refresh mutable references and filesystem identity for every removal.
            pins.update(referenced_versions(root, cwd))
            running, current_unknown = process_references(root, entries)
            pins.update(running)
            if unknown or current_unknown or version in pins:
                print(f"keep {version} (referenced or active)")
                continue
            if cache_info(path, root) != info:
                print(f"keep {version} (changed or unsafe)")
                continue
            if dry_run:
                print(f"would delete {version}")
                continue
            try:
                unregister_app(info[2])
            except (UnsafeState, OSError):
                print(f"keep {version} (unregister failed)")
                continue
            # Unregistration may take time; do not rely on the earlier snapshot.
            running, current_unknown = process_references(root, entries)
            pins.update(referenced_versions(root, cwd))
            if (
                current_unknown
                or version in running
                or version in pins
                or cache_info(path, root) != info
            ):
                print(f"keep {version} (changed or active)")
                continue
            if cache_info(validated_path, root) != validated:
                raise UnsafeState("validated browser changed")
            shutil.rmtree(path)
            print(f"deleted {version}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="install and validate without deleting"
    )
    parser.add_argument("--keep", action="append", default=[], metavar="VERSION")
    args = parser.parse_args(argv)
    if any(VERSION.fullmatch(version) is None for version in args.keep):
        parser.error("--keep requires a numeric dotted version")
    try:
        update(
            Path.home() / ".agent-browser" / "browsers",
            Path.cwd(),
            args.keep,
            args.dry_run,
        )
    except (UnsafeState, OSError, ValueError):
        print(
            "browser maintenance stopped; no further versions deleted", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
