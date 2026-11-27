"""Mission classification, function decomposition, and baseline requirements."""

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .catalog import stable_hash


SCHEMA_VERSION = "1.0.0"
PRESENT = {"known", "missing", "unknown", "not_applicable"}
TASK_ROLES = {"active", "supporting", "conditional", "outside_scope", "unknown"}
IN_SCOPE = {"active", "supporting", "conditional"}
ACCEPTED = {"accepted", "conditionally_accepted"}
AUTHORITY = "EF-APP-20261126"
TRIGGER_LABELS = {
    "M": "Missing required information", "A": "Unresolved ambiguity",
    "C": "Conflicting evidence or results", "Q": "Insufficient evidence",
    "V": "Mandatory expert or authority review",
}
PHRASES = {"MI-04", "MI-05", "MI-07", "MI-08"}
MI_REQUIRED = {"MI-02", "MI-05", "MI-08"}
SPEC_TYPES = {"baseline_specification", "case_specification", "case_obligation"}


class WorkflowError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise WorkflowError(message)


def text_value(value):
    return isinstance(value, str) and bool(value.strip())


def finite(value):
    return type(value) in (int, float) and isfinite(value)


def as_list(value, label):
    require(isinstance(value, list), f"{label} must be a list")
    return value


def require_text_list(value, label):
    require(all(text_value(x) for x in as_list(value, label)), f"{label} must contain text")
    return value


def unique_records(records, key, label):
    result = {}
    for item in as_list(records, label):
        require(isinstance(item, dict) and text_value(item.get(key)), f"{label} requires {key}")
        require(item[key] not in result, f"{label} has duplicate {key} {item[key]}")
        result[item[key]] = item
    return result


def known(field):
    return field.get("value") if field.get("status") == "known" else None


def validate_fact(field, label):
    require(isinstance(field, dict) and text_value(field.get("status")) and field["status"] in PRESENT,
            f"{label}: choose a field status")
    if field["status"] == "known":
        require(field.get("value") is not None and field.get("value") != "", f"{label}: enter a value")
    else:
        require(field.get("value") is None, f"{label}: clear the value when it is {field['status']}")
    if field["status"] == "not_applicable":
        require(text_value(field.get("reason")), f"{label}: explain why it does not apply")
    require_text_list(field.get("refs", []), f"{label} references")


def parse_window(window):
    require(isinstance(window, dict), "Enter start, end and IANA time zone")
    try:
        zone = ZoneInfo(window.get("zone", ""))
        start, end = (datetime.fromisoformat(window[k]) for k in ("start", "end"))
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise WorkflowError("Enter a valid IANA zone and ISO 8601 start/end with UTC offsets") from exc
    for point in (start, end):
        require(point.utcoffset() is not None, "Start/end must include UTC offsets")
        local = point.astimezone(zone)
        require(local.replace(tzinfo=None) == point.replace(tzinfo=None) and local.utcoffset() == point.utcoffset(),
                "Start/end offsets must agree with the mission time zone")
    require(start.astimezone(timezone.utc) < end.astimezone(timezone.utc), "Mission end must follow start")


