"""요약 단계를 실제 SDK로 호출하되, 로컬 가짜 서버로 받아서 요청 모양과 응답 처리만 확인한다(비용 0)."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic

from pipeline import enrich

RESULT = {
    "one_line": "예비창업자 사업화 자금 최대 1억 원",
    "eligibility": ["예비창업자"],
    "benefits": ["사업화 자금"],
    "amount": "최대 1억 원",
    "how_to_apply": ["온라인 접수"],
    "check_before": [],
    "good_for": "",
}


class FakeAPI(BaseHTTPRequestHandler):
    captured: list = []
    stop_reason = "end_turn"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAPI.captured.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(RESULT, ensure_ascii=False)}],
            "stop_reason": FakeAPI.stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class SummarizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.client = anthropic.Anthropic(
            api_key="test-key", base_url=f"http://127.0.0.1:{cls.server.server_port}", max_retries=0
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeAPI.captured.clear()
        FakeAPI.stop_reason = "end_turn"

    notice = {
        "title": "[샘플] 예비창업자 지원",
        "agency": "기관",
        "category": "창업",
        "summary_text": "□ 지원내용: 사업화 자금 최대 1억 원",
        "period_raw": "20261101 ~ 20261130",
    }

    def test_request_shape_and_parse(self):
        data, resp, status = enrich.summarize(self.client, "claude-opus-5-5", "low", self.notice)
        self.assertEqual(status, "ok")
        self.assertEqual(data, RESULT)
        req = FakeAPI.captured[0]
        body = req["body"]
        self.assertTrue(req["path"].startswith("/v1/messages"))
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", req["headers"].get("anthropic-beta", ""))
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("thinking", body)
        self.assertIn("<notice>", body["messages"][0]["content"])

    def test_refusal_returns_none(self):
        FakeAPI.stop_reason = "refusal"
        data, _, status = enrich.summarize(self.client, "claude-opus-5-5", "low", self.notice)
        self.assertIsNone(data)
        self.assertEqual(status, "refusal")


if __name__ == "__main__":
    unittest.main()
