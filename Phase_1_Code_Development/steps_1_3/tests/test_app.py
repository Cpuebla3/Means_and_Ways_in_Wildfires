"""Run the application routes against the verified source release."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from Phase_1_Code_Development.steps_1_3.app import create_app
from Phase_1_Code_Development.steps_1_3.case_io import atomic_json
from Phase_1_Code_Development.steps_1_3.workflow import ACCEPTED

from test_workflow import CODE_ROOT, configured_catalog, example, judgment_entry


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.thesis, cls.catalog = configured_catalog()

    def setUp(self):
        self.temp = TemporaryDirectory(prefix="phase1-verification-")
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.client = create_app(self.catalog, CODE_ROOT, self.thesis, self.output).test_client()

    def json_request(self, method, path, payload=None, status=200):
        response = self.client.open(path, method=method, json=payload)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True)[:650])
        return response.get_json()

    def create(self, mission):
        return self.json_request("POST", "/api/drafts", {"mission": mission})

    def decide(self, draft, target, action="retain", **extra):
        node = draft["evaluation"]["nodes"][target]
        return self.json_request("POST", f"/api/drafts/{draft['id']}/judgments",
                                 {"revision": draft["revision"], **judgment_entry(node, action, **extra)})

    def batch(self, draft, kind):
        return self.json_request("POST", f"/api/drafts/{draft['id']}/batch",
                                 {"revision": draft["revision"], "kind": kind, "analyst": "Workflow verification",
                                  "evidence_quality": 2, "confidence": 2})

    def populate(self):
        mission = self.json_request("GET", "/api/examples/esperanza")
        draft = self.create(mission)
        self.assertEqual(draft["evaluation"]["class_assessment"]["proposed_class"], "LFO")
        draft = self.decide(draft, "mission_class")
        for kind in ("function", "dimension", "capability", "measure"):
            draft = self.batch(draft, kind)
        return draft

    def test_esperanza_review_save_reopen_export(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        draft = self.populate()
        result = draft["evaluation"]
        self.assertEqual({f["function_id"] for f in result["functions"] if f["role"] == "active"},
                         {"F-DET", "F-MON", "F-SUP", "F-PP"})
        self.assertEqual(sum(d["disposition"] == "active" for d in result["dimensions"]), 21)
        self.assertEqual(result["supporting_roles"][0]["role_id"], "EF-DS-001")
        ci = "EF-CI-LD09-02-CASE"
        self.assertTrue(result["nodes"][f"baseline:{ci}"]["triggers"]["M"])
        self.assertTrue(result["nodes"][f"baseline:{ci}"]["triggers"]["Q"])
        draft = self.decide(draft, f"baseline:{ci}", "defer", rationale="No governing numeric baseline.")
        draft = self.decide(draft, f"case_spec:{ci}")
        draft = self.decide(draft, "obligation:EF-OBL-001")
        draft = self.decide(draft, "obligation:EF-OBL-002")
        draft = self.json_request("POST", f"/api/drafts/{draft['id']}/save",
                                  {"revision": draft["revision"], "name": "esperanza-test"})
        reopened = self.json_request("POST", "/api/cases/esperanza-test/open", {})
        self.assertFalse(reopened["read_only"])
        self.assertEqual(reopened["decisions"], draft["decisions"])
        package = self.json_request("POST", f"/api/drafts/{reopened['id']}/export",
                                    {"revision": reopened["revision"], "name": "esperanza-test", "write": True})
        self.assertEqual(package, json.loads((self.output / "esperanza-test-step3.json").read_text(encoding="utf-8")))
        self.assertEqual(package["approved_class"], "LFO")
        self.assertEqual(len(package["criterion_scope_review"]), 63)
        self.assertEqual(len(package["baseline_criterion_instances"]), 16)
        self.assertEqual(len(package["baseline_instances"]), 18)
        self.assertEqual(len(package["baseline_conditioning_handoff"]), 18)
        self.assertEqual(len(package["case_obligations"]), 2)
        targets = {c["criterion_instance_id"]: c for c in package["baseline_criterion_instances"]}
        error = targets[ci]
        self.assertEqual(error["selection"], "conditional")
        self.assertIsNone(error["baseline_specification"]["target"])
        self.assertEqual(error["baseline_specification"]["readiness"], "unresolved")
        self.assertIn("Baseline-relative conditioning", error["baseline_specification"]["blocked_uses"])
        self.assertEqual(error["case_specification"]["target"], 10)
        self.assertEqual(error["case_specification"]["unit"], "m")
        self.assertTrue(error["case_specification"]["threshold_approved"])
        for suffix in ("DW", "OH"):
            shared = targets[f"EF-CI-LD21-01-{suffix}"]
            self.assertEqual(set(shared["baseline_ids"]), {"C_B,8", "C_B,10"})
            self.assertEqual(shared["native_unit"], "h")
        self.assertEqual(package["later_step_references"][0]["function_link_id"], "FL-004")
        self.assertNotIn("FL-004", {c["requirement_id"] for c in targets.values()})

    def test_upstream_change_preserves_unaffected_judgments_and_stale_override(self):
        draft = self.populate()
        path = f"/api/drafts/{draft['id']}/mission"
        original = draft["evaluation"]["nodes"]["function:F-PP"]["decision"]["decision_id"]
        draft = self.decide(draft, "function:F-MON", "revise", value="supporting")
        changed = deepcopy(draft["mission"])
        task = next(t for t in changed["tasks"] if t["function_id"] == "F-MON")
        task["description"] += " Limit the monitoring assignment to the northern sector."
        result = self.json_request("PATCH", path, {"revision": draft["revision"], "mission": changed})
        nodes = result["evaluation"]["nodes"]
        self.assertTrue(nodes["function:F-MON"]["stale_decision"])
        self.assertEqual(nodes["function:F-MON"]["stale_decision"]["action"], "revise")
        self.assertIsNone(nodes["function:F-MON"]["decision"])
        self.assertEqual(nodes["function:F-PP"]["decision"]["decision_id"], original)
        self.assertTrue(any(i["kind"] == "inactive_prior_decision" for i in result["evaluation"]["open_items"]))
        self.json_request("PATCH", path, {"revision": draft["revision"], "mission": changed}, status=400)

    def test_case_tolerance_and_prerequisite_have_separate_review_bases(self):
        draft = self.populate()
        ci = "EF-CI-LD09-02-CASE"
        target = f"case_spec:{ci}"
        path = f"/api/drafts/{draft['id']}/export"
        proposed = self.json_request("POST", path, {"revision": draft["revision"], "name": "candidate"})
        error = next(c for c in proposed["baseline_criterion_instances"] if c["criterion_instance_id"] == ci)
        self.assertIsNone(error["case_specification"]["target"])
        self.assertEqual(error["case_specification"]["proposal"]["target"], 10)
        draft = self.decide(draft, target, "revise", value={"unit": "min"}, authority_ref="TEST-001")
        self.assertEqual(draft["recorded"][0]["disposition"], "rejected")
        self.assertIn("source-backed actual unit", draft["recorded"][0]["validation"][0]["message"])
        draft = self.decide(draft, target)
        draft = self.decide(draft, f"prerequisite:{ci}", "revise", value="resolved",
                            rationale="Test evidence defines a receiving decision and time-aligned reference geometry.")
        changed = draft["evaluation"]["nodes"][target]
        self.assertIsNotNone(changed["stale_decision"])
        self.assertFalse(changed["triggers"]["Q"])
        draft = self.decide(draft, target)
        reviewed = self.json_request("POST", path, {"revision": draft["revision"], "name": "reviewed"})
        error = next(c for c in reviewed["baseline_criterion_instances"] if c["criterion_instance_id"] == ci)
        self.assertEqual(error["case_specification"]["prerequisite_status"], "resolved")
        self.assertEqual(error["case_specification"]["target"], 10)
        self.assertIsNone(error["baseline_specification"]["target"])

    def test_reopening_release_mismatch_keeps_saved_snapshot_read_only(self):
        mission = example("esperanza_mission.json")
        draft = self.decide(self.create(mission), "mission_class")
        draft = self.json_request("POST", f"/api/drafts/{draft['id']}/save",
                                  {"revision": draft["revision"], "name": "mismatch"})
        filename = self.output / "mismatch-case.json"
        content = json.loads(filename.read_text(encoding="utf-8"))
        content["release"]["workbooks"]["WB-03"]["sha256"] = "0" * 64
        atomic_json(filename, content)
        reopened = self.json_request("POST", "/api/cases/mismatch/open", {})
        self.assertTrue(reopened["read_only"])
        self.assertTrue(any("Release mismatch" in d for d in reopened["diagnostics"]))
        self.assertEqual(reopened["evaluation"]["approved_class"], "LFO")
        self.json_request("POST", f"/api/drafts/{reopened['id']}/save",
                          {"revision": reopened["revision"], "name": "mismatch"}, status=400)

    def test_non_esperanza_mission_uses_same_review_path(self):
        mission = self.json_request("GET", "/api/examples/template")
        mission.update(mission_id="DEMO-MON-1", source_refs=["TEST-001"])
        def fact(value):
            return {"status": "known", "value": value, "refs": ["TEST-001"]}
        mission["fields"].update({
            "MI-02": fact("Observe the existing watershed fire and provide updates."),
            "MI-04": fact("Known watershed fire under observation."),
            "MI-05": fact("Reconnaissance of the active perimeter."),
            "MI-07": fact(["Remote watershed"]),
            "MI-08": fact("Provide fire-state updates for the duty officer."),
        })
        mission["area"] = fact({"description": "Example watershed"})
        mission["window"] = fact({"start": "2026-11-26T08:00:00-08:00",
                                  "end": "2026-11-26T10:00:00-08:00", "zone": "America/Los_Angeles"})
        mission["fire_at_start"] = fact({"description": "Known active perimeter", "main_fire_known": True})
        mission["tasks"] = [
            {"task_id": "T-MON", "function_id": "F-MON", "status": "active",
             "description": "Update the existing fire perimeter.", "refs": ["TEST-001"],
             "dimension_ids": ["D-MON-04"]},
            {"task_id": "T-DET", "function_id": "F-DET", "status": "outside_scope",
             "description": "The assignment covers an existing fire.", "refs": ["TEST-001"]},
        ]
        draft = self.create(mission)
        self.assertEqual(draft["evaluation"]["class_assessment"]["proposed_class"], "FRM")
        draft = self.decide(draft, "mission_class")
        for kind in ("function", "dimension"):
            draft = self.batch(draft, kind)
        candidate = next(r for r in draft["evaluation"]["criteria"] if r["requirement_id"] == "R-LD09-02")
        draft = self.decide(draft, "capability:C_B,3", "revise", value="include")
        draft = self.decide(draft, candidate["node_id"], "revise", value="include")
        self.assertIn(draft["recorded"][0]["disposition"], ACCEPTED)
        package = self.json_request("POST", f"/api/drafts/{draft['id']}/export",
                                    {"revision": draft["revision"], "name": "watershed"})
        self.assertEqual(package["approved_class"], "FRM")
        self.assertEqual({f["function_id"] for f in package["mission_selected_functions"] if f["role"] == "active"},
                         {"F-MON"})
        self.assertEqual(package["case_obligations"], [])
        self.assertEqual(package["later_step_references"], [])
        self.assertEqual(len(package["baseline_criterion_instances"]), 1)
        self.assertIsNone(package["baseline_criterion_instances"][0]["case_specification"]["target"])