def validate_mission(mission, catalog):
    require(isinstance(mission, dict) and mission.get("schema_version") == SCHEMA_VERSION,
            "Mission schema_version must be 1.0.0")
    require(text_value(mission.get("mission_id")), "Enter a mission ID")
    fields = mission.get("fields")
    require(isinstance(fields, dict), "Enter the mission fields")
    allowed_fields = catalog.index("WB-01", "mission_input_fields")
    for key, item in fields.items():
        require(key in allowed_fields and key != "MI-01", f"Unknown mission field {key}")
        validate_fact(item, key)
        if known(item) is not None:
            if key == "MI-07":
                require_text_list(known(item), key)
            else:
                require(text_value(known(item)), f"{key}: enter text")
    explicit = known(fields.get("MI-03", {}))
    require(explicit is None or explicit in catalog.index("WB-01", "mission_classes"), "MI-03: unknown assigned class")
    for key in ("area", "window", "fire_at_start", "assets"):
        validate_fact(mission.get(key, {}), key)
    if (window := known(mission["window"])) is not None:
        parse_window(window)
    area = known(mission["area"])
    if area is not None:
        require(isinstance(area, dict) and text_value(area.get("description")), "Area requires a description")
        if area.get("provisional_km2") is not None:
            require(finite(area["provisional_km2"]) and area["provisional_km2"] > 0, "Area must be positive")
    fire = known(mission["fire_at_start"])
    if fire is not None:
        require(isinstance(fire, dict) and text_value(fire.get("description")), "Describe the fire state")
    assets = unique_records(known(mission["assets"]) or [], "asset_id", "Assets")
    functions = catalog.index("WB-02", "operational_functions")
    dims = catalog.index("WB-02", "function_dimensions")
    for task in unique_records(mission.get("tasks", []), "task_id", "Tasks").values():
        require(text_value(task.get("function_id")) and task["function_id"] in functions,
                f"{task['task_id']}: select a workbook function")
        require(text_value(task.get("status")) and task["status"] in TASK_ROLES and text_value(task.get("description")),
                f"{task['task_id']}: enter a task description and disposition")
        require_text_list(task.get("refs", []), "Task references")
        if task["status"] == "conditional":
            require(text_value(task.get("condition")), f"{task['task_id']}: enter the condition for activation")
        for asset in require_text_list(task.get("asset_ids", []), "Task assets"):
            require(asset in assets, f"{task['task_id']}: unknown asset {asset}")
        for dimension in require_text_list(task.get("dimension_ids", []), "Task dimensions"):
            require(dimension in dims and dims[dimension]["function_id"] == task["function_id"],
                    f"{task['task_id']}: incompatible function context {dimension}")
    contexts = catalog.index("WB-03", "requirement_function_contexts")
    case_scope = unique_records(mission.get("criterion_scopes", []), "context_id", "Criterion scopes")
    all_instance_ids = set()
    registered_instances = catalog.index("WB-03", "baseline_criterion_instances", "criterion_instance_id")
    for key, row in case_scope.items():
        require(key in contexts, f"Unknown requirement context {key}")
        require(row.get("status") in {"include", "conditional", "defer", "exclude"}, f"{key}: invalid scope status")
        require_text_list(row.get("refs", []), "Scope references")
        instances = unique_records(row.get("instances", []), "criterion_instance_id", f"{key} instances")
        for instance in instances.values():
            cid = instance["criterion_instance_id"]
            require(cid not in all_instance_ids, f"Duplicate criterion_instance_id {cid}")
            all_instance_ids.add(cid)
            if cid in registered_instances:
                prior = registered_instances[cid]
                context = contexts[key]
                require(prior["mission_id"] == mission["mission_id"] and
                        prior["requirement_id"] == context["requirement_id"] and
                        prior["function_dimension_id"] == context["function_dimension_id"] and
                        prior["target_id"] == instance.get("target_id"), f"{cid}: conflicts with its registered scope")
            require(instance.get("target_id") in (None, *assets) or text_value(instance.get("spatial_scope")),
                    f"{key}: unknown target without a spatial scope")
            disposition = instance.get("activation", row["status"])
            require(disposition in {"include", "conditional"}, f"{key}: invalid instance activation")
            if disposition == "conditional":
                require(text_value(instance.get("condition", row.get("condition"))),
                        f"{key}: document the conditional scope")
            if (spec := instance.get("case_specification")) is not None:
                require(isinstance(spec, dict), f"{key}: expected case specification object")
    selection_records = catalog.index("WB-02", "mission_selected_functions", "selection_id")
    for fn_id, row in unique_records(mission.get("function_record_refs", []), "function_id",
                                     "Workbook function references").items():
        prior = selection_records.get(row.get("selection_id"))
        require(prior and prior["function_id"] == fn_id and prior["mission_id"] == mission["mission_id"],
                f"{fn_id}: invalid workbook function selection reference")
        selected_dims = {d["function_dimension_id"]: d["dimension_selection_id"]
                         for d in catalog.rows("WB-02", "mission_selected_dimensions")
                         if d["selection_id"] == prior["selection_id"]}
        supplied = row.get("dimension_selection_ids", {})
        require(isinstance(supplied, dict) and all(selected_dims.get(k) == v for k, v in supplied.items()),
                f"{fn_id}: invalid workbook dimension selection reference")
    obligation_ids = set()
    template_ids = set(catalog.index("WB-03", "requirement_templates"))
    for oid, obligation in unique_records(mission.get("case_obligations", []), "obligation_id",
                                         "Case obligations").items():
        require(obligation.get("dependency_id") in template_ids | obligation_ids,
                f"{oid}: dependency must identify a requirement or earlier obligation")
        obligation_ids.add(oid)
        require(obligation.get("function_id") in functions and text_value(obligation.get("name")) and
                text_value(obligation.get("definition")) and isinstance(obligation.get("specification"), dict),
                f"{oid}: supply a function, name, definition and specification")
        require_text_list(obligation.get("baseline_ids"), f"{oid} capability IDs")
        require_text_list(obligation.get("refs", []), f"{oid} references")
    require_text_list(mission.get("source_refs", []), "Mission source references")


def source_refs(*records):
    return list(dict.fromkeys(ref for record in records for ref in (record or {}).get("refs", [])))


def rank_classes(mission, catalog):
    """Step 1. Apply a term only to its MI field and score a rule at most once."""
    fields = mission["fields"]
    terms_by_rule = defaultdict(list)
    for item in catalog.rows("WB-01", "mission_rule_terms"):
        terms_by_rule[item["rule_id"]].append(item)
    results = {r["mission_class_id"]: {"id": r["mission_class_id"], "name": r["name"],
                                     "definition": r["definition"], "score": 0, "hits": []}
               for r in catalog.rows("WB-01", "mission_classes")}
    for rule in catalog.rows("WB-01", "mission_class_rules"):
        field = fields.get(rule["input_field_id"], {})
        value = known(field)
        observations = value if isinstance(value, list) else [value or ""]
        terms = [t for t in terms_by_rule[rule["rule_id"]]
                 if any(re.search(r"(?<!\w)" + re.escape(t["term"].casefold()) + r"(?!\w)", text.casefold())
                        for text in observations)]
        if terms:
            cand = results[rule["mission_class_id"]]
            cand["score"] += rule["weight"]
            cand["hits"].append({
                "rule_id": rule["rule_id"], "field_id": rule["input_field_id"], "fact": value,
                "terms": [t["term"] for t in terms], "weight": rule["weight"],
                "reason": rule["operational_rationale"], "refs": field.get("refs", []),
                "source": catalog.source("WB-01", "mission_class_rules", rule["rule_id"]),
                "term_sources": [catalog.source("WB-01", "mission_rule_terms",
                                                [t["rule_id"], t["term_index"]]) for t in terms],
            })
    maximum = max(c["score"] for c in results.values())
    for candidate in results.values():
        score = candidate["score"]
        candidate["rank"] = ("primary" if score and score == maximum else
                             "secondary" if score and score * 10 >= maximum * 3 else "weak_or_no_match")
    return sorted(results.values(), key=lambda c: (-c["score"], c["id"]))


