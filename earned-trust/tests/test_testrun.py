import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import repo_with
from trust import testrun

FIX = "ClosedGenericStruct_FromMetadataReference"
UNKEYED = FIX + "_UnkeyedMember"


class Verdict(unittest.TestCase):
    def test_passing_with_and_failing_without_proves_the_change(self):
        v = testrun.verdict("passed", "failed")
        self.assertTrue(v["proves_fix"])
        self.assertIn("tests the change", v["why"])

    def test_a_test_of_new_code_proves_it_when_it_no_longer_compiles_without_it(self):
        self.assertTrue(testrun.verdict("passed", "does not compile")["proves_fix"])

    def test_passing_both_ways_does_not_test_the_change(self):
        v = testrun.verdict("passed", "passed")
        self.assertFalse(v["proves_fix"])
        self.assertIn("does not test the change", v["why"])

    def test_a_failing_or_missing_test_proves_nothing(self):
        for here in ("failed", "does not compile", "not found in output"):
            self.assertFalse(testrun.verdict(here, "failed")["proves_fix"], here)


class DotnetOutput(unittest.TestCase):
    def test_a_name_that_prefixes_another_is_not_confused_with_it(self):
        out = f"  Passed GenericsFormatterTests.{UNKEYED} [83 ms]\n  Failed GenericsFormatterTests.{FIX} [3 ms]"
        self.assertEqual(testrun.dotnet_results(out, [FIX, UNKEYED]), {FIX: "failed", UNKEYED: "passed"})

    def test_a_build_failure_means_nothing_compiled(self):
        self.assertEqual(testrun.dotnet_results("Build FAILED.\n", [FIX]), {FIX: "does not compile"})

    def test_a_test_missing_from_the_output_is_not_a_pass(self):
        self.assertEqual(testrun.dotnet_results("Total tests: 0", [FIX]), {FIX: "not found in output"})


class JunitReports(unittest.TestCase):
    def reports(self, cases):
        folder = Path(tempfile.mkdtemp())
        (folder / "TEST-junit-jupiter.xml").write_text(f"<testsuite>{cases}</testsuite>")
        return folder

    def test_pass_failure_error_and_skip_are_told_apart(self):
        folder = self.reports('<testcase name="ok()"/><testcase name="bad()"><failure/></testcase>'
                              '<testcase name="boom()"><error/></testcase><testcase name="later()"><skipped/></testcase>')
        self.assertEqual(testrun.junit_results(folder, ["ok", "bad", "boom", "later"]),
                         {"ok": "passed", "bad": "failed", "boom": "failed", "later": "skipped"})

    def test_parameters_in_the_reported_name_are_ignored(self):
        self.assertEqual(testrun.junit_results(self.reports('<testcase name="t(int, String)"/>'), ["t"]), {"t": "passed"})

    def test_no_reports_means_not_found(self):
        self.assertEqual(testrun.junit_results(Path(tempfile.mkdtemp()), ["t"]), {"t": "not found in output"})


class Checkout(unittest.TestCase):
    def setUp(self):
        self.repo = str(repo_with({"src/A.java": "a\nb\n", "tests/T.java": "t\n"},
                                  {"src/A.java": "a\nB\n", "src/New.java": "new\n", "tests/T.java": "t2\n"}))
        self.work = mock.patch.object(testrun, "WORK", Path(tempfile.mkdtemp()))
        self.work.start()
        self.addCleanup(self.work.stop)

    def test_without_the_change_the_source_is_reverted_and_added_files_are_gone(self):
        tree = Path(testrun.checkout(self.repo, "HEAD", "w", ("HEAD~1", "src")))
        self.assertEqual((tree / "src/A.java").read_text(), "a\nb\n")
        self.assertFalse((tree / "src/New.java").exists())

    def test_tests_stay_at_the_change_when_only_the_source_is_reverted(self):
        tree = Path(testrun.checkout(self.repo, "HEAD", "w", ("HEAD~1", "src")))
        self.assertEqual((tree / "tests/T.java").read_text(), "t2\n")

    def test_reusing_a_worktree_resets_it_and_removes_build_output(self):
        tree = Path(testrun.checkout(self.repo, "HEAD", "w", ("HEAD~1", "src")))
        (tree / ".classes").mkdir()
        tree = Path(testrun.checkout(self.repo, "HEAD", "w"))
        self.assertEqual((tree / "src/A.java").read_text(), "a\nB\n")
        self.assertFalse((tree / ".classes").exists())


class Run(unittest.TestCase):
    def test_no_new_tests_means_nothing_to_run(self):
        self.assertEqual(testrun.run("repo", {"kind": "junit"}, [], "HEAD", "HEAD~1"), {})

    def test_a_missing_toolchain_is_reported_as_not_run(self):
        with mock.patch.object(testrun.shutil, "which", return_value=None):
            result = testrun.run("repo", {"kind": "junit"}, ["t"], "HEAD", "HEAD~1")
        self.assertEqual(result["t"]["status"], "not run")
        self.assertIn("javac", result["t"]["why"])

    def test_both_runs_are_combined_per_test(self):
        runs = iter([{"t": "passed", "u": "passed"}, {"t": "failed", "u": "passed"}])
        fake = lambda cwd, spec, names: next(runs)
        with mock.patch.dict(testrun.RUNNERS, {"junit": (fake, "git")}), \
             mock.patch.object(testrun, "checkout", return_value="tree"), \
             mock.patch.object(testrun, "git", return_value="abc123\n"):
            result = testrun.run("repo", {"kind": "junit", "src": "src"}, ["t", "u"], "HEAD", "HEAD~1")
        self.assertEqual((result["t"]["proves_fix"], result["u"]["proves_fix"]), (True, False))


if __name__ == "__main__":
    unittest.main()
