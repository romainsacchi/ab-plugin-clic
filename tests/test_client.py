import unittest
from unittest.mock import Mock, patch

import requests

from ab_clic.client import ClicClient, ClicError


class ClicClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock(spec=requests.Session)
        self.client = ClicClient(self.session)

    @staticmethod
    def response(payload, status=200):
        response = Mock(status_code=status, ok=status < 400)
        response.json.return_value = payload
        return response

    def test_search_is_anonymous(self):
        self.session.request.return_value = self.response({"results": []})
        self.client.search_versions("electricity", 2)
        request = self.session.request.call_args
        self.assertEqual(request.args, ("GET", "https://clic.psi.ch/api/versions/"))
        self.assertEqual(request.kwargs["params"]["page"], 2)
        self.assertEqual(request.kwargs["headers"], {})

    @patch("ab_clic.client.time.sleep")
    def test_async_export_retrieves_the_requested_version(self, _sleep):
        package = {"package": {"root_version_ids": [42]}}
        self.session.request.side_effect = [
            self.response({"status": "queued", "status_url": "/api/jobs/test/"}, 202),
            self.response(
                {"status": "succeeded", "result_url": "/api/jobs/test/result/"}
            ),
            self.response(package),
        ]
        self.assertEqual(
            self.client.export(42, {"family": "ecoinvent"}, "fake-token"), package
        )
        calls = self.session.request.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["POST", "GET", "GET"])
        for call in calls:
            self.assertEqual(
                call.kwargs["headers"]["Authorization"], "Bearer fake-token"
            )
            self.assertFalse(call.kwargs["allow_redirects"])

    def test_token_stays_on_clic_origin(self):
        self.session.request.return_value = self.response(
            {"status": "succeeded", "result_url": "https://example.org/result/"}
        )
        with self.assertRaisesRegex(ClicError, "another origin"):
            self.client.export(42, {}, "fake-token")
        self.session.request.assert_called_once()