def trigger_map(**flags):
    return {code: flags.get(code, False) for code in TRIGGER_LABELS}


def index_by(rows, field):
    index = defaultdict(list)
    for row in rows:
        index[row[field]].append(row)
    return index


def generated_id(prefix, *parts):
    return f"{prefix}-{stable_hash(parts)[:20]}"


def shown_status(node):
    if node["decision"] is not None:
        return node["decision"]["disposition"]
    return "review_required" if node["review_required"] else "proposed"


def accepted_value(node):
    decision = node["decision"] if node else None
    return decision["value"] if decision and decision["disposition"] in ACCEPTED else None


def append_block(open_items, key, kind, text, blocks):
    open_items.append({"target_id": key, "kind": kind, "description": text, "blocks": blocks})


class Evaluation:
    def __init__(self, mission, decisions, catalog):
        self.mission = mission
        self.catalog = catalog
        self.latest = {d["target_id"]: d for d in decisions}
        self.nodes = {}
        self.open_items = []
        self.mission_id = mission["mission_id"]
        self.result = {
            "nodes": self.nodes, "functions": [], "dimensions": [], "capabilities": [],
            "criteria": [], "constraints": [], "obligations": [], "open_items": self.open_items,
        }

    def add(self, key, kind, label, proposal, basis, *, explanation="", sources=(), refs=(),
            triggers=None, alternatives=(), condition=None, blocks=(), constraints=(), spec_contract=None):
        fingerprint = stable_hash([SCHEMA_VERSION, self.catalog.release["manifest_sha256"], self.mission_id,
                                   kind, key, proposal, basis, condition, list(sources), list(refs), triggers,
                                   list(constraints), spec_contract])
        prior = self.latest.get(key)
        decision = prior if prior and prior["basis"] == fingerprint else None
        node = {
            "id": key, "kind": kind, "label": label, "proposal": proposal, "basis": fingerprint,
            "why": explanation, "sources": list(sources), "refs": list(dict.fromkeys(refs)),
            "triggers": triggers or trigger_map(), "review_required": any(v is not False for v in (triggers or {}).values()),
            "alternatives": list(alternatives), "condition": condition, "blocks": list(blocks),
            "constraints": list(constraints), "decision": decision, "stale_decision": prior if not decision else None,
            "spec_contract": spec_contract,
        }
        self.nodes[key] = node
        if not decision or decision["disposition"] == "unresolved":
            if node["review_required"] or not decision or node["stale_decision"]:
                append_block(self.open_items, key, kind, label, list(blocks))
        return node

    def step1(self):
        fields = self.mission["fields"]
        candidates = rank_classes(self.mission, self.catalog)
        primary = [c for c in candidates if c["rank"] == "primary"]
        secondary = [c for c in candidates if c["rank"] == "secondary"]
        explicit_field = fields.get("MI-03", {})
        explicit = known(explicit_field)
        conflict = bool(explicit and primary and explicit not in [c["id"] for c in primary])
        status_hits = [c for c in candidates if any(h["field_id"] == "MI-04" for h in c["hits"])]
        status_conflict = len(status_hits) > 1
        required_gaps = sorted(k for k in MI_REQUIRED if known(fields.get(k, {})) is None)
        missing_status = fields.get("MI-04", {}).get("status", "missing")
        proposed_id = (explicit if explicit and source_refs(explicit_field) and not conflict else
                       primary[0]["id"] if len(primary) == 1 else None)
        refs = source_refs(*(fields.get(k) for k in sorted(PHRASES)), explicit_field)
        class_node = self.add(
            "mission_class", "class", "Governing mission class", proposed_id,
            {key: fields.get(key) for key in sorted(PHRASES | MI_REQUIRED | {"MI-03"})},
            explanation=("Authoritative assignment is consistent with the rule evidence."
                         if explicit and explicit == proposed_id and source_refs(explicit_field)
                         else "The highest nonzero workbook score proposes the governing class. "
                              "Review tied, competing, and weak candidates against the mission effect."),
            sources=[self.catalog.source("WB-01", "mission_selection_guidance", f"SG-{i:02d}") for i in range(1, 12)],
            refs=refs,
            triggers=trigger_map(M=True if required_gaps else None if missing_status == "unknown" else False,
                                 A=len(primary) != 1 or bool(secondary), C=conflict or status_conflict,
                                 Q=bool(explicit and not source_refs(explicit_field)) or not proposed_id),
            alternatives=[c["id"] for c in candidates],
            blocks=["Step 2 function selection"],
            constraints=[f"Required mission field {k} is unresolved" for k in required_gaps],
        )
        self.result["class_assessment"] = {"candidates": candidates, "assigned_class": explicit,
                                           "proposed_class": proposed_id, "node_id": class_node["id"]}
        return accepted_value(class_node)

    def step2(self, class_id):
        """Use task evidence to interpret, rather than automatically activate, class membership."""
        catalog = self.catalog
        tasks = index_by(self.mission["tasks"], "function_id")
        mappings = {(r["mission_class_id"], r["function_id"]): r
                    for r in catalog.rows("WB-02", "mission_function_map")}
        dimensions = index_by(catalog.rows("WB-02", "function_dimensions"), "function_id")
        definitions = catalog.index("WB-02", "capability_dimensions")
        supplied_scope = {r["function_id"]: r for r in self.mission.get("function_record_refs", [])}
        approved_dims = {}
        for fn in catalog.rows("WB-02", "operational_functions"):
            fn_id = fn["function_id"]
            assigned = tasks[fn_id]
            mapping = mappings.get((class_id, fn_id))
            roles = {t["status"] for t in assigned}
            distinct_roles = [v for v in ("active", "supporting", "conditional", "outside_scope") if v in roles]
            if "unknown" in roles:
                role = None
            else:
                role = distinct_roles[0] if distinct_roles else None if mapping else "outside_scope"
            conflict = "outside_scope" in roles and bool(roles.intersection(IN_SCOPE))
            condition = " or ".join(t["condition"] for t in assigned if t["status"] == "conditional") or None
            exception = role in IN_SCOPE and not mapping
            sources = [catalog.source("WB-02", "operational_functions", fn_id)]
            refs = source_refs(*assigned)
            if mapping:
                sources.append(catalog.source("WB-02", "mission_function_map", mapping["mapping_id"]))
            record = supplied_scope.get(fn_id, {})
            if record.get("source"):
                sources.append(record["source"])
            node = self.add(f"function:{fn_id}", "function", fn["name"], role,
                            [record, assigned, class_id, mapping],
                            explanation=("Mission task evidence and reviewed class membership."
                                         if mapping else "Function is outside the class reference set."),
                            refs=refs, sources=sources, condition=condition,
                            triggers=trigger_map(M=None if "unknown" in roles else not assigned and bool(mapping),
                                                 A=exception, C=conflict, Q=bool(assigned and not refs)),
                            alternatives=sorted(IN_SCOPE | {"outside_scope"}),
                            blocks=["Dimension review and Step 5 link activation"])
            selected_role = accepted_value(node)
            selection_id = record.get("selection_id") or generated_id("FS", self.mission_id, fn_id)
            self.result["functions"].append({
                **fn, "selection_id": selection_id, "mission_id": self.mission_id, "function_id": fn_id,
                "mission_class_id": class_id, "mapping_id": mapping["mapping_id"] if mapping else None,
                "role": selected_role, "proposal": role, "task_scope": assigned,
                "exception": bool(selected_role in IN_SCOPE and not mapping),
                "activation_condition": (node["decision"]["condition"] if selected_role == "conditional" else None),
                "node_id": node["id"], "status": shown_status(node),
            })
            for link in dimensions[fn_id]:
                key = link["function_dimension_id"]
                definition = definitions[link["dimension_id"]]
                saved_dim = record.get("dimension_selection_ids", {}).get(key)
                dsid = saved_dim or generated_id("DS", self.mission_id, key)
                required = key in {d for t in assigned for d in t.get("dimension_ids", [])}
                proposal = ("outside_scope" if selected_role == "outside_scope" else
                            selected_role if required else "candidate")
                dim_row = {**link, "name": definition["established_label"], "definition": definition["definition"],
                           "dimension_selection_id": dsid, "selection_id": selection_id,
                           "mission_id": self.mission_id, "task_scope": assigned,
                           "proposal": proposal, "node_id": None, "disposition": None}
                if selected_role in IN_SCOPE:
                    dim_node = self.add(
                        f"dimension:{key}", "dimension", definition["established_label"], proposal,
                        [selected_role, node["basis"], dsid],
                        explanation="Workbook function context. Review its relevance to the selected task.",
                        sources=[catalog.source("WB-02", "function_dimensions", key)], refs=refs,
                        triggers=trigger_map(A=not required), condition=node["decision"]["condition"],
                        alternatives=sorted(IN_SCOPE | {"outside_scope"}), blocks=["Step 3 criterion applicability"])
                    dim_row.update(node_id=dim_node["id"], disposition=accepted_value(dim_node),
                                   review_status=shown_status(dim_node),
                                   activation_condition=dim_node["decision"]["condition"] if dim_node["decision"] else None)
                    if dim_row["disposition"] in IN_SCOPE:
                        approved_dims[key] = dim_row
                elif selected_role == "outside_scope":
                    dim_row.update(disposition="outside_scope", review_status="inherited_from_function")
                self.result["dimensions"].append(dim_row)
        return approved_dims

    def step3(self, dimensions):
        """Instantiate one scoped criterion and retain all of its capability memberships."""
        c = self.catalog
        scope_rows = {r["context_id"]: r for r in self.mission.get("criterion_scopes", [])}
        templates = c.index("WB-03", "requirement_templates")
        measures = c.index("WB-03", "criterion_measures", "requirement_id")
        memberships = index_by(c.rows("WB-03", "bl_criterion_links"), "requirement_id")
        dependencies = index_by(c.rows("WB-03", "requirement_dependencies"), "requirement_id")
        drafts = c.index("WB-03", "baseline_specification_drafts", "requirement_id")
        capability_defs = c.index("WB-03", "baseline_capabilities")
        records = []
        by_capability = defaultdict(list)
        seen_ids = set()
        for context in c.rows("WB-03", "requirement_function_contexts"):
            d = dimensions.get(context["function_dimension_id"])
            if not d:
                continue
            req_id = context["requirement_id"]
            req, measure = templates[req_id], measures[req_id]
            scope = scope_rows.get(context["context_id"], {})
            default_id = generated_id("CI", self.mission_id, context["context_id"])
            for instance in scope.get("instances") or [{"criterion_instance_id": default_id}]:
                ci = instance["criterion_instance_id"]
                require(ci not in seen_ids, f"Duplicate criterion_instance_id {ci}")
                seen_ids.add(ci)
                role = instance.get("activation", scope.get("status", "defer"))
                if role == "include" and d["disposition"] == "conditional":
                    role = "conditional"
                conditions = list(dict.fromkeys(p for p in (instance.get("condition") or scope.get("condition"),
                                                            d.get("activation_condition")) if p))
                condition = " AND ".join(conditions) or None
                links = memberships[req_id]
                refs = source_refs(scope, instance, *d["task_scope"])
                sources = [c.source("WB-03", "requirement_function_contexts", context["context_id"]),
                           c.source("WB-03", "requirement_templates", req_id),
                           c.source("WB-03", "criterion_measures", measure["measure_id"])]
                sources.extend(scope.get("sources", []))
                if instance.get("source"):
                    sources.append(instance["source"])
                for link in links:
                    by_capability[link["baseline_id"]].append((ci, d["node_id"], role, condition))
                records.append((context, d, req, measure, scope, instance, ci, role, condition, links, refs, sources))

        for baseline_id, members in by_capability.items():
            definition = capability_defs[baseline_id]
            # Link all candidate contexts. An unreviewed context cannot satisfy demand.
            proposes = any(row[2] in {"include", "conditional"} for row in members)
            refs = sorted({ref for record in records if any(link["baseline_id"] == baseline_id for link in record[9])
                           for ref in record[10]})
            node = self.add(
                f"capability:{baseline_id}", "capability", definition["name"], "include" if proposes else "review",
                members, explanation="Candidate capability derived from qualifying criterion contexts.",
                triggers=trigger_map(A=not proposes), refs=refs,
                sources=[c.source("WB-03", "baseline_capabilities", baseline_id)],
                alternatives=["include", "exclude"], blocks=["Capability membership selection"])
            self.result["capabilities"].append({**definition, "node_id": node["id"], "selection": accepted_value(node)})

        for context, d, req, measure, scope, instance, ci, role, condition, links, refs, sources in records:
            active_links = [link for link in links if accepted_value(self.nodes[f"capability:{link['baseline_id']}"]) == "include"]
            scope_details = {
                "target_id": instance.get("target_id"), "spatial_scope": instance.get("spatial_scope") or known(self.mission["area"]),
                "time_window": instance.get("time_window") or known(self.mission["window"]),
                "metric_variable": instance.get("metric_variable"),
                "population": instance.get("population"), "task_scope": d["task_scope"],
            }
            affected_fields = [d["disposition"], self.nodes[d["node_id"]]["basis"], scope_details,
                               self.mission["area"], self.mission["window"],
                               self.mission["fire_at_start"] if context["function_id"] == "F-MON" else None]
            measure_node = self.add(
                f"measure:{ci}", "measure", measure["measure_name"], role,
                [affected_fields, context["context_id"], bool(active_links)],
                explanation=scope.get("reason") or req["activation_rule"], sources=sources, refs=refs,
                triggers=trigger_map(A=role == "defer", M=not active_links and role != "exclude",
                                     Q=role in {"include", "conditional"} and not refs),
                condition=condition, alternatives=["include", "conditional", "exclude"],
                blocks=["Criterion selection and specification review"],
                constraints=[] if active_links or role == "exclude" else ["Approve at least one linked capability first."])
            selection = accepted_value(measure_node)
            if selection == "conditional":
                condition = measure_node["decision"]["condition"]
            baseline_node = case_node = prerequisite = None
            draft = drafts[req["requirement_id"]]
            if selection in ("include", "conditional"):
                missing_scope = [f"Specify the criterion's {label} before approving a quantitative setting."
                                 for field, label in (("spatial_scope", "spatial scope"), ("time_window", "time window"))
                                 if not scope_details[field]]
                spec = {
                    "kind": "boolean" if measure["unit"] == "boolean" else "threshold",
                    "comparator": measure["acceptance_direction"], "unit": measure["unit"],
                    "target": None, "reference_conditions": instance.get("baseline_reference_conditions"),
                    "resolution_status": "unresolved",
                }
                baseline_node = self.add(
                    f"baseline:{ci}", "baseline_specification", f"{measure['measure_name']} · baseline tolerance",
                    spec, [affected_fields, selection, measure_node["decision"]["condition"], draft],
                    explanation=measure["derivation_rule"], refs=refs, sources=sources + [
                        c.source("WB-03", "baseline_specification_drafts", req["requirement_id"])],
                    triggers=trigger_map(M=True, Q=True),
                    constraints=missing_scope,
                    blocks=["Baseline-relative conditioning", "Definitive screening against the baseline"])
                case_spec = instance.get("case_specification") or {**spec, "resolution_status": "unresolved"}
                # The release explicitly authorizes the scoped Boolean proxy for LD17;
                # the canonical measure retains its original comparator and unit.
                override = (req["requirement_id"] == "R-LD17-01"
                            and "EF-DEC-010" in case_spec.get("decision_refs", [])
                            and case_spec.get("authority_ref") == AUTHORITY
                            and (instance.get("source") or {}).get("table") == "baseline_criterion_instances")
                case_contract = {"unit": "boolean", "comparator": "=="} if override else spec
                case_sources = sources + ([case_spec["source"]] if "source" in case_spec else [])
                case_refs = refs + ([case_spec["authority_ref"]] if "authority_ref" in case_spec else [])
                prerequisite = self.prerequisite(ci, case_spec, affected_fields, case_sources, case_refs)
                pending = prerequisite and accepted_value(prerequisite) != "resolved"
                case_node = self.add(
                    f"case_spec:{ci}", "case_specification", f"{measure['measure_name']} · case specification",
                    case_spec, [affected_fields, selection, measure_node["decision"]["condition"], case_spec],
                    explanation=case_spec.get("description", "Authorize a scoped case specification or defer."),
                    refs=case_refs, sources=case_sources, condition=" AND ".join(dict.fromkeys(
                        p for p in (case_spec.get("condition"), condition) if p)) or None,
                    triggers=trigger_map(M=case_spec.get("target") is None or bool(missing_scope),
                                         Q=bool(pending),
                                         V=not bool(case_spec.get("authority_ref"))),
                    constraints=missing_scope,
                    blocks=["Definitive screening against the scoped case criterion"], spec_contract=case_contract)
            self.result["criteria"].append({
                "criterion_instance_id": ci, "mission_id": self.mission_id, "requirement_id": req["requirement_id"],
                "measure_id": measure["measure_id"], "name": measure["measure_name"],
                "definition": measure["measure_definition"], "native_unit": measure["unit"],
                "acceptance_direction": measure["acceptance_direction"], "catalog_acceptance_rule": measure["acceptance_rule"],
                "resolve_before": measure["resolve_before"], "condition": condition, "node_id": measure_node["id"],
                "scope": scope_details, "requirement_context_id": context["context_id"],
                "function_dimension_id": context["function_dimension_id"], "dimension_id": context["dimension_id"],
                "function_id": context["function_id"], "dimension_selection_id": d["dimension_selection_id"],
                "candidate_memberships": links, "memberships": active_links if selection in ("include", "conditional") else [],
                "selection": selection, "status": shown_status(measure_node),
                "baseline_spec_node_id": baseline_node["id"] if baseline_node else None,
                "case_spec_node_id": case_node["id"] if case_node else None,
                "case_prerequisite_node_id": prerequisite["id"] if prerequisite else None,
                "case_specification_preview": instance.get("case_specification"),
                "specification_dependencies": dependencies[req["requirement_id"]], "sources": sources,
                "population_and_counting": {r["field"]: r[measure["measure_id"]]
                                           for r in c.rows("WB-03", "cb1_specification_fields")}
                if measure["measure_id"] in {"MEAS-R-LD01-01", "MEAS-R-LD01-02"} else None,
            })

        self.add_obligations()
        self.add_constraints()

    def prerequisite(self, key, spec, basis, sources, refs):
        if spec.get("pending"):
            return self.add(
                f"prerequisite:{key}", "case_prerequisite", spec["pending"], "review", basis,
                explanation="Record the evidence that supplies the missing case definition or assessment basis.",
                sources=sources, refs=refs, triggers=trigger_map(M=True, Q=True),
                alternatives=["resolved"], blocks=["Quantitative use where this prerequisite is material"])
        return None

    def add_obligations(self):
        functions = {f["function_id"] for f in self.result["functions"] if f["role"] in IN_SCOPE}
        selected_requirements = {r["requirement_id"] for r in self.result["criteria"]
                                 if r["selection"] in {"include", "conditional"}}
        eligible = set(selected_requirements)
        for item in self.mission.get("case_obligations", []):
            if item["function_id"] in functions and item["dependency_id"] in eligible:
                key = item["obligation_id"]
                spec = item["specification"]
                if any(b not in self.catalog.index("WB-03", "baseline_capabilities") for b in item["baseline_ids"]):
                    raise WorkflowError(f"{key}: unknown obligation capability membership")
                prerequisite = self.prerequisite(key, spec, item, item["sources"], item["refs"])
                node = self.add(
                    f"obligation:{key}", "case_obligation", item["name"], spec, item,
                    explanation=item["definition"], refs=item["refs"], sources=item["sources"],
                    triggers=trigger_map(Q=bool(prerequisite and accepted_value(prerequisite) != "resolved"),
                                         V=not bool(spec.get("authority_ref"))),
                    blocks=["Quantitative use of this case obligation"])
                self.result["obligations"].append({**item, "node_id": node["id"],
                                                    "case_prerequisite_node_id": prerequisite["id"] if prerequisite else None,
                                                    "selection": shown_status(node)})
                if accepted_value(node):
                    eligible.add(key)

    def add_constraints(self):
        functions = {f["function_id"] for f in self.result["functions"] if f["role"] in IN_SCOPE}
        c = self.catalog
        links = index_by(c.rows("WB-03", "baseline_constraint_functions"), "constraint_id")
        for row in c.rows("WB-03", "baseline_constraints"):
            cid = row["constraint_id"]
            selected = [r["function_id"] for r in links[cid] if r["function_id"] in functions]
            if selected:
                early = row["resolve_stage"].startswith("03")
                self.result["constraints"].append({
                    **row, "function_ids": selected, "source": c.source("WB-03", "baseline_constraints", cid),
                    "assessment_status": "pending_predicate_and_evidence" if early else "later_instantiation",
                    "required_value": True, "observed_compliance": None,
                })

    def run(self):
        class_id = self.step1()
        if class_id:
            dimensions = self.step2(class_id)
            if dimensions:
                self.step3(dimensions)
        for key, prior in self.latest.items():
            if key not in self.nodes:
                append_block(self.open_items, key, "inactive_prior_decision",
                             f"{prior['label']} needs rechecking if it becomes applicable again.", [])
        self.result["approved_class"] = class_id
        self.result["supporting_roles"] = self.mission.get("supporting_roles", []) if class_id else []
        return self.result


