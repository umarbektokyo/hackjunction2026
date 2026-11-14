import json
import tempfile
import unittest
from pathlib import Path

from helpers import repo_with
from trust import build, evidence, review

REPO = str(repo_with({"src/A.java": "class A {\n    // TODO\n    void a() { b(); b(); }\n}\n"}))


def check(pattern, expect, **extra):
    return evidence.run_check(REPO, "HEAD", ["issue line: crash"], {"id": "C1", "paths": ["src/A.java"],
                              "pattern": pattern, "expect": expect, **extra})


class RunCheck(unittest.TestCase):
    def test_present_and_absent(self):
        self.assertTrue(check("TODO", "present")["holds"])
        self.assertFalse(check("TODO", "absent")["holds"])
        self.assertTrue(check("FIXME", "absent")["holds"])

    def test_counts_are_per_line(self):
        self.assertTrue(check(r"b\(\)", "==1")["holds"])
        self.assertTrue(check(r"b\(\)", ">=1")["holds"])
        self.assertFalse(check(r"b\(\)", "==2")["holds"])

    def test_a_range_limits_the_lines_searched(self):
        self.assertTrue(check("TODO", "absent", range=(3, 4))["holds"])

    def test_the_issue_text_can_be_checked_too(self):
        result = evidence.run_check(REPO, "HEAD", ["issue line: crash"], {"id": "C2", "paths": ["@issue"], "pattern": "crash", "expect": "present"})
        self.assertEqual(result["matches"], [{"file": "@issue", "line": 1, "text": "issue line: crash"}])


def unit(**extra):
    return {"id": "u", "name": "u", "tier": "shipped", "reqs": ["REQ-1"], "covered_by": ["t"], **extra}


HOLDS = [{"id": "C1", "units": ["u"], "holds": True}]
PROVEN = {"t": {"status": "passed", "proves_fix": True}}


class Gates(unittest.TestCase):
    def test_shipped_code_with_every_gate_passed_is_cleared(self):
        self.assertEqual(evidence.gates(unit(), HOLDS, PROVEN, [])[1], "cleared")

    def test_a_test_that_does_not_prove_the_change_holds_shipped_code(self):
        self.assertEqual(evidence.gates(unit(), HOLDS, {"t": {"status": "passed", "proves_fix": False}}, [])[1], "held")

    def test_a_failing_check_or_missing_requirement_holds_it(self):
        self.assertEqual(evidence.gates(unit(), [{**HOLDS[0], "holds": False}], PROVEN, [])[1], "held")
        self.assertEqual(evidence.gates(unit(reqs=[]), HOLDS, PROVEN, [])[1], "held")

    def test_a_refusal_routes_the_unit_whatever_the_evidence(self):
        self.assertEqual(evidence.gates(unit(), HOLDS, PROVEN, [{"id": "R1"}])[1], "routed")

    def test_docs_and_tests_do_not_need_executed_evidence(self):
        self.assertEqual(evidence.gates(unit(tier="doc", covered_by=[]), HOLDS, {}, [])[1], "cleared")

    def test_imports_only_need_to_go_uncontested(self):
        self.assertEqual(evidence.gates(unit(name="file header", reqs=[], covered_by=[]), [], {}, [])[1], "cleared")


class Confidence(unittest.TestCase):
    CHECKS = {"C1": {"id": "C1", "holds": True}, "C2": {"id": "C2", "holds": False}}

    def test_a_finding_is_backed_contradicted_or_model_only(self):
        self.assertTrue(build.confidence({"checks": ["C1"]}, self.CHECKS)["backed"])
        self.assertEqual(build.confidence({"checks": ["C1", "C2"]}, self.CHECKS)["basis"], "contradicted by C2")
        self.assertEqual(build.confidence({"checks": ["C9"]}, self.CHECKS)["basis"], "model only")


class TestNames(unittest.TestCase):
    def test_xunit_and_junit_tests_are_found_but_helpers_are_not(self):
        lines = lambda text: [{"text": text}]
        found = build.test_names([{"name": "a", "tier": "test", "lines": lines("[Fact]")},
                                  {"name": "b", "tier": "test", "lines": lines("@Test")},
                                  {"name": "c", "tier": "test", "lines": lines("void helper()")},
                                  {"name": "d", "tier": "shipped", "lines": lines("@Test")}])
        self.assertEqual(found, ["a", "b"])


class ReviewLayer(unittest.TestCase):
    def test_refusal_units_come_from_their_findings_unless_given(self):
        rv = {"findings": [{"id": "F1", "unit": "A:x"}, {"id": "F2", "unit": "B:y"}],
              "refusals": [{"id": "R1", "evidence": ["F2", "C3"]}, {"id": "R2", "units": ["Z:z"], "evidence": ["F1"]},
                           {"id": "R3"}]}
        self.assertEqual([r["units"] for r in review.normalise(rv)["refusals"]], [["B:y"], ["Z:z"], []])

    def test_the_cached_model_review_wins_over_the_hand_written_one(self):
        folder = Path(tempfile.mkdtemp())
        for name, source in (("review.llm.json", "llm"), ("review.handwritten.json", "handwritten")):
            (folder / name).write_text(json.dumps({"source": source, "findings": [], "refusals": []}))
        self.assertEqual(review.load(folder)["source"], "llm")

    def test_a_case_without_a_review_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            review.load(Path(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
