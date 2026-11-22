import unittest
from datetime import date

from pipeline import store
from pipeline.sources import bizinfo, sample
from pipeline.status import notice_status


class ParsePeriodTest(unittest.TestCase):
    def test_compact_range(self):
        self.assertEqual(
            bizinfo.parse_period("20261101 ~ 20261130"), (date(2026, 11, 1), date(2026, 11, 30), "range")
        )

    def test_dotted_range(self):
        self.assertEqual(
            bizinfo.parse_period("2026. 11. 1. ~ 2026. 12. 5."), (date(2026, 11, 1), date(2026, 12, 5), "range")
        )

    def test_budget_exhaustion_is_always(self):
        self.assertEqual(bizinfo.parse_period("20261101 ~ 예산 소진시까지"), (date(2026, 11, 1), None, "always"))

    def test_always(self):
        self.assertEqual(bizinfo.parse_period("상시 접수"), (None, None, "always"))

    def test_end_only(self):
        self.assertEqual(bizinfo.parse_period("~ 20261231"), (None, date(2026, 12, 31), "range"))

    def test_garbage(self):
        self.assertEqual(bizinfo.parse_period("추후 공지"), (None, None, "unknown"))


class NormalizeTest(unittest.TestCase):
    def test_json_field_names(self):
        n = bizinfo.normalize(
            {
                "pblancId": "PBLN_1",
                "pblancNm": "테스트 &amp; 공고",
                "pblancUrl": "/web/view.do?pblancId=PBLN_1",
                "jrsdInsttNm": "중소벤처기업부",
                "pldirSportRealmLclasCodeNm": "창업",
                "bsnsSumryCn": "&lt;p&gt;□ 지원대상: A&lt;/p&gt;&lt;p&gt;□ 지원내용: B&lt;/p&gt;",
                "reqstBeginEndDe": "20261101 ~ 20261130",
                "hashtags": "창업,서울,경기도",
                "creatPnttm": "2026-11-01 09:00:00",
                "inqireCo": "1,234",
            }
        )
        self.assertEqual(n["title"], "테스트 & 공고")
        self.assertEqual(n["url"], "https://www.bizinfo.go.kr/web/view.do?pblancId=PBLN_1")
        self.assertEqual(n["summary_text"], "□ 지원대상: A\n□ 지원내용: B")
        self.assertEqual(n["regions"], ["서울", "경기"])
        self.assertEqual(n["end_date"], "2026-11-30")
        self.assertEqual(n["registered_at"], "2026-11-01")
        self.assertEqual(n["views"], 1234)

    def test_rss_field_names_and_defaults(self):
        n = bizinfo.normalize({"seq": "PBLN_2", "title": "공고", "lcategory": "", "hashTags": "전남광주"})
        self.assertEqual(n["id"], "PBLN_2")
        self.assertEqual(n["category"], "기타")
        self.assertEqual(n["regions"], ["광주", "전남"])

    def test_missing_required(self):
        self.assertIsNone(bizinfo.normalize({"pblancNm": "id 없음"}))

    def test_extract_items_shapes(self):
        self.assertEqual(len(bizinfo.extract_items({"jsonArray": [{"a": 1}, {"b": 2}]})), 2)
        self.assertEqual(len(bizinfo.extract_items({"jsonArray": {"item": [{"a": 1}]}})), 1)
        self.assertEqual(len(bizinfo.extract_items({"jsonArray": {"item": {"a": 1}}})), 1)


class StatusTest(unittest.TestCase):
    today = date(2026, 11, 23)

    def status(self, **kw):
        return notice_status(kw, self.today, 7)

    def test_states(self):
        self.assertEqual(self.status(end_date="2026-11-23")["dday_label"], "오늘 마감")
        self.assertEqual(self.status(end_date="2026-11-30")["status"], "closing")
        self.assertEqual(self.status(end_date="2026-12-01")["status"], "open")
        self.assertEqual(self.status(end_date="2026-11-22")["status"], "closed")
        self.assertEqual(self.status(start_date="2026-11-25", end_date="2026-12-25")["status"], "upcoming")
        self.assertEqual(self.status(period_kind="always")["status"], "always")
        self.assertEqual(self.status()["status"], "unknown")


class StoreTest(unittest.TestCase):
    def test_upsert_keeps_first_seen(self):
        items = {"A": {"id": "A", "hash": "1", "first_seen": "2026-11-01"}}
        stats = store.upsert(items, [{"id": "A", "hash": "2"}, {"id": "B", "hash": "1"}], date(2026, 11, 23))
        self.assertEqual(stats, {"new": 1, "changed": 1, "same": 0})
        self.assertEqual(items["A"]["first_seen"], "2026-11-01")
        self.assertEqual(items["B"]["first_seen"], "2026-11-23")

    def test_prune(self):
        items = {
            "old": {"end_date": "2026-01-01", "last_seen": "2026-11-23"},
            "gone": {"end_date": None, "last_seen": "2026-01-01"},
            "keep": {"end_date": "2026-11-01", "last_seen": "2026-11-23"},
        }
        self.assertEqual(store.prune(items, date(2026, 11, 23), 180), 2)
        self.assertEqual(list(items), ["keep"])


class SampleTest(unittest.TestCase):
    def test_sample_fixture_normalizes(self):
        raw = sample.load_raw(date(2026, 11, 23))
        notices = [bizinfo.normalize(r) for r in raw]
        self.assertTrue(all(notices))
        self.assertTrue(all(n["title"].startswith("[샘플]") for n in notices))


if __name__ == "__main__":
    unittest.main()