def evaluate(mission, decisions, catalog):
    validate_mission(mission, catalog)
    return Evaluation(mission, decisions, catalog).run()


def numeric_domain(value, unit):
    return finite(value) and (0 <= value <= 1 if unit in {"fraction", "probability"} else value >= 0)


def validate_uncertainty(value):
    if value is None:
        return
    require(isinstance(value, dict), "Uncertainty must be a structured record")
    kind = value.get("kind")
    require(kind in {"epistemic_unknown", "bounded_interval", "distribution", "sensitivity_points"},
            "Choose an uncertainty representation")
    if kind == "epistemic_unknown":
        return
    require(text_value(value.get("unit")) and text_value(value.get("reference_conditions")),
            "Uncertainty requires units and reference conditions")
    require(text_value(value.get("dependence")), "Declare material dependence or explain why it is inapplicable")
    if kind == "bounded_interval":
        lo, hi = value.get("lower"), value.get("upper")
        require(finite(lo) and finite(hi) and lo <= hi, "Enter ordered finite uncertainty bounds")
    if kind == "sensitivity_points":
        points = value.get("points")
        require(isinstance(points, list) and bool(points) and all(finite(p) for p in points),
                "Enter finite sensitivity points")
    if kind == "distribution":
        parameters = value.get("parameters")
        require(isinstance(parameters, dict), "Supply distribution parameters")
        constraints = {
            "normal": (("mean", "sd"), lambda p: p["sd"] > 0),
            "lognormal": (("log_mean", "log_sd"), lambda p: p["log_sd"] > 0),
            "uniform": (("lower", "upper"), lambda p: p["lower"] < p["upper"]),
            "triangular": (("lower", "mode", "upper"),
                           lambda p: p["lower"] <= p["mode"] <= p["upper"] and p["lower"] < p["upper"]),
            "beta": (("alpha", "beta"), lambda p: p["alpha"] > 0 and p["beta"] > 0),
        }
        model = value.get("family")
        require(model in constraints, "Choose normal, lognormal, uniform, triangular, or beta")
        fields, predicate = constraints[model]
        require(set(parameters) == set(fields) and all(finite(v) for v in parameters.values()) and
                predicate(parameters), f"Invalid {model} parameters. Expected {', '.join(fields)}")


