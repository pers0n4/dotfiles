"""Isolated cache-maintenance tests; never launch a browser or use the network."""

import contextlib
import importlib.util
import io
import json
import os
import plistlib
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "browser-update.py"
SPEC = importlib.util.spec_from_file_location("browser_update", SCRIPT)
browser = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(browser)


class BrowserUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.root = self.home / ".agent-browser" / "browsers"
        self.root.mkdir(parents=True)
        self.cwd = self.home / "work" / "project"
        self.cwd.mkdir(parents=True)
        self.environment = mock.patch.dict(
            os.environ, {"HOME": str(self.home)}, clear=True
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.old = self.cache("9.0.0.1")
        self.new = self.cache("10.0.0.1")
        self.install_version = "10.0.0.1"
        self.install_code = 0
        self.install_output = None
        self.validation_code = 0
        self.validation_marker = True
        self.validation_timeout = False
        self.close_code = 0
        self.ps_output = "123 /usr/bin/idle\n"
        self.ps_code = 0
        self.commands = []
        self.command_patch = mock.patch.object(
            browser, "run_command", side_effect=self.command
        )
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)
        self.unregister_patch = mock.patch.object(browser, "unregister_app")
        self.unregister = self.unregister_patch.start()
        self.addCleanup(self.unregister_patch.stop)

    def cache(self, version):
        path = self.root / f"chrome-{version}"
        contents = path / browser.APP_NAME / "Contents"
        executable = contents / "MacOS" / browser.BINARY_NAME
        executable.parent.mkdir(parents=True)
        executable.write_text("fixture executable", encoding="utf-8")
        executable.chmod(0o700)
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump({"CFBundleShortVersionString": version}, stream)
        return path

    def executable(self, path):
        return path / browser.APP_NAME / "Contents" / "MacOS" / browser.BINARY_NAME

    def config(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"executablePath": value}), encoding="utf-8")

    def command(self, args, timeout=30, env=None):
        self.commands.append((args, timeout))
        if args == ["agent-browser", "install"]:
            output = self.install_output
            if output is None:
                output = f"Chrome {self.install_version} installed successfully\n"
            return subprocess.CompletedProcess(args, self.install_code, output, "")
        if args == ["ps", "-axo", "pid=,command="]:
            return subprocess.CompletedProcess(args, self.ps_code, self.ps_output, "")
        if "--executable-path" in args:
            self.assertEqual(args[args.index("--headed") + 1], "false")
            self.assertFalse(any(key.startswith("AGENT_BROWSER_") for key in env))
            profile = Path(args[args.index("--profile") + 1])
            self.assertNotEqual(profile, self.home)
            self.assertEqual(profile.parent, Path(env["HOME"]))
            config = Path(args[args.index("--config") + 1])
            self.assertEqual(json.loads(config.read_text()), {})
            if args[-1] == "close":
                return subprocess.CompletedProcess(args, self.close_code, "", "")
            if self.validation_timeout:
                raise browser.UnsafeState("command timed out")
            if args[-2] == "open":
                page = Path(unquote(urlparse(args[-1]).path))
                self.assertEqual(profile.parent, page.parent)
                self.assertEqual(timeout, 60)
                return subprocess.CompletedProcess(
                    args, self.validation_code, "opened", ""
                )
            self.assertEqual(args[-2:], ["get", "title"])
            page = profile.parent / "validation.html"
            output = (
                page.read_text().split("<title>")[1].split("</title>")[0]
                if self.validation_marker
                else "unrelated title"
            )
            return subprocess.CompletedProcess(args, self.validation_code, output, "")
        self.fail(f"unexpected command: {args}")

    def update(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            browser.update(self.root, self.cwd, **kwargs)

    def assert_all_present(self):
        self.assertTrue(self.old.is_dir())
        self.assertTrue(self.new.is_dir())

    def test_success_numeric_order_and_scoped_deletion(self):
        older = self.cache("2.0.0.1")
        future = self.cache("100.0.0.1")
        unrelated = self.root / "chromium-1.0"
        unrelated.mkdir()
        sentinel = (
            self.home
            / "Library"
            / "Caches"
            / "ms-playwright"
            / "chromium-1"
            / "sentinel"
        )
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("keep", encoding="utf-8")
        self.update()
        self.assertFalse(older.exists())
        self.assertFalse(self.old.exists())
        self.assertTrue(self.new.exists())
        self.assertTrue(future.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        launched = [
            args[args.index("--executable-path") + 1]
            for args, _ in self.commands
            if "--executable-path" in args and args[-2] == "open"
        ]
        self.assertEqual(launched, [self.executable(self.new)])
        self.assertEqual(self.commands[0][1], 300)

    def test_already_installed_output(self):
        self.install_output = "Chrome 10.0.0.1 is already installed\n"
        self.update()
        self.assertFalse(self.old.exists())

    def test_install_failure_never_validates_or_deletes(self):
        self.install_code = 1
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assert_all_present()
        self.assertEqual(len(self.commands), 1)
        self.unregister.assert_not_called()

    def test_unconfirmed_or_ambiguous_install_output_fails_closed(self):
        for output in (
            "done",
            "Chrome 9.0.0.1 installed successfully\nChrome 10.0.0.1 installed successfully",
        ):
            with self.subTest(output=output):
                self.install_output = output
                with self.assertRaises(browser.UnsafeState):
                    self.update()
                self.assert_all_present()

    def test_validation_failures_preserve_every_version(self):
        for mode in ("marker", "nonzero", "timeout"):
            with self.subTest(mode=mode):
                self.validation_marker = mode != "marker"
                self.validation_code = 1 if mode == "nonzero" else 0
                self.validation_timeout = mode == "timeout"
                with self.assertRaises(browser.UnsafeState):
                    self.update()
                self.assert_all_present()
                self.unregister.assert_not_called()

    def test_explicit_keep(self):
        self.update(keep=["9.0.0.1"])
        self.assert_all_present()

    def test_failed_browser_close_prevents_deletion(self):
        self.close_code = 1
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assert_all_present()

    def test_environment_pin(self):
        os.environ["AGENT_BROWSER_EXECUTABLE_PATH"] = str(self.executable(self.old))
        self.update()
        self.assert_all_present()

    def test_global_project_and_ancestor_config_pins(self):
        locations = (
            self.root.parent / "config.json",
            self.cwd / "agent-browser.json",
            self.cwd.parent / "agent-browser.json",
        )
        for location in locations:
            with self.subTest(location=location):
                # Resolve relative to the configuration file, not the process cwd.
                relative = os.path.relpath(self.executable(self.old), location.parent)
                self.config(location, relative)
                self.update()
                self.assert_all_present()
                location.unlink()

    def test_expanded_config_pin(self):
        os.environ["PINNED_BROWSER"] = str(self.executable(self.old))
        location = self.root.parent / "config.json"
        for reference in (
            "$PINNED_BROWSER",
            "~/.agent-browser/browsers/chrome-9.0.0.1/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ):
            with self.subTest(reference=reference):
                self.config(location, reference)
                self.update()
                self.assert_all_present()

    def test_custom_config_pin(self):
        location = self.cwd / "custom.json"
        self.config(location, str(self.executable(self.old)))
        os.environ["AGENT_BROWSER_CONFIG"] = "custom.json"
        self.update()
        self.assert_all_present()

    def test_external_reference_does_not_expand_cleanup_scope(self):
        external = self.home / "external-browser"
        external.write_text("keep", encoding="utf-8")
        self.config(self.cwd / "agent-browser.json", str(external))
        self.update()
        self.assertFalse(self.old.exists())
        self.assertEqual(external.read_text(encoding="utf-8"), "keep")

    def test_malformed_config_and_unknown_reference_types_fail_closed(self):
        location = self.cwd / "agent-browser.json"
        for contents in (
            "{",
            "[]",
            '{"executablePath": null}',
            '{"executablePath": 3}',
            '{"executablePath": "$UNDEFINED/browser"}',
            '{"executablePath": ""}',
        ):
            with self.subTest(contents=contents):
                location.write_text(contents, encoding="utf-8")
                with self.assertRaises(browser.UnsafeState):
                    self.update()
                self.assert_all_present()

    def test_unreadable_and_missing_custom_configuration_fail_closed(self):
        location = self.cwd / "agent-browser.json"
        location.mkdir()
        with self.assertRaises(browser.UnsafeState):
            self.update()
        location.rmdir()
        os.environ["AGENT_BROWSER_CONFIG"] = "missing.json"
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assert_all_present()

    def test_symlink_candidate_is_untouched(self):
        candidate = self.root / "chrome-8.0.0.1"
        candidate.symlink_to(self.old, target_is_directory=True)
        self.update(keep=["9.0.0.1"])
        self.assertTrue(candidate.is_symlink())
        self.assert_all_present()

    def test_symlink_root_is_refused_before_install(self):
        real = self.root.with_name("actual-browsers")
        self.root.rename(real)
        self.root.symlink_to(real, target_is_directory=True)
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assertTrue((real / self.old.name).exists())
        self.assertEqual(self.commands, [])

    def test_symlink_parent_is_refused_before_install(self):
        parent = self.root.parent
        real = self.home / "actual-agent-browser"
        parent.rename(real)
        parent.symlink_to(real, target_is_directory=True)
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assertTrue((real / "browsers" / self.old.name).exists())
        self.assertEqual(self.commands, [])

    def test_escaping_executable_is_not_a_deletion_candidate(self):
        executable = self.executable(self.old)
        outside = self.home / "outside-executable"
        executable.rename(outside)
        executable.symlink_to(outside)
        self.update()
        self.assert_all_present()
        self.assertTrue(outside.exists())

    def test_escaping_intermediate_directory_is_protected(self):
        contents = self.old / browser.APP_NAME / "Contents"
        outside = self.home / "outside-contents"
        contents.rename(outside)
        contents.symlink_to(outside, target_is_directory=True)
        self.update()
        self.assert_all_present()
        self.assertTrue(outside.exists())

    def test_mismatched_plist_and_missing_executable_are_skipped(self):
        info = self.old / browser.APP_NAME / "Contents" / "Info.plist"
        with info.open("wb") as stream:
            plistlib.dump({"CFBundleShortVersionString": "1.0"}, stream)
        self.update()
        self.assert_all_present()
        self.executable(self.new).unlink()
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assert_all_present()

    def test_running_old_browser_preserved(self):
        self.ps_output = f"123 {self.executable(self.old)} --headless\n"
        self.update()
        self.assert_all_present()

    def test_unknown_daemon_skips_all_deletion(self):
        for command in (
            "node /opt/agent-browser/dist/daemon.js",
            "agent-browser daemon",
            "agent-browser-darwin-arm64",
        ):
            with self.subTest(command=command):
                self.ps_output = f"123 {command}\n"
                self.update()
                self.assert_all_present()

    def test_parent_shell_text_and_own_process_are_not_daemons(self):
        self.ps_output = (
            "123 /bin/zsh -c 'node /opt/agent-browser/dist/daemon.js'\n"
            f"{os.getpid()} agent-browser daemon\n"
        )
        self.update()
        self.assertFalse(self.old.exists())

    def test_process_inspection_failure_preserves_all(self):
        self.ps_code = 1
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assert_all_present()

    def test_empty_or_malformed_process_inspection_fails_closed(self):
        for output in ("", "unparseable process output"):
            with self.subTest(output=output):
                self.ps_output = output
                with self.assertRaises(browser.UnsafeState):
                    self.update()
                self.assert_all_present()

    def test_process_recheck_before_deletion(self):
        original = self.command
        inspections = 0

        def command(args, timeout=30, env=None):
            nonlocal inspections
            if args[0] == "ps":
                inspections += 1
                if inspections >= 3:
                    self.ps_output = f"123 {self.executable(self.old)}\n"
            return original(args, timeout, env)

        with mock.patch.object(browser, "run_command", side_effect=command):
            self.update()
        self.assert_all_present()
        self.assertGreaterEqual(inspections, 3)

    def test_reference_recheck_after_unregister(self):
        self.unregister.side_effect = lambda app: self.config(
            self.cwd / "agent-browser.json", str(self.executable(self.old))
        )
        self.update()
        self.assert_all_present()

    def test_process_failure_after_unregister_preserves_candidate(self):
        def fail_inspection(app):
            self.ps_code = 1

        self.unregister.side_effect = fail_inspection
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assert_all_present()

    def test_candidate_replacement_after_unregister_is_not_deleted(self):
        moved = self.home / "moved-old-cache"

        def replace_candidate(app):
            self.old.rename(moved)
            self.cache("9.0.0.1")

        self.unregister.side_effect = replace_candidate
        self.update()
        self.assert_all_present()
        self.assertTrue(moved.exists())

    def test_validated_browser_disappearing_prevents_deletion(self):
        self.unregister.side_effect = lambda app: self.new.rename(
            self.home / "moved-new-cache"
        )
        with self.assertRaises(browser.UnsafeState):
            self.update()
        self.assertTrue(self.old.is_dir())

    def test_dry_run_still_installs_and_validates(self):
        self.update(dry_run=True)
        self.assert_all_present()
        self.assertTrue(any("--executable-path" in args for args, _ in self.commands))
        self.unregister.assert_not_called()

    def test_unregister_failure_preserves_candidate(self):
        self.unregister.side_effect = browser.UnsafeState("unregister failed")
        self.update()
        self.assert_all_present()

    def test_unregister_exact_path_only(self):
        self.unregister_patch.stop()
        app = self.old / browser.APP_NAME
        for dump, expected_unregister in (
            (f"path: {app}.other\n", False),
            (f"path: {app}.other (0x6870)\n", False),
            (f"    path:                       {app}\n", True),
            (f"path: {app} (0x6870)\n", True),
        ):
            with self.subTest(dump=dump):
                responses = [
                    subprocess.CompletedProcess([], 0, dump, ""),
                    subprocess.CompletedProcess([], 0, "", ""),
                ]
                with (
                    mock.patch.object(browser.sys, "platform", "darwin"),
                    mock.patch.object(
                        browser, "run_command", side_effect=responses
                    ) as command,
                ):
                    browser.unregister_app(app)
                    self.assertEqual(
                        command.call_count, 2 if expected_unregister else 1
                    )
                    if expected_unregister:
                        self.assertEqual(
                            command.call_args.args[0], [browser.LSREGISTER, "-u", app]
                        )

    def test_real_unregister_nonzero_raises(self):
        self.unregister_patch.stop()
        app = self.old / browser.APP_NAME
        responses = [
            subprocess.CompletedProcess([], 0, f"path: {app} (0x6870)\n", ""),
            subprocess.CompletedProcess([], 1, "", ""),
        ]
        with (
            mock.patch.object(browser.sys, "platform", "darwin"),
            mock.patch.object(browser, "run_command", side_effect=responses),
            self.assertRaises(browser.UnsafeState),
        ):
            browser.unregister_app(app)

    def test_nonblocking_lock_contention_prevents_install(self):
        with (
            mock.patch.object(browser.fcntl, "flock", side_effect=BlockingIOError),
            self.assertRaises(browser.UnsafeState),
        ):
            self.update()
        self.assertEqual(self.commands, [])
        self.assert_all_present()

    def test_timeout_kills_and_reaps_process_group(self):
        self.command_patch.stop()
        process = mock.Mock(pid=321)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["fixture"], 1),
            ("", ""),
        ]
        with (
            mock.patch.object(
                browser.subprocess, "Popen", return_value=process
            ) as popen,
            mock.patch.object(browser.os, "killpg") as killpg,
            self.assertRaises(browser.UnsafeState),
        ):
            browser.run_command(["fixture"], timeout=1)
        killpg.assert_called_once_with(321, signal.SIGKILL)
        self.assertEqual(process.communicate.call_count, 2)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
