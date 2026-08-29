"""
The one non-negotiable constraint, enforced rather than documented.

DATABASE-PLAN.md: "No UPDATE statement and no DELETE statement exists anywhere
in this design's interaction with `observations`. That is not an implementation
detail -- it is the requirement."

This greps the source for SQL that could mutate `observations`, so the rule
survives a future edit made in good faith by someone who has not read the plan.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(ROOT.glob("db/*.py")) + [ROOT / "pipeline.py", ROOT / "bootstrap.py"]

# Any UPDATE/DELETE naming observations, in any spacing or case.
MUTATION = re.compile(r"\b(?:UPDATE|DELETE\s+FROM)\s+observations\b", re.IGNORECASE)
# ...and the table-wide forms that would take it out sideways.
DESTRUCTIVE = re.compile(r"\b(?:DROP\s+TABLE|TRUNCATE|REPLACE\s+INTO)\s+.*observations",
                         re.IGNORECASE)


class AppendOnly(unittest.TestCase):
    def test_no_mutation_of_observations(self):
        for path in SOURCES:
            if not path.exists():
                continue
            text = path.read_text()
            for pattern, label in ((MUTATION, "UPDATE/DELETE"), (DESTRUCTIVE, "destructive")):
                hit = pattern.search(text)
                self.assertIsNone(
                    hit, f"{path.relative_to(ROOT)} contains {label} SQL against "
                         f"observations: {hit.group(0) if hit else ''!r}")

    def test_schema_has_no_on_conflict_update_for_observations(self):
        schema = (ROOT / "db" / "schema.sql").read_text()
        self.assertNotRegex(schema, r"(?i)observations[\s\S]{0,400}?DO\s+UPDATE")

    def test_insert_uses_do_nothing(self):
        store = (ROOT / "db" / "store.py").read_text()
        self.assertIn("ON CONFLICT(series_id, date, vintage_date) DO NOTHING", store)


if __name__ == "__main__":
    unittest.main()
