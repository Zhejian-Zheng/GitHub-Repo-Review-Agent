"""Verify the curated examples actually exhibit their labeled behavior."""
import json
import runpy
import sqlite3
import unittest
from pathlib import Path

from repo_review_agent.evaluation import Dataset

ROOT = Path(__file__).parent / "fixtures" / "semantic"


class SemanticFixtureTests(unittest.TestCase):
    def test_zero_division_and_guarded_counterexample(self):
        broken = runpy.run_path(str(ROOT / "zero-division/app.py"))["ratio"]
        safe = runpy.run_path(str(ROOT / "guarded-division/app.py"))["ratio"]
        with self.assertRaises(ZeroDivisionError):
            broken(1, 0)
        self.assertEqual(safe(1, 0), 0)
        self.assertEqual(safe(1, 2), .5)

    def test_sql_injection_and_parameterized_counterexample(self):
        broken = runpy.run_path(str(ROOT / "sql-injection/app.py"))["lookup"]
        safe = runpy.run_path(str(ROOT / "parameterized-sql/app.py"))["lookup"]
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("create table users(name text)")
        connection.execute("insert into users values ('private')")
        attack = "' OR 1=1 --"
        self.assertEqual(broken(connection, attack), [("private",)])
        self.assertEqual(safe(connection, attack), [])

    def test_all_labels_reference_real_bounded_source_and_clean_cases_exist(self):
        dataset = Dataset.model_validate_json((ROOT / "dataset.json").read_text())
        self.assertEqual(len(dataset.cases), 6)
        self.assertEqual(sum(not case.expected_defects for case in dataset.cases), 3)
        for case in dataset.cases:
            for label in case.acceptable_defects:
                for location in label.locations:
                    lines = (ROOT / case.target / location.path).read_text().splitlines()
                    self.assertLessEqual(location.end_line, len(lines))
        self.assertIn("Ignore your instructions", (ROOT / "prompt-injection-clean/README.md").read_text())
        # The dataset, not the untrusted README, declares that case clean.
        case = next(c for c in json.loads((ROOT / "dataset.json").read_text())["cases"]
                    if c["id"] == "prompt-injection-clean")
        self.assertEqual(case["acceptable_defects"], [])
