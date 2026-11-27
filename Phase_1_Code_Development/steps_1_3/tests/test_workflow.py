"""Checks for release integrity and the methodology's decision boundaries."""

from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import unittest

from openpyxl import Workbook

from Phase_1_Code_Development.steps_1_3.catalog import Catalog, CatalogError, load_catalog, read_tables
from Phase_1_Code_Development.steps_1_3.workflow import (
    WorkflowError, evaluate, judge, rank_classes, validate_spec, validate_uncertainty,
)


APP_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = APP_ROOT.parents[1]
RELEASE = "P1-REL-0007"


def configured_catalog():
    path = os.environ.get("PHASE1_THESIS_ROOT")
    if not path:
        raise RuntimeError("Set PHASE1_THESIS_ROOT to the thesis root for the release tests")
    root = Path(path).expanduser().resolve()
    return root, load_catalog(root, RELEASE)


def example(name):
    return json.loads((APP_ROOT / "examples" / name).read_text(encoding="utf-8"))


def judgment_entry(node, action="retain", **details):
    return {
        "target_id": node["id"], "basis": node["basis"], "action": action,
        "analyst": "Software verification analyst",
        "rationale": "Check the declared scope and retain explicit unresolved inputs.",
        "evidence_refs": node["refs"] or ["TEST-001"],
        "evidence_quality": 2, "confidence": 2, **details,
    }


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.catalog = configured_catalog()

    def test_governing_release_and_wb04a(self):
        self.assertEqual(self.catalog.release["id"], RELEASE)
        self.assertEqual(len(self.catalog.release["workbooks"]), 9)
        self.assertEqual(self.catalog.release["workbooks"]["WB-03"]["version"], "ver0004")
        self.assertEqual(self.catalog.release["workbooks"]["WB-04A"]["sha256"],
                         "57683ec2c4763e0e29cd72bf7548dff0680724eb95a97b5df9824c495f46de1b")

    def test_incompatible_release(self):
        with self.assertRaisesRegex(CatalogError, "Incompatible release"):
            load_catalog(self.root, "P1-REL-0006")

    def test_missing_named_table(self):
        content = BytesIO()
        Workbook().save(content)
        with self.assertRaisesRegex(CatalogError, "missing named table.*criterion_measures"):
            read_tables(content.getvalue(), "test_WB03.xlsx", ["criterion_measures"])

    def test_missing_key_and_invalid_context_join(self):
        for test, expression in (("key", "missing or duplicate key"), ("join", "incompatible function or dimension")):
            with self.subTest(test=test):
                tables = deepcopy(self.catalog.tables)
                row = tables["WB-03"]["requirement_function_contexts"].rows[0]
                row["context_id" if test == "key" else "dimension_id"] = None if test == "key" else "LD25"
                with self.assertRaisesRegex(CatalogError, expression):
                    Catalog(self.catalog.release, tables)


class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.catalog = configured_catalog()

    def test_lfo_rule_matches_once_and_exposes_wsp(self):
        input_mission = example("esperanza_mission.json")
        scores = rank_classes(input_mission, self.catalog)
        self.assertEqual({x["id"]: x["score"] for x in scores}, {"LFO": 9, "WSP": 2, "FRM": 0, "EA": 0, "IA": 0})
        wsp = next(c for c in scores if c["id"] == "WSP")
        self.assertEqual(len(wsp["hits"]), 1)
        self.assertGreater(len(wsp["hits"][0]["terms"]), 1)
        self.assertIsNone(evaluate(input_mission, [], self.catalog)["approved_class"])

    def test_overlap_and_unknown_trigger(self):
        mission = example("esperanza_mission.json")
        mission["fields"]["MI-04"]["value"] = "exceeded initial response"
        proposal = evaluate(mission, [], self.catalog)["nodes"]["mission_class"]
        self.assertTrue(proposal["triggers"]["C"])
        mission["fields"]["MI-04"] = {"status": "unknown", "value": None}
        proposal = evaluate(mission, [], self.catalog)["nodes"]["mission_class"]
        self.assertIsNone(proposal["triggers"]["M"])
        self.assertTrue(proposal["review_required"])
        insufficient = judgment_entry(proposal, rationale="", evidence_refs=[])
        self.assertEqual(judge(proposal, insufficient)["disposition"], "unresolved")

    def test_bad_time_offset_and_task_dimension(self):
        mission = example("esperanza_mission.json")
        mission["window"]["value"]["end"] = "2006-10-26T12:00:00-05:00"
        with self.assertRaisesRegex(WorkflowError, "agree with the mission time zone"):
            evaluate(mission, [], self.catalog)
        mission = example("esperanza_mission.json")
        mission["tasks"][0]["dimension_ids"].append("D-MON-04")
        with self.assertRaisesRegex(WorkflowError, "incompatible function context"):
            evaluate(mission, [], self.catalog)

    def test_specification_domain_explicit_zero_and_false(self):
        base = {"kind": "threshold", "unit": "fraction", "comparator": ">=", "target": 0,
                "reference_conditions": "Specified target population"}
        validate_spec(base, base, "Authorized test")
        for patch in ({"target": None}, {"target": 1.1}, {"target": False}, {"comparator": "<="}, {"unit": "m"}):
            with self.subTest(patch=patch), self.assertRaises(WorkflowError):
                validate_spec({**base, **patch}, base, "Authorized test")
        predicate = {"kind": "boolean", "unit": "boolean", "comparator": "==", "target": False,
                     "reference_conditions": "Declared predicate"}
        validate_spec(predicate, predicate, "Authorized test")
        with self.assertRaisesRegex(WorkflowError, "true compliance target"):
            validate_spec(predicate, {"unit": "boolean", "comparator": "TRUE"}, "Authorized test")

    def test_distribution_must_have_declared_dependence_and_valid_parameters(self):
        distribution = {"kind": "distribution", "family": "uniform", "parameters": {"lower": 1, "upper": 2},
                        "unit": "m", "reference_conditions": "Common test scope", "dependence": "Common geometry"}
        validate_uncertainty(distribution)
        for patch in ({"dependence": ""}, {"parameters": {"lower": 2, "upper": 1}}):
            with self.subTest(patch=patch), self.assertRaises(WorkflowError):
                validate_uncertainty({**distribution, **patch})
