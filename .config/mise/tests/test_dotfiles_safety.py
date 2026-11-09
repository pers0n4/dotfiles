"""Native mise dotfiles preflight integration tests; all writes use a temp HOME."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check-dotfiles.py"


class DotfilesSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mise = shutil.which("mise")
        if cls.mise is None:
            raise unittest.SkipTest("native mise integration tests require mise on PATH")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.repository = self.home / "iCloud" / "git" / "dotfiles"
        self.mise_config = self.repository / ".config" / "mise"
        (self.mise_config / "conf.d").mkdir(parents=True)
        (self.mise_config / "scripts").mkdir()
        shutil.copyfile(CHECKER, self.mise_config / "scripts" / CHECKER.name)
        (self.home / ".config").mkdir()
        (self.home / ".config" / "mise").symlink_to(
            self.mise_config, target_is_directory=True
        )
        self.cwd = self.root / "outside-repository"
        self.cwd.mkdir()
        self.environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": os.environ.get("PATH", os.defpath),
        }

    def configure(self, entries):
        lines = [
            "[bootstrap.hooks]",
            "pre-dotfiles = 'python3 \"$HOME/iCloud/git/dotfiles/.config/mise/scripts/check-dotfiles.py\"'",
        ]
        for target, source, mode in entries:
            lines.extend(
                [
                    "",
                    f"[dotfiles.{json.dumps(str(target))}]",
                    f"source = {json.dumps(str(source))}",
                    f"mode = {json.dumps(mode)}",
                ]
            )
            if mode == "symlink":
                lines.append("relative = false")
        (self.mise_config / "conf.d" / "dotfiles.toml").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def apply(self):
        return subprocess.run(
            [self.mise, "dot", "apply", "--force", "--yes"],
            cwd=self.cwd,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=45,
        )

    def source_file(self, relative, contents=b"upstream bytes\n"):
        source = self.repository / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(contents)
        return source

    def assert_refusal(self, result, reason):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mise dotfiles safety check refused apply:", result.stderr)
        self.assertIn(reason, result.stderr)

    def test_force_apply_is_idempotent_and_preserves_symlink_source(self):
        contents = b"upstream bytes\x00\xff\n"
        source = self.source_file(".config/source", contents)
        target = self.home / ".deployed"
        self.configure([("~/.deployed", source, "symlink")])

        for _ in range(2):
            result = self.apply()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), source.resolve())
            self.assertEqual(source.read_bytes(), contents)

    def test_copy_accepts_valid_internal_source_symlink_and_preserves_bytes(self):
        contents = bytes(range(256))
        source = self.source_file(".agents/AGENTS.md", contents)
        linked_source = self.repository / ".gjc" / "agent" / "AGENTS.md"
        linked_source.parent.mkdir(parents=True)
        linked_source.symlink_to("../../.agents/AGENTS.md")
        target = self.home / ".copied"
        self.configure([("~/.copied", linked_source, "copy")])

        result = self.apply()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), contents)
        self.assertEqual(source.read_bytes(), contents)

    def test_directory_parent_alias_into_repository_is_rejected_before_apply(self):
        source = self.source_file(".config/source")
        managed_parent = self.repository / "managed-targets"
        managed_parent.mkdir()
        aliased_parent = self.home / "target-parent"
        aliased_parent.symlink_to(managed_parent, target_is_directory=True)
        target = aliased_parent / "created"
        self.configure([(target, source, "symlink")])

        result = self.apply()

        self.assert_refusal(
            result, "a target parent resolves into the canonical iCloud repository"
        )
        self.assertFalse(target.exists())
        self.assertFalse((managed_parent / "created").exists())

    def test_git_ignore_directory_alias_cannot_overwrite_its_source(self):
        contents = b"the upstream ignore source must remain unchanged\n"
        source = self.source_file(".config/git/ignore", contents)
        source_directory = source.parent
        target_directory = self.home / ".config" / "git"
        target_directory.symlink_to(source_directory, target_is_directory=True)
        target = target_directory / "ignore"
        self.configure([("~/.config/git/ignore", source, "symlink")])

        result = self.apply()

        self.assert_refusal(
            result, "a target parent resolves into the canonical iCloud repository"
        )
        self.assertTrue(target_directory.is_symlink())
        self.assertEqual(source.read_bytes(), contents)
        self.assertEqual(target.read_bytes(), contents)

    def test_loaded_config_overlay_source_is_checked_before_apply(self):
        good_source = self.source_file(".config/good-source")
        outside_source = self.root / "outside-source"
        outside_source.write_bytes(b"outside the canonical repository\n")
        good_target = self.home / ".a-good"
        outside_target = self.home / ".z-outside"
        self.configure([("~/.a-good", good_source, "symlink")])
        (self.mise_config / "conf.d" / "zz-overlay.toml").write_text(
            "\n".join(
                [
                    '[dotfiles."~/.z-outside"]',
                    f"source = {json.dumps(str(outside_source))}",
                    'mode = "copy"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.apply()

        self.assert_refusal(
            result, "a source resolves outside the canonical iCloud repository"
        )
        self.assertFalse(good_target.exists())
        self.assertFalse(outside_target.exists())

    def test_template_expression_in_source_path_is_rejected(self):
        source = self.repository / ".config" / "{{ unexpanded }}"
        target = self.home / ".templated-source"
        self.configure([("~/.templated-source", source, "symlink")])

        result = self.apply()

        self.assert_refusal(result, "source contains an unsupported template expression")
        self.assertFalse(target.exists())

    def assert_bad_source_stops_all_entries(self, bad_source):
        good_source = self.source_file(".config/good-source")
        first_target = self.home / ".a-first"
        last_target = self.home / ".z-last"
        self.configure(
            [
                ("~/.a-first", good_source, "symlink"),
                ("~/.z-last", bad_source, "copy"),
            ]
        )

        result = self.apply()

        self.assert_refusal(result, "a source is missing or has a symlink loop")
        self.assertFalse(first_target.exists())
        self.assertFalse(last_target.exists())

    def test_missing_source_stops_all_entries_before_any_write(self):
        missing = self.repository / ".config" / "missing-source"
        self.assert_bad_source_stops_all_entries(missing)

    def test_loop_source_stops_all_entries_before_any_write(self):
        first = self.repository / ".config" / "loop-a"
        second = self.repository / ".config" / "loop-b"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.symlink_to(second.name)
        second.symlink_to(first.name)
        self.assert_bad_source_stops_all_entries(first)

    def test_copy_hardlink_alias_to_source_is_rejected(self):
        contents = b"shared inode must not be copied over itself\n"
        source = self.source_file(".config/source", contents)
        target = self.home / ".hardlink-copy"
        os.link(source, target)
        self.configure([("~/.hardlink-copy", source, "copy")])

        result = self.apply()

        self.assert_refusal(result, "a target hard-links to a registered source")
        self.assertTrue(os.path.samefile(source, target))
        self.assertEqual(source.read_bytes(), contents)


if __name__ == "__main__":
    unittest.main()
