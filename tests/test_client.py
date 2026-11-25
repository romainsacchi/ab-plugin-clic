import unittest
from unittest.mock import Mock, patch

import requests

from ab_clic.client import ClicClient, ClicError
from ab_clic.progress import PreparationStep


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

    def test_search_uses_the_selected_field(self):
        self.session.request.return_value = self.response({"results": []})
        self.client.search_versions("Krogh", 1, field="author")
        self.assertEqual(
            self.session.request.call_args.kwargs["params"]["author"], "Krogh"
        )
        self.assertNotIn("name", self.session.request.call_args.kwargs["params"])

    def test_project_search_sends_the_requested_catalog_sort(self):
        self.session.request.return_value = self.response({"results": []})
        self.client.search_versions(
            "Inventory project", 2, field="project", sort="name_desc"
        )
        request = self.session.request.call_args.kwargs["params"]
        self.assertEqual(request["project"], "Inventory project")
        self.assertEqual(request["sort"], "name_desc")
        self.assertEqual(request["page"], 2)

    def test_publication_year_search_uses_an_exact_year_range(self):
        self.session.request.return_value = self.response({"results": []})
        self.client.search_versions("2024", 1, field="publication_year")
        params = self.session.request.call_args.kwargs["params"]
        self.assertEqual(params["publication_year_min"], "2024")
        self.assertEqual(params["publication_year_max"], "2024")

    def test_license_filter_skips_pages_without_matching_versions(self):
        noncommercial = [
            {"selected_license": f"CC-BY-NC-{suffix}"}
            for suffix in ("3.0", "4.0", "SA-4.0", "ND-4.0")
        ]
        visible = [
            {"selected_license": "CC-BY-4.0"},
            {"selected_license": "UNDISCLOSED"},
        ]
        self.session.request.side_effect = [
            self.response(
                {"page": 2, "previous": "previous-url", "results": noncommercial}
            ),
            self.response(
                {"page": 1, "previous": None, "results": [*visible, *noncommercial]}
            ),
        ]
        result = self.client.search_versions(
            "solar", 2, exclude_noncommercial=True, direction=-1
        )
        self.assertEqual(result["results"], visible)
        self.assertEqual(result["page"], 1)
        self.assertEqual(
            [
                call.kwargs["params"]["page"]
                for call in self.session.request.call_args_list
            ],
            [2, 1],
        )

    def test_column_filters_combine_and_skip_nonmatching_pages(self):
        visible = {"name": "Solar electricity", "location": "CH", "id": 32}
        wrong_location = {**visible, "id": 29, "location": "CHE"}
        excluded_id = {**visible, "id": 31}
        wrong_name = {**visible, "id": 30, "name": "Wind electricity"}
        self.session.request.side_effect = [
            self.response(
                {
                    "page": 1,
                    "next": "next-url",
                    "results": [wrong_location, excluded_id],
                }
            ),
            self.response({"page": 2, "next": None, "results": [visible, wrong_name]}),
        ]
        result = self.client.search_versions(
            "electricity",
            1,
            column_filters={
                "name": ("SOLAR", False),
                "location": ("ch", False),
                "id": ("31", True),
            },
        )
        self.assertEqual(result["results"], [visible])
        self.assertEqual(result["page"], 2)
        self.assertEqual(
            [
                call.kwargs["params"]["page"]
                for call in self.session.request.call_args_list
            ],
            [1, 2],
        )

    @patch("ab_clic.client.time.sleep")
    def test_async_export_retrieves_the_requested_version(self, _sleep):
        package = {"package": {"root_version_ids": [42]}}
        queued = self.response(
            {"status": "queued", "status_url": "/api/jobs/test/"}, 202
        )
        self.session.request.side_effect = [
            queued,
            queued,
            self.response({"status": "processing", "status_url": "/api/jobs/test/"}),
            self.response(
                {"status": "succeeded", "result_url": "/api/jobs/test/result/"}
            ),
            self.response(package),
        ]
        progress = Mock()
        self.assertEqual(
            self.client.export(
                [42], {"family": "ecoinvent"}, "fake-token", on_progress=progress
            ),
            package,
        )
        calls = self.session.request.call_args_list
        self.assertEqual(
            [call.args[0] for call in calls], ["POST", "GET", "GET", "GET", "GET"]
        )
        self.assertEqual(
            [call.args[0] for call in progress.call_args_list],
            [
                PreparationStep.REQUEST_EXPORT,
                PreparationStep.WAIT_FOR_EXPORT,
                PreparationStep.WAIT_FOR_EXPORT,
                PreparationStep.DOWNLOAD_PACKAGE,
            ],
        )
        self.assertIn("queued", progress.call_args_list[1].args[1])
        self.assertIn("preparing", progress.call_args_list[2].args[1])
        self.assertEqual(calls[0].kwargs["json"], {"family": "ecoinvent"})
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
            self.client.export([42], {}, "fake-token")
        self.session.request.assert_called_once()

    def test_multiple_versions_share_one_export(self):
        package = {"package": {"root_version_ids": [42, 58, 91]}}
        self.session.request.side_effect = [
            self.response(
                {"status": "succeeded", "result_url": "/api/jobs/test/result/"}
            ),
            self.response(package),
        ]
        target = {"family": "ecoinvent"}
        self.assertEqual(
            self.client.export([91, 42, 58, 42], target, "fake-token"), package
        )
        post = self.session.request.call_args_list[0]
        self.assertTrue(post.args[1].endswith("/versions/42/brightway-json-jobs/"))
        self.assertEqual(post.kwargs["json"], {**target, "version_ids": [58, 91]})

    def test_rejects_a_package_missing_a_selected_version(self):
        self.session.request.side_effect = [
            self.response(
                {"status": "succeeded", "result_url": "/api/jobs/test/result/"}
            ),
            self.response({"package": {"root_version_ids": [42]}}),
        ]
        with self.assertRaisesRegex(ClicError, "different selection"):
            self.client.export([42, 58], {}, "fake-token")

    def test_descriptions_use_the_exact_versions_and_keep_package_comments(self):
        def activity(slug, version, **fields):
            return {
                "provenance": {"dataset_slug": slug, "semantic_version": version},
                **fields,
            }

        root = activity("root", "1.0.0")
        supplier = activity("supplier", "1.0.0")
        supplier_other = activity("supplier", "3.0.0")
        existing = activity("other", "1.0.0", comment="Original export comment")
        helper = {"provenance": {"origin": "generated"}}
        package = {"activities": [root, supplier, supplier_other, existing, helper]}
        self.session.request.return_value = self.response(
            {
                "published_versions": [
                    {"semantic_version": "2.0.0", "description": "Newer version"},
                    {
                        "semantic_version": "1.0.0",
                        "description": "Supplier description",
                    },
                ]
            }
        )
        self.client.add_inventory_metadata(
            package,
            [
                {
                    "dataset_slug": "root",
                    "semantic_version": "1.0.0",
                    "description": "Root description",
                    "authors": [{"name": "Inventory Author"}],
                    "quality_assessment": {"technology_readiness_level": 7},
                    "discovery_metadata": {
                        "publications": [
                            {
                                "relation": "primary_source",
                                "title": "Source Title",
                                "publication_year": 2024,
                                "authors": [{"name": "Publication Author"}],
                            }
                        ]
                    },
                },
                {
                    "dataset_slug": "other",
                    "semantic_version": "1.0.0",
                    "description": "Catalog text",
                },
            ],
        )
        self.assertTrue(root["comment"].startswith("Root description\n\n"))
        self.assertIn("Source publication — Source Title", root["comment"])
        self.assertIn("Publication year — 2024", root["comment"])
        self.assertIn("Publication authors — Publication Author", root["comment"])
        self.assertIn("Inventory authors — Inventory Author", root["comment"])
        self.assertIn("Technology readiness level (TRL) — 7", root["comment"])
        self.assertTrue(supplier["comment"].startswith("Supplier description\n\n"))
        self.assertNotIn("comment", supplier_other)
        self.assertTrue(
            existing["comment"].startswith("Original export comment\n\nCatalog text")
        )
        self.assertNotIn("comment", helper)
        self.session.request.assert_called_once()
        self.assertEqual(
            self.session.request.call_args.args,
            ("GET", "https://clic.psi.ch/api/datasets/supplier/"),
        )
        self.assertEqual(self.session.request.call_args.kwargs["headers"], {})
