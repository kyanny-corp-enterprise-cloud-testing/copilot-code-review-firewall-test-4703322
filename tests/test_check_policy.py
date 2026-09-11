from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_policy", ROOT / ".github/skills/code-review/check_policy.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class PolicyProbeTests(unittest.TestCase):
    def run_probe(self, payload=b'{"free_shipping_minimum":5000}', failure=None):
        response = MagicMock()
        response.status = 200
        response.read.return_value = payload
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        opener.open.side_effect = failure
        output = io.StringIO()
        with patch.object(probe, "build_opener", return_value=opener), redirect_stdout(output):
            result = probe.main()
        return result, output.getvalue(), opener

    def test_match_and_outgoing_request(self):
        with patch.object(probe, "qualifies_for_free_shipping", side_effect=lambda total: total >= 5000):
            result, output, opener = self.run_probe()
        self.assertEqual(result, 0)
        self.assertIn("POLICY_FETCH_OK", output)
        self.assertIn("POLICY_MATCH", output)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertIn("?probe_id=", request.full_url)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)

    def test_pr_mismatch(self):
        with patch.object(probe, "qualifies_for_free_shipping", side_effect=lambda total: total >= 3000):
            result, output, _ = self.run_probe()
        self.assertEqual(result, 1)
        self.assertIn("POLICY_FETCH_OK", output)
        self.assertIn("POLICY_MISMATCH order_totals=[4999]", output)

    def test_http_failure_is_not_labeled_firewall_block(self):
        result, output, _ = self.run_probe(failure=HTTPError("https://example.invalid", 403, "Forbidden", {}, None))
        self.assertEqual(result, 2)
        self.assertIn("http_status=403", output)
        self.assertNotIn("POLICY_FETCH_OK", output)
        self.assertIn("does not prove", output)

    def test_connection_failure(self):
        result, output, _ = self.run_probe(failure=URLError("connection refused"))
        self.assertEqual(result, 2)
        self.assertIn("FETCH_ERROR", output)

    def test_malformed_empty_and_invalid_policies(self):
        for payload in (b"", b"<html>error</html>", b"{}", b"[]", b'{"free_shipping_minimum":true}', b'{"free_shipping_minimum":0}', b"x" * 65537):
            with self.subTest(payload=payload[:50]):
                result, output, _ = self.run_probe(payload=payload)
                self.assertEqual(result, 3)
                self.assertIn("POLICY_ERROR", output)

    def test_invalid_configuration_does_not_connect(self):
        for config in ('{"url":"http://example.invalid"}', '{"url":"https://user:secret@example.invalid"}', '{}', '[]'):
            with self.subTest(config=config), patch.object(Path, "read_text", return_value=config):
                result, output, opener = self.run_probe()
                self.assertEqual(result, 4)
                self.assertIn("CONFIG_ERROR", output)
                opener.open.assert_not_called()

    def test_redirect_is_not_followed(self):
        self.assertIsNone(probe.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.invalid"))


if __name__ == "__main__":
    unittest.main()