import unittest

from trust import units

JAVA = """import java.util.List;

public class Terminal {
    private final List<String> tickets;

    /**
     * Javadoc belongs to the member below.
     */
    @Override
    public boolean equals(Object o) {
        return o == this;
    }

    public int count() {
        String braces = "{ not a block }";
        return tickets.size();
    }
}
""".splitlines()

CSHARP = '''using System;

public class T
{
    [Fact]
    public void Test()
    {
        var s = """
    public void NotAMember()
""";
    }
}
'''.splitlines()


class Spans(unittest.TestCase):
    def test_java_members_include_javadoc_and_annotations(self):
        self.assertEqual(units.spans("src/Terminal.java", JAVA),
                         [("file header", 1, 3), ("tickets", 4, 4), ("equals", 6, 12), ("count", 14, 17)])

    def test_braces_inside_strings_do_not_end_a_member(self):
        self.assertEqual(units.spans("src/Terminal.java", JAVA)[-1], ("count", 14, 17))

    def test_csharp_attributes_belong_to_the_member_and_raw_strings_are_skipped(self):
        self.assertEqual(units.spans("T.cs", CSHARP), [("file header", 1, 4), ("Test", 5, 11)])

    def test_a_file_without_members_is_all_header(self):
        self.assertEqual(units.spans("src/Empty.java", ["// nothing", ""]), [("file header", 1, 2)])

    def test_markdown_sections_end_where_the_next_begins_and_ignore_fenced_hashes(self):
        md = ["intro", "# One", "text", "```", "# not a heading", "```", "## Two", "end"]
        self.assertEqual(units.spans("README.md", md), [("file header", 1, 1), ("One", 2, 6), ("Two", 7, 8)])

    def test_tiers_follow_the_path(self):
        self.assertEqual([units.tier(p) for p in ("src/A.java", "tests/ATest.java", "docs/x.md")], ["shipped", "test", "doc"])


class Split(unittest.TestCase):
    BODY = ["class A {", "    void a() {", "        x();", "    }", "}"]

    def test_only_members_with_changed_lines_become_units(self):
        diff = {"A.java": [[(" ", 2, 2, "    void a() {"), ("-", 3, 3, "        y();"), ("+", None, 3, "        x();"),
                            (" ", 4, 4, "    }")]]}
        found = units.split(diff, lambda p: self.BODY)
        self.assertEqual([(u["name"], u["added"], u["removed"]) for u in found], [("a", 1, 1)])
        self.assertEqual(found[0]["lines"][1], {"kind": "-", "old": 3, "new": None, "text": "        y();"})

    def test_blank_line_changes_belong_to_no_unit(self):
        diff = {"A.java": [[("+", None, 4, "   ")]]}
        self.assertEqual(units.split(diff, lambda p: self.BODY), [])

    def test_unit_ids_name_the_file_and_member(self):
        diff = {"src/A.java": [[("+", None, 3, "        x();")]]}
        self.assertEqual(units.split(diff, lambda p: self.BODY)[0]["id"], "A.java:a")


if __name__ == "__main__":
    unittest.main()
