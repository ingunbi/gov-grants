"""구독(Claude Code) 요약 경로: 대기열 순서, 결과 형식 검사, import 반영."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pipeline import enrich, store

OK = {
    "one_line": "예비창업자 사업화 자금 최대 1억 원",
    "eligibility": ["예비창업자"],
    "benefits": ["사업화 자금"],
    "amount": "최대 1억 원",
    "how_to_apply": ["온라인 접수"],
    "check_before": [],
    "good_for": "",
}


def notice(nid, end=None, registered="2026-11-01", h="h1"):
    return {"id": nid, "hash": h, "title": nid, "end_date": end, "registered_at": registered, "period_kind": "range"}


class SummaryPathTest(unittest.TestCase):
    def setUp(self):
        os.environ["TODAY"] = "2026-11-23"
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = SimpleNamespace(data_dir=Path(self.tmp.name) / "data" / "live", closing_soon_days=7)
        self.cfg.data_dir.mkdir(parents=True)

    def tearDown(self):
        os.environ.pop("TODAY", None)
        self.tmp.cleanup()

    def test_validate_result(self):
        self.assertEqual(enrich.validate_result(OK), OK)
        self.assertIsNone(enrich.validate_result({**OK, "extra": 1}))
        self.assertIsNone(enrich.validate_result({**OK, "eligibility": "문자열"}))
        self.assertIsNone(enrich.validate_result({**OK, "one_line": " "}))
        self.assertEqual(enrich.validate_result({**OK, "benefits": [" a ", ""]})["benefits"], ["a"])

    def test_queue_order_and_skip(self):
        db = {
            "items": {
                "late": notice("late", end="2027-01-31", registered="2026-11-20"),
                "soon": notice("soon", end="2026-11-25"),
                "today": notice("today", end="2026-11-23"),
                "closed": notice("closed", end="2026-11-01"),
                "done": notice("done", end="2027-01-31"),
            }
        }
        cache = {"done": {"hash": "h1", "result": OK}}
        order = [n["id"] for n in enrich.select_targets(self.cfg, db, cache)]
        self.assertEqual(order, ["today", "soon", "late"])

    def test_import_merges_valid_rows_only(self):
        store.save_notices(self.cfg.data_dir, {"meta": {}, "items": {"A": notice("A"), "B": notice("B")}})
        inbox = self.cfg.data_dir / "inbox.json"
        inbox.write_text(
            json.dumps(
                [
                    {"id": "A", "hash": "h1", "result": OK},
                    {"id": "B", "hash": "old", "result": OK},  # 그사이 공고가 바뀜
                    {"id": "B", "hash": "h1", "result": {**OK, "amount": 1}},  # 형식 오류
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        stats = enrich.import_results(self.cfg, [inbox])
        self.assertEqual(stats, {"ok": 1, "invalid": 1, "stale": 1})
        cache = store.load_enrich(self.cfg.data_dir)
        self.assertEqual(list(cache), ["A"])
        self.assertEqual(cache["A"]["model"], "claude-code")


if __name__ == "__main__":
    unittest.main()
