import unittest
from unittest import mock

from trust import style

UNIT = {"id": "T.java:count", "name": "count", "file": "src/T.java", "start": 10, "end": 20, "added": 1,
        "lines": [{"kind": "+", "new": 12}, {"kind": " ", "new": 13}, {"kind": "-", "new": None}]}


class Report(unittest.TestCase):
    def test_lines_with_and_without_a_column_are_read(self):
        out = ("[WARN] /r/src/T.java:12:5: Line is longer than 100 characters. [LineLength]\n"
               "[ERROR] /r/src/T.java:3: Missing a Javadoc comment. [MissingJavadocMethod]\n"
               "Starting audit...\nAudit done.")
        with mock.patch.object(style.subprocess, "run") as run:
            run.return_value.stdout = out
            found = style.violations("tree", "checkstyle.xml", ["src/T.java"])
        self.assertEqual(found, [("/r/src/T.java", 12, "Line is longer than 100 characters. [LineLength]"),
                                 ("/r/src/T.java", 3, "Missing a Javadoc comment. [MissingJavadocMethod]")])


class CheckFor(unittest.TestCase):
    def test_a_violation_on_a_changed_line_counts_against_the_change(self):
        check = style.check_for(1, UNIT, [("/r/src/T.java", 12, "long [LineLength]")], "checkstyle.xml")
        self.assertFalse(check["holds"])
        self.assertEqual(check["matches"], [{"file": "src/T.java", "line": 12, "text": "long [LineLength]"}])

    def test_violations_on_untouched_lines_are_pre_existing(self):
        check = style.check_for(1, UNIT, [("/r/src/T.java", 13, "old [Javadoc]")], "checkstyle.xml")
        self.assertTrue(check["holds"])
        self.assertEqual(check["preexisting"], 1)

    def test_violations_outside_the_unit_or_in_another_file_are_ignored(self):
        found = [("/r/src/T.java", 30, "x [X]"), ("/r/src/Other.java", 12, "y [Y]")]
        check = style.check_for(1, UNIT, found, "checkstyle.xml")
        self.assertEqual((check["holds"], check["count"], check["preexisting"]), (True, 0, 0))


class Checks(unittest.TestCase):
    def test_no_style_config_or_no_java_or_no_checkstyle_means_no_style_checks(self):
        self.assertEqual(style.checks("repo", "HEAD", None, [UNIT]), [])
        self.assertEqual(style.checks("repo", "HEAD", {"kind": "checkstyle"}, [{**UNIT, "file": "a.cs"}]), [])
        with mock.patch.object(style.shutil, "which", return_value=None):
            self.assertEqual(style.checks("repo", "HEAD", {"kind": "checkstyle", "config": "c.xml"}, [UNIT]), [])

    def test_units_that_only_remove_lines_are_not_style_checked(self):
        with mock.patch.object(style.shutil, "which", return_value="/bin/checkstyle"):
            self.assertEqual(style.checks("repo", "HEAD", {"kind": "checkstyle"}, [{**UNIT, "added": 0}]), [])


if __name__ == "__main__":
    unittest.main()
