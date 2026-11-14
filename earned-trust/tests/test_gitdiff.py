import subprocess
import unittest

from helpers import repo_with
from trust import gitdiff


class Diff(unittest.TestCase):
    def test_changed_lines_carry_their_real_numbers(self):
        repo = repo_with({"a.txt": "1\n2\n3\n"}, {"a.txt": "1\nTWO\n3\n"})
        hunk = gitdiff.diff(str(repo), "HEAD~1", "HEAD")["a.txt"][0]
        self.assertEqual([l for l in hunk if l[0] != " "], [("-", 2, 2, "2"), ("+", None, 2, "TWO")])

    def test_two_far_apart_changes_are_two_hunks(self):
        before = "".join(f"{i}\n" for i in range(1, 31))
        after = before.replace("2\n", "two\n", 1).replace("28\n", "twenty-eight\n")
        repo = repo_with({"a.txt": before}, {"a.txt": after})
        self.assertEqual(len(gitdiff.diff(str(repo), "HEAD~1", "HEAD")["a.txt"]), 2)

    def test_new_files_are_all_added_and_deleted_files_are_left_out(self):
        repo = repo_with({"old.txt": "x\n"}, {"old.txt": None, "new.txt": "a\nb\n"})
        diff = gitdiff.diff(str(repo), "HEAD~1", "HEAD")
        self.assertEqual(list(diff), ["new.txt"])
        self.assertEqual([l[0] for l in diff["new.txt"][0]], ["+", "+"])

    def test_no_change_is_an_empty_diff(self):
        repo = repo_with({"a.txt": "x\n"}, {})
        self.assertEqual(gitdiff.diff(str(repo), "HEAD~1", "HEAD"), {})

    def test_show_reads_a_file_at_a_revision_and_fails_for_a_missing_one(self):
        repo = repo_with({"a.txt": "old\n"}, {"a.txt": "new\n"})
        self.assertEqual(gitdiff.show(str(repo), "HEAD~1", "a.txt"), ["old"])
        with self.assertRaises(subprocess.CalledProcessError):
            gitdiff.show(str(repo), "HEAD", "missing.txt")


if __name__ == "__main__":
    unittest.main()
