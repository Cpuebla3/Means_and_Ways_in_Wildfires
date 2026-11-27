"""Persist local case snapshots and export the Step 3 workbook-shaped handoff."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from . import __version__
from .catalog import CatalogError, digest, read_bytes, relative_to_root, stable_hash
from .workflow import ACCEPTED, IN_SCOPE, SCHEMA_VERSION, WorkflowError, generated_id, require


CASE_FORMAT = "phase1.case"
EXPORT_FORMAT = "phase1.step3"
CASE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def to_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def from_json(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise WorkflowError(f"Invalid JSON: {exc}") from exc


def release_fingerprint(release):
    return {
        "id": release["id"], "manifest_sha256": release["manifest_sha256"],
        "workbooks": {k: (p["version"], p["sha256"]) for k, p in release["workbooks"].items()},
    }


def check_case_sources(mission, thesis_root):
    artifacts = mission.get("source_artifacts", [])
    require(isinstance(artifacts, list), "Source artifacts must be a list")
    seen = set()
    for artifact in artifacts:
        require(isinstance(artifact, dict) and all(isinstance(artifact.get(k), str)
                for k in ("id", "path", "sha256")), "Each source artifact needs an ID, relative path and SHA-256")
        require(artifact["id"] not in seen, f"Duplicate source artifact {artifact['id']}")
        seen.add(artifact["id"])
        source = relative_to_root(thesis_root, artifact["path"])
        if (actual := digest(read_bytes(source))) != artifact["sha256"]:
            raise CatalogError(f"{artifact['id']} {source.name}: expected SHA-256 {artifact['sha256']}, found {actual}")


def ensure_name(name):
    require(isinstance(name, str) and CASE_NAME.fullmatch(name) is not None,
            "Use 1–64 lowercase letters, digits, hyphens or underscores for the case filename")
    require(name.upper() not in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                                 *[f"LPT{i}" for i in range(1, 10)]},
            "Choose a filename that is valid on Windows")


def atomic_json(path, value):
    content = to_json(value)
    temp_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", mode="w",
                                encoding="utf-8", delete=False, newline="\n") as temp:
            temp_path = Path(temp.name)
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def load_case(case_dir, name):
    ensure_name(name)
    path = case_dir / f"{name}-case.json"
    data = read_bytes(path)
    record = from_json(data)
    require(isinstance(record, dict) and record.get("format") == CASE_FORMAT and
            record.get("schema_version") == SCHEMA_VERSION, "Unsupported saved case format or schema version")
    require(isinstance(record.get("release"), dict) and isinstance(record.get("mission"), dict)
            and isinstance(record.get("decisions"), list) and isinstance(record.get("evaluation"), dict),
            "Saved case is missing the release, mission, decision history or evaluation")
    return record, digest(data)


def save_case(case_dir, name, draft, expected, catalog):
    ensure_name(name)
    path = case_dir / f"{name}-case.json"
    current = digest(read_bytes(path)) if path.exists() else None
    require(current == expected,
            f"{path.name} already exists or changed since it was opened. Reopen it or choose a new name.")
    record = {
        "format": CASE_FORMAT, "schema_version": SCHEMA_VERSION, "name": name,
        "application_version": __version__,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release": catalog.release, "mission_sha256": stable_hash(draft["mission"]),
        "mission": draft["mission"], "decisions": draft["decisions"], "evaluation": draft["evaluation"],
    }
    atomic_json(path, record)
    return digest(read_bytes(path))


def selected_spec(node, prerequisite=None):
    if node is None:
        return None
    judgment = node["decision"]
    effective = judgment and judgment["disposition"] in ACCEPTED
    value = judgment["value"] if effective else node["proposal"]
    prereq_judgment = prerequisite["decision"] if prerequisite else None
    pending = value.get("pending") and not (prereq_judgment and prereq_judgment["disposition"] in ACCEPTED)
    return {
        **value,
        "target": value["target"] if effective else None,
        "proposal": node["proposal"], "sources": node["sources"],
        "judgment_id": judgment["decision_id"] if judgment else None,
        "readiness": judgment["disposition"] if judgment else "unreviewed",
        "threshold_approved": bool(effective and value.get("target") is not None),
        "condition": (judgment["condition"] if effective else node["condition"]),
        "prerequisite_status": "unresolved" if pending else "resolved" if value.get("pending") else None,
        "prerequisite_judgment_id": prereq_judgment["decision_id"] if prereq_judgment else None,
        "blocked_uses": node["blocks"] if (not effective or pending) else [],
    }


def step3_package(draft, catalog):
    result = draft["evaluation"]
    mission = draft["mission"]
    mid = mission["mission_id"]
    nodes = result["nodes"]
    require(result["approved_class"] is not None, "Approve the mission class before exporting a Step 3 handoff")
    class_decision = nodes["mission_class"]["decision"]
    class_id = class_decision["value"]
    version = {owner: pin["version"] for owner, pin in catalog.release["workbooks"].items()}
    class_ref = mission.get("class_record_ref")
    class_handoff = {
        "handoff_id": generated_id("H01", mid, class_id), "mission_id": mid,
        "mission_class_id": class_id, "class_decision_id": class_decision["decision_id"],
        "registry_release_id": catalog.release["id"], "class_definition_version": version["WB-01"],
        "decision_evidence_ref": class_decision["evidence_refs"], "status": class_decision["disposition"],
        "source_case_decision": class_ref,
    }
    functions = [{**f, "class_decision_id": class_decision["decision_id"],
                  "registry_release_id": catalog.release["id"], "disposition": f["role"],
                  "decision_rationale": nodes[f["node_id"]]["decision"]["rationale"]
                  if nodes[f["node_id"]]["decision"] else None}
                 for f in result["functions"]]
    dim_handoff = [{
        "handoff_id": generated_id("H02", mid, d["dimension_selection_id"]),
        "mission_id": mid, "class_decision_id": class_decision["decision_id"],
        "dimension_selection_id": d["dimension_selection_id"], "selection_id": d["selection_id"],
        "function_dimension_id": d["function_dimension_id"], "dimension_id": d["dimension_id"],
        "requirement_disposition": d["disposition"], "task_scope": d["task_scope"],
        "unresolved_condition": d.get("activation_condition"), "source_workbook_version": version["WB-02"],
        "registry_release_id": catalog.release["id"], "status": d.get("review_status", "unreviewed"),
    } for d in result["dimensions"]]
    prior = {(r["criterion_instance_id"], r["baseline_id"]): r
             for r in catalog.rows("WB-03", "baseline_instances") if r["mission_id"] == mid}
    prior_handoffs = catalog.index("WB-03", "baseline_conditioning_handoff", "baseline_instance_id")
    selected, memberships, handoffs = [], [], []
    for criterion in result["criteria"]:
        if criterion["selection"] not in {"include", "conditional"}:
            continue
        ci = criterion["criterion_instance_id"]
        baseline = selected_spec(nodes[criterion["baseline_spec_node_id"]])
        case = selected_spec(nodes[criterion["case_spec_node_id"]], nodes.get(criterion["case_prerequisite_node_id"]))
        activation = "conditional" if criterion["selection"] == "conditional" else "active"
        accepted_memberships = criterion["memberships"]
        selected.append({
            **criterion, **criterion["scope"], "activation_status": activation,
            "activation_predicate": criterion["condition"], "resolution_status":
                "resolved_baseline" if baseline["threshold_approved"] else "unresolved_baseline",
            "actual_unit": baseline["unit"], "threshold_numeric":
                baseline["target"] if baseline["threshold_approved"] and baseline["kind"] == "threshold" else None,
            "threshold_boolean":
                baseline["target"] if baseline["threshold_approved"] and baseline["kind"] == "boolean" else None,
            "reference_conditions": baseline.get("reference_conditions"),
            "baseline_specification": baseline, "case_specification": case,
            "baseline_ids": [b["baseline_id"] for b in accepted_memberships],
        })
        for link in accepted_memberships:
            bid = link["baseline_id"]
            old = prior.get((ci, bid), {})
            bi = old.get("baseline_instance_id") or generated_id("BI", mid, ci, bid)
            common = {"mission_id": mid, "baseline_instance_id": bi, "baseline_id": bid,
                      "requirement_id": criterion["requirement_id"], "criterion_instance_id": ci,
                      "function_dimension_id": criterion["function_dimension_id"],
                      "dimension_selection_id": criterion["dimension_selection_id"], "activation_status": activation}
            memberships.append({
                **common, "baseline_group_id": old.get("baseline_group_id") or generated_id("BG", mid, bid),
                "criterion_link_id": link["criterion_link_id"], "ownership_role": link["ownership_role"],
                "task_scope": criterion["scope"]["task_scope"], "status": criterion["status"],
                "source": catalog.source("WB-03", "bl_criterion_links", link["criterion_link_id"]),
            })
            handoffs.append({
                **common, "handoff_id": prior_handoffs.get(bi, {}).get("handoff_id") or generated_id("H03", mid, bi),
                "baseline_resolution_status": "resolved" if baseline["threshold_approved"] else "unresolved",
                "pending_resolution": baseline["blocked_uses"],
                "case_readiness": case["readiness"], "case_pending_conditions":
                    case.get("pending") if case["prerequisite_status"] == "unresolved" else None,
                "source_workbook_version": version["WB-03"], "status": criterion["status"],
            })
    obligations = [{**item, "effective_specification":
                    selected_spec(nodes[item["node_id"]], nodes.get(item["case_prerequisite_node_id"]))}
                   for item in result["obligations"]]
    active_ids = {f["function_id"] for f in functions if f["role"] in IN_SCOPE}
    later_refs = [ref for ref in mission.get("later_step_references", [])
                  if {ref["source_function_id"], ref["target_function_id"]} <= active_ids]
    coverage = {row["context_id"]: {**row, "criterion_instances": []}
                for row in mission.get("criterion_scopes", [])}
    for criterion in result["criteria"]:
        key = criterion["requirement_context_id"]
        coverage.setdefault(key, {"context_id": key, "criterion_instances": []})
        coverage[key]["criterion_instances"].append({
            "criterion_instance_id": criterion["criterion_instance_id"], "disposition": criterion["status"],
            "selection": criterion["selection"], "selection_node_id": criterion["node_id"],
        })
    return {
        "format": EXPORT_FORMAT, "schema_version": SCHEMA_VERSION, "stage": "baseline_requirements",
        "application_version": __version__,
        "mission_sha256": stable_hash(mission), "release": catalog.release,
        "case_identity": {"case_id": mission.get("case_id"), "version": mission.get("case_version"),
                          "mission_id": mid, "reference_scenario_id": mission.get("reference_scenario_id")},
        "mission": mission, "approved_class": class_id, "mission_class_handoff": class_handoff,
        "class_assessment": result["class_assessment"], "mission_selected_functions": functions,
        "mission_selected_dimensions": result["dimensions"], "function_dimension_handoff": dim_handoff,
        "baseline_capabilities": [b for b in result["capabilities"] if b["selection"] == "include"],
        "baseline_criterion_instances": selected, "baseline_instances": memberships,
        "baseline_conditioning_handoff": handoffs, "criterion_scope_review": list(coverage.values()),
        "case_obligations": obligations, "constraints": result["constraints"],
        "later_step_references": later_refs, "supporting_roles": result["supporting_roles"],
        "decision_history": draft["decisions"], "current_proposals": nodes, "open_items": result["open_items"],
    }
