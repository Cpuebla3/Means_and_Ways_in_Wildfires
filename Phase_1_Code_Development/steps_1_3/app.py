"""Loopback web entry points for the Phase 1 Steps 1–3 workflow."""

import re
from threading import RLock
from uuid import uuid4

from flask import Flask, Response, jsonify, render_template, request

from .case_io import (atomic_json, check_case_sources, ensure_name, from_json, load_case,
                      release_fingerprint, save_case, step3_package, to_json)
from .catalog import CatalogError
from .workflow import ACCEPTED, TRIGGER_LABELS, WorkflowError, evaluate, judge, require


def create_app(catalog, code_root, thesis_root, case_dir):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=5_000_000, TRUSTED_HOSTS=["localhost", "127.0.0.1", "::1"])
    examples = code_root / "Phase_1_Code_Development" / "steps_1_3" / "examples"
    drafts = {}
    lock = RLock()

    def draft_view(draft):
        return {key: draft[key] for key in (
            "id", "revision", "mission", "evaluation", "decisions", "name", "read_only", "diagnostics", "release")}

    def json_body():
        data = request.get_json(silent=True)
        require(isinstance(data, dict), "Provide a JSON object")
        try:
            to_json(data)
        except ValueError as exc:
            raise WorkflowError("JSON numbers must be finite") from exc
        return data

    def new_draft(mission, decisions=(), *, snapshot=None, name=None, fingerprint=None, release=None,
                  diagnostics=()):
        view = {
            "id": str(uuid4()), "revision": 0, "mission": mission, "decisions": list(decisions),
            "name": name, "file_digest": fingerprint, "read_only": snapshot is not None,
            "diagnostics": [*catalog.diagnostics, *diagnostics], "release": release or catalog.release,
            "evaluation": snapshot if snapshot is not None else evaluate(mission, decisions, catalog),
        }
        drafts[view["id"]] = view
        return view

    def editing(draft_id, payload=None):
        draft = drafts.get(draft_id)
        require(draft is not None, "Reopen this case or regenerate the mission")
        require(not draft["read_only"], "Reopen with the recorded source release and case fingerprint to edit or export")
        if payload is not None:
            require(payload.get("revision") == draft["revision"],
                    "The draft changed. Reload its current revision before editing.")
        return draft

    def apply_entries(draft, entries):
        history = list(draft["decisions"])
        result = draft["evaluation"]
        recorded = []
        for target, entry in entries:
            node = result["nodes"].get(target)
            require(node is not None and entry.get("basis") == node["basis"],
                    f"{target}: the decision is out of date or outside the current scope")
            record = judge(node, entry)
            history.append(record)
            recorded.append(record)
        draft.update(decisions=history, evaluation=evaluate(draft["mission"], history, catalog),
                     revision=draft["revision"] + 1)
        return {**draft_view(draft), "recorded": recorded}

    @app.errorhandler(WorkflowError)
    @app.errorhandler(CatalogError)
    def input_error(exc):
        return jsonify(error=str(exc)), 400

    @app.before_request
    def local_request():
        if request.method in {"POST", "PATCH"} and request.headers.get("Origin") not in {
            None, request.host_url.rstrip("/"),
        }:
            return jsonify(error="Use the local workbench origin"), 403

    @app.get("/")
    def home():
        return render_template("index.html", release=catalog.release["id"])

    @app.get("/api/config")
    def config():
        return jsonify(release=catalog.release, diagnostics=catalog.diagnostics, triggers=TRIGGER_LABELS,
                       functions=catalog.rows("WB-02", "operational_functions"),
                       fields=catalog.rows("WB-01", "mission_input_fields"))

    @app.get("/api/examples/<name>")
    def example(name):
        files = {"template": "mission_template.json", "esperanza": "esperanza_mission.json"}
        require(name in files, "Select a provided mission template")
        return jsonify(from_json((examples / files[name]).read_text(encoding="utf-8")))

    @app.post("/api/drafts")
    def create_draft():
        mission = json_body().get("mission")
        require(isinstance(mission, dict), "Enter a mission")
        with lock:
            check_case_sources(mission, thesis_root)
            return jsonify(draft_view(new_draft(mission)))

    @app.patch("/api/drafts/<draft_id>/mission")
    def update_mission(draft_id):
        payload = json_body()
        mission = payload.get("mission")
        require(isinstance(mission, dict), "Enter a mission")
        with lock:
            draft = editing(draft_id, payload)
            require(mission.get("mission_id") == draft["mission"]["mission_id"],
                    "Use a new draft to change the mission ID")
            check_case_sources(mission, thesis_root)
            result = evaluate(mission, draft["decisions"], catalog)
            draft.update(mission=mission, evaluation=result, revision=draft["revision"] + 1)
            return jsonify(draft_view(draft))

    @app.post("/api/drafts/<draft_id>/judgments")
    def judgments(draft_id):
        payload = json_body()
        target = payload.get("target_id")
        require(isinstance(target, str), "Choose a decision")
        with lock:
            return jsonify(apply_entries(editing(draft_id, payload), [(target, payload)]))

    @app.post("/api/drafts/<draft_id>/batch")
    def batch(draft_id):
        payload = json_body()
        allowed = {"function", "dimension", "capability", "measure", "case_specification", "case_obligation"}
        kind = payload.get("kind")
        require(kind in allowed, "Choose a batch review type")
        with lock:
            draft = editing(draft_id, payload)
            entries = []
            for key, node in draft["evaluation"]["nodes"].items():
                if (node["kind"] != kind or node["decision"] or node["stale_decision"]
                        or node["review_required"] or node["proposal"] in ("review", "defer", None)):
                    continue
                entry = {**payload, "basis": node["basis"], "action": "retain"}
                if judge(node, entry)["disposition"] in ACCEPTED:
                    entries.append((key, entry))
            require(bool(entries), "No routine recommendations are ready for this batch. Review flagged records individually.")
            return jsonify(apply_entries(draft, entries))

    @app.get("/api/cases")
    def case_list():
        result = [p.name[:-10] for p in sorted(case_dir.glob("*-case.json"))
                  if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}-case\.json", p.name)]
        return jsonify(cases=result)

    @app.post("/api/cases/<name>/open")
    def reopen(name):
        with lock:
            record, fingerprint = load_case(case_dir, name)
            diagnostics = []
            try:
                mismatch = release_fingerprint(record["release"]) != release_fingerprint(catalog.release)
            except (TypeError, KeyError) as exc:
                raise WorkflowError("Saved case release metadata is incomplete") from exc
            if mismatch:
                diagnostics.append(f"Release mismatch: case {record['release']['id']}, loaded {catalog.release['id']}. "
                                   "The saved snapshot is open for inspection.")
            try:
                check_case_sources(record["mission"], thesis_root)
            except CatalogError as exc:
                diagnostics.append(f"Case source mismatch: {exc}. The saved snapshot is open for inspection.")
            snapshot = record["evaluation"] if diagnostics else None
            view = new_draft(record["mission"], record["decisions"], snapshot=snapshot,
                             name=name, fingerprint=fingerprint, release=record["release"],
                             diagnostics=diagnostics)
            return jsonify(draft_view(view))

    @app.post("/api/drafts/<draft_id>/save")
    def save(draft_id):
        payload = json_body()
        name = payload.get("name")
        ensure_name(name)
        with lock:
            draft = editing(draft_id, payload)
            fingerprint = save_case(case_dir, name, draft,
                                    draft["file_digest"] if name == draft["name"] else None, catalog)
            draft.update(name=name, file_digest=fingerprint, revision=draft["revision"] + 1)
            return jsonify(draft_view(draft))

    @app.post("/api/drafts/<draft_id>/export")
    def export(draft_id):
        payload = json_body()
        with lock:
            draft = editing(draft_id, payload)
            name = payload.get("name")
            ensure_name(name)
            package = step3_package(draft, catalog)
            if payload.get("write"):
                path = case_dir / f"{name}-step3.json"
                require(not path.exists() or (draft["name"] == name and payload.get("replace") is True),
                        "The export already exists. Choose a new name or confirm replacement of this case's export.")
                atomic_json(path, package)
            return Response(to_json(package), mimetype="application/json",
                            headers={"Content-Disposition": f'attachment; filename="{name}-step3.json"'})

    return app
