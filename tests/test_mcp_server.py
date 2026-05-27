import unittest

from repo_review_agent.mcp_server import issue_drafts_from_report_dict


class MCPServerHelpersTests(unittest.TestCase):
    def test_issue_drafts_from_report_dict(self) -> None:
        drafts = issue_drafts_from_report_dict(
            {
                "repo_name": "example",
                "generated_at": "2026-05-27T00:00:00+00:00",
                "overview": [],
                "metrics": {},
                "framework_signals": {},
                "findings": [
                    {
                        "title": "Add tests",
                        "severity": "medium",
                        "category": "testing",
                        "evidence": ["No tests found."],
                        "recommendation": "Add unit tests.",
                    }
                ],
            }
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].title, "[MEDIUM] Add tests")


if __name__ == "__main__":
    unittest.main()