def validate_spec(value, expected, authority_ref):
    require(isinstance(value, dict), "Enter a structured specification")
    kind, unit, comparator, target = (value.get(k) for k in ("kind", "unit", "comparator", "target"))
    require(kind in {"threshold", "range", "boolean", "service_profile"}, "Choose a specification kind")
    require(text_value(unit) and text_value(value.get("reference_conditions")),
            "Supply actual units and reference conditions")
    require(text_value(authority_ref), "Record explicit authorization for this scoped specification")
    require(unit not in {"native variable unit", "native exposure unit", "declared effect unit",
                         "declared holding measure", "declared protective-effect unit", "declared effect unit/h",
                         "asset-service equivalents"}, "Choose a concrete measure unit")
    native = expected.get("unit")
    declared_units = {"native variable unit", "native exposure unit", "declared effect unit",
                      "declared holding measure", "declared protective-effect unit", "declared effect unit/h",
                      "asset-service equivalents"}
    compatible = unit == native or native in declared_units or (native, unit) in {
        ("min from task trigger", "min"), ("km of qualifying feature", "km"),
    }
    require(compatible, f"Unit {unit!r} is incompatible with governing unit {native!r}")
    expected_comp = expected.get("comparator")
    if kind == "boolean":
        require(unit == "boolean" and type(target) is bool and
                comparator in {"TRUE", "=="} and expected_comp in {"TRUE", "=="},
                "This specification requires a supported Boolean predicate")
        require(expected_comp != "TRUE" or target is True, "Workbook requires a true compliance target")
    elif kind == "threshold":
        require(comparator == expected_comp and comparator in {"<=", ">=", "=="},
                f"The measure comparator is {expected_comp!r}")
        require(numeric_domain(target, unit), "Enter a finite, nonnegative threshold in the allowed unit domain")
        if unit == "count":
            require(int(target) == target, "A count target must be an integer")
    elif kind == "range":
        require(expected_comp in {"<=", ">=", "between"} and comparator == "between" and
                value.get("bound_direction") == expected_comp and isinstance(target, dict) and
                numeric_domain(target.get("lower"), unit) and numeric_domain(target.get("upper"), unit) and
                target["lower"] <= target["upper"],
                "An acceptance range requires ordered bounds and the measure's governing direction")
    else:
        require(expected.get("kind") == kind and isinstance(target, dict) and bool(target),
                "A service profile requires a registered profile and structured values")
    points = value.get("sensitivity", [])
    for sweep in as_list(points, "Sensitivity"):
        require(isinstance(sweep, dict) and text_value(sweep.get("field")) and text_value(sweep.get("unit"))
                and isinstance(sweep.get("points"), list) and bool(sweep["points"])
                and all(numeric_domain(p, sweep["unit"]) for p in sweep["points"]),
                "Each sensitivity sweep needs a parameter, units and valid numeric test points")
    if (distribution := value.get("distribution")) is not None:
        require(isinstance(distribution, dict), "Supply a structured distribution")
        require(distribution.get("unit") == unit, "Distribution units must match the specification")
        validate_uncertainty({**distribution, "kind": "distribution"})


