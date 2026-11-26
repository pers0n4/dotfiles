#!/usr/bin/env python3
"""Fail-closed preflight for native mise dotfiles deployment.

Requires Python 3.11 or newer for the standard-library ``tomllib`` module.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    print("dotfiles safety check requires Python 3.11 or newer", file=sys.stderr)
    raise SystemExit(1)


class SafetyError(Exception):
    """A condition that makes it unsafe to run native dotfiles apply."""


def _within(path, parent):
    return path == parent or parent in path.parents


def _home_directory():
    home_value = os.environ.get("HOME")
    if not home_value:
        raise SafetyError("HOME is unavailable")
    home = Path(home_value)
    if not home.is_absolute():
        raise SafetyError("HOME is not an absolute path")
    try:
        return home.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise SafetyError("HOME cannot be resolved") from None


def _repository_root(home):
    try:
        root = (home / "iCloud" / "git" / "dotfiles").resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise SafetyError("canonical iCloud dotfiles repository is unavailable") from None
    if not root.is_dir():
        raise SafetyError("canonical iCloud dotfiles repository is not a directory")
    return root


def _expand_absolute_path(value, home, description):
    if not isinstance(value, str) or not value:
        raise SafetyError(f"{description} is missing or invalid")
    if any(marker in value for marker in ("{{", "{%", "{#")):
        raise SafetyError(f"{description} contains an unsupported template expression")
    if "\0" in value or any(character in value for character in "*?["):
        raise SafetyError(f"{description} uses an unsupported path pattern")
    if value == "~":
        return home
    if value.startswith("~/"):
        relative = value[2:]
        if not relative or relative.startswith("/"):
            raise SafetyError(f"{description} is not a valid home-relative path")
        return home / relative
    path = Path(value)
    if not path.is_absolute():
        raise SafetyError(f"{description} is not absolute or home-relative")
    return path


def _mise_executable():
    mise = shutil.which("mise")
    if mise is None:
        raise SafetyError("mise is not available on PATH")
    return mise


def _loaded_config_paths(mise):
    # config ls reports loaded files in precedence order. Its JSON also lists
    # this config's `.env` and `.env.local` dotenv files; only TOML configs can
    # declare [dotfiles], and unknown non-TOML paths fail closed.
    # Avoid `mise dot status --json`: status renders dotfile template entries,
    # whose `exec()` functions may have side effects before this guard.
    try:
        result = subprocess.run(
            [mise, "config", "ls", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise SafetyError("could not inspect loaded mise configuration") from None
    if result.returncode != 0:
        raise SafetyError("mise could not list its loaded configuration")
    try:
        configs = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raise SafetyError("mise returned invalid configuration metadata") from None
    if not isinstance(configs, list) or not configs:
        raise SafetyError("mise returned no loaded configuration files")

    paths = []
    seen = set()
    for config in configs:
        if not isinstance(config, dict):
            raise SafetyError("mise returned invalid configuration metadata")
        path_value = config.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise SafetyError("mise returned invalid configuration metadata")
        path = Path(path_value)
        if not path.is_absolute():
            raise SafetyError("a loaded mise configuration path is not absolute")
        if path.name in {".env", ".env.local"}:
            continue
        if path.suffix.lower() != ".toml":
            raise SafetyError("mise returned an unsupported non-TOML config path")
        try:
            canonical_path = path.resolve(strict=True)
            if not canonical_path.is_file():
                raise SafetyError("a loaded mise configuration is not a file")
            with canonical_path.open("rb"):
                pass
        except SafetyError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise SafetyError("a loaded mise configuration is unreadable") from None
        if canonical_path not in seen:
            seen.add(canonical_path)
            paths.append(canonical_path)
    if not paths:
        raise SafetyError("mise returned no loaded TOML configuration files")
    return paths


def _merge_entry(key, declaration):
    target, _, edit_id = key.rpartition("/")
    merge = declaration["merge"]
    if (
        set(declaration) != {"source", "merge"}
        or (merge is not True and merge != "missing")
        or not target.endswith(".json")
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", edit_id)
    ):
        raise SafetyError("unsupported dotfile merge; expected a JSON target, edit id and source")
    return target, declaration["source"], "merge"


def _effective_entries(config_paths):
    # `mise config ls` returns files from lowest to highest precedence. The
    # later declaration for a target replaces the earlier declaration, as mise
    # does for native [dotfiles] entries.
    declarations = {}
    active = []
    for path in config_paths:
        try:
            with path.open("rb") as stream:
                config = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            raise SafetyError("a loaded mise configuration cannot be parsed") from None
        if not isinstance(config, dict):
            raise SafetyError("a loaded mise configuration has an invalid shape")
        if "dotfile_groups" in config:
            raise SafetyError("dotfile groups are not covered by this safety check")
        dotfiles = config.get("dotfiles", {})
        if not isinstance(dotfiles, dict):
            raise SafetyError("a loaded [dotfiles] table has an invalid shape")
        for target, declaration in dotfiles.items():
            if not isinstance(target, str) or not isinstance(declaration, dict):
                raise SafetyError("a native dotfile declaration has an invalid shape")
            # Edits and whole-file entries have separate precedence in mise.
            # Validate every merge declaration, including ones later shadowed.
            if "merge" in declaration:
                active.append(_merge_entry(target, declaration))
            else:
                declarations[target] = declaration

    for target, declaration in declarations.items():
        enabled = declaration.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SafetyError("a native dotfile has an invalid enabled flag")
        if not enabled:
            continue
        if set(declaration) - {"source", "mode", "relative", "enabled"}:
            raise SafetyError("a native dotfile uses unsupported deployment options")
        mode = declaration.get("mode")
        if not isinstance(mode, str) or mode not in ("symlink", "copy", "symlink-each"):
            raise SafetyError("a native dotfile uses an unsupported deployment mode")
        if not isinstance(declaration.get("relative", False), bool):
            raise SafetyError("a native dotfile has an invalid relative setting")
        active.append((target, declaration.get("source"), mode))
    return active


def _validate_source(source, repository):
    try:
        canonical_source = source.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise SafetyError("a source is missing or has a symlink loop") from None
    if not _within(canonical_source, repository):
        raise SafetyError("a source resolves outside the canonical iCloud repository")
    try:
        source_stat = canonical_source.stat()
        if not stat.S_ISREG(source_stat.st_mode):
            raise SafetyError("a source is not a regular file")
        with canonical_source.open("rb"):
            pass
    except SafetyError:
        raise
    except (OSError, ValueError):
        raise SafetyError("a source is unreadable") from None
    return canonical_source, source_stat


def _target_slot(target_value, home):
    target = _expand_absolute_path(target_value, home, "target")
    if target == home or not target.name or target.name in {".", ".."}:
        raise SafetyError("a native dotfile target is not a file path")
    try:
        # Resolve the parent only. A target leaf symlink is an intended part of
        # an already-deployed symlink entry and must not be followed here.
        parent = target.parent.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        raise SafetyError("a target parent cannot be resolved") from None
    return parent / target.name


def _require_tree_directory(target):
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(mode):
        raise SafetyError("a symlink-each target directory is not a real directory")


def _expand_entries(target_value, source_value, mode, home, repository):
    source = _expand_absolute_path(source_value, home, "source")
    target = _target_slot(target_value, home)
    if mode == "merge":
        if (
            ".." in source.parts
            or _expand_absolute_path(target_value, home, "target") != target
            or not _within(target, home)
        ):
            raise SafetyError("a merge target must be under HOME without parent aliases")
    if mode != "symlink-each":
        yield target, source, mode
        return

    declared_target = _expand_absolute_path(target_value, home, "target")
    if ".." in source.parts or declared_target != target:
        raise SafetyError("a symlink-each path uses parent traversal or a target parent link")

    try:
        source = source.resolve(strict=True)
        if not _within(source, repository) or not source.is_dir():
            raise SafetyError("a symlink-each source is not a directory in the repository")
        # mise can also prune stale links absent from the current source tree.
        if (not _within(target, home) or target == home
                or _within(target, repository) or _within(repository, target)):
            raise SafetyError("a symlink-each target tree must be under HOME and disjoint from the repository")
        if any(p.exists() and p.samefile(repository) for p in (target, *target.parents)):
            raise SafetyError("a symlink-each target aliases the repository")
        if target.exists() and any(target.samefile(p) for p in repository.parents):
            raise SafetyError("a symlink-each target aliases a repository ancestor")

        pending = [(source, target)]
        while pending:
            directory, destination = pending.pop()
            _require_tree_directory(destination)
            for child in directory.iterdir():
                leaf = destination / child.name
                if stat.S_ISDIR(child.lstat().st_mode):
                    pending.append((child, leaf))
                else:
                    yield leaf, child, "symlink"
    except (OSError, RuntimeError, ValueError):
        raise SafetyError("a symlink-each tree cannot be inspected safely") from None


def validate():
    home = _home_directory()
    repository = _repository_root(home)
    config_paths = _loaded_config_paths(_mise_executable())
    declarations = _effective_entries(config_paths)

    entries = []
    source_paths = set()
    source_stats = []
    for target_value, source_value, mode in declarations:
        for target, source_path, leaf_mode in _expand_entries(
            target_value, source_value, mode, home, repository
        ):
            source, source_stat = _validate_source(source_path, repository)
            entries.append((target, source, leaf_mode))
            source_paths.add(source)
            source_stats.append(source_stat)

    whole_file_targets = {target for target, _, mode in entries if mode != "merge"}
    for target, _source, mode in entries:
        if _within(target, repository):
            raise SafetyError("a target parent resolves into the canonical iCloud repository")
        if target in source_paths:
            raise SafetyError("a target aliases a registered source")
        try:
            target_stat = target.lstat()
            if mode == "merge":
                if not stat.S_ISREG(target_stat.st_mode):
                    raise SafetyError("a merge target must be an existing regular file")
                if any(parent.samefile(repository) for parent in target.parents):
                    raise SafetyError("a merge target aliases the canonical iCloud repository")
                if target in whole_file_targets:
                    raise SafetyError("a merge target also has a whole-file deployment")
        except FileNotFoundError:
            if mode == "merge":
                # mise would create a partial keymap without Herdr defaults.
                raise SafetyError("a merge target must be an existing regular file") from None
            continue
        except OSError:
            raise SafetyError("a target cannot be inspected safely") from None
        if not (stat.S_ISREG(target_stat.st_mode) or stat.S_ISLNK(target_stat.st_mode)):
            raise SafetyError("a target is not a regular file or symlink")
        if stat.S_ISREG(target_stat.st_mode) and any(
            target_stat.st_dev == source_stat.st_dev
            and target_stat.st_ino == source_stat.st_ino
            for source_stat in source_stats
        ):
            raise SafetyError("a target hard-links to a registered source")


def main():
    try:
        validate()
    except SafetyError as error:
        print(f"mise dotfiles safety check refused apply: {error}", file=sys.stderr)
        return 1
    print("mise dotfiles safety check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
