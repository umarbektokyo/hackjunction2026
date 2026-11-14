import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trust import decisions, serve

DOSSIER = {"refusals": [{"id": "R1", "owner": {"name": "Aino"}, "options": ["keep", "narrow", "reject"], "evidence": ["C1"]}],
           "units": [{"id": "held", "name": "held", "status": "held"}, {"id": "ok", "name": "ok", "status": "cleared"}],
           "owners": {"approver": {"name": "Sara"}}, "id": "d1"}
AINO = {"name": "Aino"}


class Latest(unittest.TestCase):
    def test_the_last_record_per_item_stands(self):
        records = [{"item": "R1", "decision": "keep"}, {"item": "R1", "decision": "narrow"}, {"item": "R2", "decision": "x"}]
        self.assertEqual({k: v["decision"] for k, v in decisions.latest(records).items()}, {"R1": "narrow", "R2": "x"})

    def test_reopen_withdraws_and_a_new_decision_after_it_stands_again(self):
        self.assertEqual(decisions.latest([{"item": "R1", "decision": "keep"}, {"item": "R1", "decision": "reopen"}]), {})
        records = [{"item": "R1", "decision": "keep"}, {"item": "R1", "decision": "reopen"}, {"item": "R1", "decision": "narrow"}]
        self.assertEqual(decisions.latest(records)["R1"]["decision"], "narrow")


class Blockers(unittest.TestCase):
    def test_an_open_decision_and_an_unproven_unit_block_the_merge(self):
        self.assertEqual(len(decisions.merge_blockers(DOSSIER, [])), 2)

    def test_deciding_and_accepting_without_proof_clear_the_way(self):
        done = [{"item": "R1", "decision": "keep", "by": AINO}, {"item": "held", "decision": "accepted without proof"}]
        self.assertEqual(decisions.merge_blockers(DOSSIER, done), [])

    def test_choosing_the_last_option_rejects_and_keeps_blocking(self):
        done = [{"item": "R1", "decision": "reject", "by": AINO}, {"item": "held", "decision": "accepted without proof"}]
        self.assertEqual(decisions.merge_blockers(DOSSIER, done), ["R1 rejected by Aino"])

    def test_reopening_an_accepted_unit_blocks_again(self):
        done = [{"item": "R1", "decision": "keep", "by": AINO}, {"item": "held", "decision": "accepted without proof"},
                {"item": "held", "decision": "reopen"}]
        self.assertEqual(len(decisions.merge_blockers(DOSSIER, done)), 1)


class Record(unittest.TestCase):
    def test_records_are_appended_never_rewritten(self):
        with mock.patch.object(decisions, "ROOT", Path(tempfile.mkdtemp())):
            decisions.record("c", "d1", "R1", "keep", AINO, ["C1"])
            decisions.record("c", "d1", "R1", "reopen", AINO, ["C1"], note="second thoughts")
            records = decisions.load("c")
        self.assertEqual([r["decision"] for r in records], ["keep", "reopen"])
        self.assertEqual(records[1]["note"], "second thoughts")
        self.assertEqual(records[0]["dossier"], "d1")

    def test_a_case_without_decisions_has_none(self):
        with mock.patch.object(decisions, "ROOT", Path(tempfile.mkdtemp())):
            self.assertEqual(decisions.load("nothing"), [])


class WhoDecides(unittest.TestCase):
    def test_the_routed_owner_decides_their_question_and_may_reopen_it(self):
        self.assertEqual(serve.who_decides(DOSSIER, [], "R1", "keep"), (AINO, ["C1"]))
        self.assertEqual(serve.who_decides(DOSSIER, [], "R1", "reopen")[0], AINO)

    def test_an_answer_that_is_not_an_option_is_refused(self):
        self.assertIsNone(serve.who_decides(DOSSIER, [], "R1", "whatever"))

    def test_only_a_held_unit_can_be_accepted_without_proof_and_only_by_the_approver(self):
        self.assertEqual(serve.who_decides(DOSSIER, [], "held", "accepted without proof")[0]["name"], "Sara")
        self.assertIsNone(serve.who_decides(DOSSIER, [], "ok", "accepted without proof"))
        self.assertIsNone(serve.who_decides(DOSSIER, [], "held", "keep"))

    def test_merge_needs_no_blockers_but_requesting_changes_is_always_possible(self):
        self.assertIsNone(serve.who_decides(DOSSIER, [], "MERGE", "approved"))
        self.assertIsNotNone(serve.who_decides(DOSSIER, [], "MERGE", "changes requested"))
        done = [{"item": "R1", "decision": "keep", "by": AINO}, {"item": "held", "decision": "accepted without proof"}]
        self.assertEqual(serve.who_decides(DOSSIER, done, "MERGE", "approved")[0]["name"], "Sara")

    def test_unknown_items_are_refused(self):
        self.assertIsNone(serve.who_decides(DOSSIER, [], "R9", "keep"))


if __name__ == "__main__":
    unittest.main()