def judge(node, entry, *, now=None):
    """Section IV.D. Preserve the proposal, the requested action, and validation separately."""
    require(isinstance(entry, dict), "Specify a judgment")
    action = entry.get("action")
    require(action in {"retain", "revise", "reject", "defer"}, "Choose retain, revise, reject or defer")
    analyst = entry.get("analyst")
    rationale = entry.get("rationale", "")
    require(text_value(analyst), "Enter the analyst or reviewing authority")
    require(isinstance(rationale, str), "Rationale must be text")
    refs = require_text_list(entry.get("evidence_refs", []), "Evidence references")
    ratings = (entry.get("evidence_quality", 0), entry.get("confidence", 0))
    require(all(type(score) is int and 0 <= score <= 3 for score in ratings),
            "Evidence quality and confidence each use a whole number from 0 to 3")
    require(action == "retain" or text_value(rationale), f"Explain the rationale for {action}")
    value = node["proposal"] if action == "retain" else entry.get("value")
    condition = entry.get("condition") or node["condition"]
    authority = entry.get("authority_ref")
    uncertainty = entry.get("uncertainty")
    numeric = node["kind"] in SPEC_TYPES
    checks = []
    if action in ("retain", "revise"):
        try:
            validate_uncertainty(uncertainty)
            require(not node["constraints"], " ".join(node["constraints"]))
            require(value is not None, "Select a supported option or defer")
            if numeric:
                require(isinstance(value, dict), "Enter a structured specification")
                if action == "revise":
                    # These fields are governed by the measure or recorded authority.
                    allowed_fields = {"kind", "comparator", "unit", "target", "reference_conditions",
                                      "sensitivity", "distribution", "bound_direction"}
                    require(set(value) <= allowed_fields, "Revise only the editable specification fields")
                    supplied = value
                    value = {**node["proposal"], **supplied}
                    if node["proposal"].get("source") and node["proposal"].get("target") is not None:
                        require(value["unit"] == node["proposal"]["unit"],
                                "Keep the source-backed actual unit for this scoped specification")
                    if text_value(authority):
                        value["authority_ref"] = authority
                authority = authority or (value.get("authority_ref") if action == "retain" else None)
                validate_spec(value, node["spec_contract"] or node["proposal"], authority)
                require(node["kind"] != "baseline_specification" or action == "revise",
                        "A blank baseline must be explicitly resolved or deferred")
                value = {**value, "authority_ref": authority, "resolution_status": "specified"}
            else:
                require(value in node["alternatives"], "Select a compatible disposition or defer")
            if action == "revise" or (node["review_required"] and not numeric) or (
                entry.get("condition") and entry["condition"] != node["condition"]
            ):
                require(text_value(rationale) and bool(refs), "Record rationale and supporting evidence")
            if node["triggers"]["V"] is not False:
                require(text_value(authority), "Provide the mandatory reviewing authority and its reference")
            conditional = value == "conditional" if not numeric else bool(condition)
            if entry.get("conditional") or conditional:
                require(text_value(condition) and bool(refs or node["refs"]),
                        "Conditional acceptance requires an explicit supported condition, bound or branch")
                disposition = "conditionally_accepted"
            else:
                disposition = "accepted"
            checks.append({"status": "passed", "message": "Checked applicability, evidence and governing constraints"})
        except WorkflowError as exc:
            checks.append({"status": "failed", "message": str(exc)})
            disposition = "unresolved" if action == "retain" else "rejected"
    else:
        disposition = "unresolved" if action == "defer" else "rejected"
        checks.append({"status": "recorded", "message": f"Analyst chose {action}"})
    if ratings[0] <= 1 or ratings[1] <= 1:
        checks.append({"status": "review_note",
                       "message": "Low or unassessed ratings may warrant further review or sensitivity analysis."})
    proposal_snapshot = {key: node[key] for key in (
        "proposal", "why", "refs", "sources", "triggers", "alternatives", "condition", "blocks", "constraints")}
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="microseconds")
    record = {"target_id": node["id"], "basis": node["basis"], "kind": node["kind"], "label": node["label"],
              "timestamp": stamp, "analyst": analyst, "action": action, "value": value, "rationale": rationale,
              "evidence_refs": refs or (node["refs"] if action == "retain" else []),
              "evidence_quality": ratings[0], "confidence": ratings[1], "uncertainty": uncertainty,
              "condition": condition, "authority_ref": authority, "validation": checks,
              "disposition": disposition, "system_proposal": proposal_snapshot}
    return {"decision_id": generated_id("DEC", record), **record}
