"""Read and validate the registered Phase 1 contracts without writing Excel files."""

from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries


THESIS_RELATIVE = PurePosixPath("DOCS_&_INFORMATION/Thesis_Methodology_Development_New/01_Phase_1")
SUPPORTED = {
    "P1-REL-0007": "1fe31223ebb1936d177c118dbc208219f68809be5ff5a80d9ddfd7381cef76de",
}
TABLES = {
    "WB-00": ("registry_release_manifest", "registry_python_tables", "ef_release_decisions"),
    "WB-01": ("mission_classes", "mission_input_fields", "mission_class_rules",
              "mission_rule_terms", "mission_selection_guidance", "mission_instances",
              "mission_class_decisions", "mission_class_handoff"),
    "WB-02": ("operational_functions", "capability_dimensions", "function_dimensions",
              "mission_function_map", "function_selection_guidance", "mission_selected_functions",
              "mission_selected_dimensions", "function_dimension_handoff", "ef_supporting_roles"),
    "WB-03": ("baseline_capabilities", "bl_dimension_links", "requirement_templates", "criterion_measures",
              "baseline_specification_drafts", "bl_criterion_links", "requirement_function_contexts",
              "requirement_dependencies", "baseline_constraints", "baseline_constraint_functions",
              "baseline_criterion_instances", "baseline_instances", "baseline_conditioning_handoff",
              "ef_scope_review", "ef_case_obligations", "ef_obligation_memberships",
              "cb1_specification_fields"),
    "WB-04": ("scenario_instances", "selected_impact_records", "criterion_conditioning_rules",
              "ef_obligation_handoff_04"),
    "WB-05": ("function_links", "active_function_links", "interface_requirement_instances"),
    "WB-06": ("capability_deltas", "delta_baseline_references", "delta_constraint_handoff",
              "ef_obligation_handoff_06"),
    "WB-07": ("mccrv_criteria", "mccrv_baseline_links", "mccrv_constraints", "ef_obligation_handoff_07"),
}


class CatalogError(ValueError):
    pass


def digest(data):
    return sha256(data).hexdigest()


def stable_hash(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8"))


def relative_to_root(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or any(":" in part or "\\" in part for part in path.parts):
        raise CatalogError(f"Expected a portable relative path, got {relative!r}")
    resolved = root.joinpath(*path.parts).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise CatalogError(f"Path escapes the configured project root: {relative}")
    return resolved


def read_bytes(path):
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CatalogError(f"Cannot read {path}: {exc}") from exc


def workbook_value(value):
    return value.isoformat() if isinstance(value, (date, datetime, time)) else value


@dataclass
class Table:
    sheet: str
    headers: tuple
    rows: list
    keys: tuple = ()


def read_tables(data, filename, expected):
    # Table refs are available in the regular openpyxl reader. The workbook is opened
    # from an immutable byte snapshot and is never saved or recalculated.
    try:
        book = load_workbook(BytesIO(data), data_only=True, keep_links=False)
    except Exception as exc:
        raise CatalogError(f"Cannot parse workbook {filename}: {exc}") from exc
    result = {}
    try:
        for sheet in book:
            for table in sheet.tables.values():
                if table.name not in expected:
                    continue
                a, b, c, d = range_boundaries(table.ref)
                cells = sheet.iter_rows(min_col=a, min_row=b, max_col=c, max_row=d, values_only=True)
                headers = tuple(next(cells))
                if any(not isinstance(name, str) or not name for name in headers) or len(set(headers)) != len(headers):
                    raise CatalogError(f"{filename} / {table.name}: missing or duplicate header")
                rows = [dict(zip(headers, map(workbook_value, row))) for row in cells
                        if any(value is not None for value in row)]
                result[table.name] = Table(sheet.title, headers, rows)
    finally:
        book.close()
    missing = set(expected) - result.keys()
    if missing:
        raise CatalogError(f"{filename}: missing named table(s): {', '.join(sorted(missing))}")
    return result


class Catalog:
    def __init__(self, release, tables, diagnostics=()):
        self.release = release
        self.tables = tables
        self.diagnostics = list(diagnostics)
        self.indexes = {}
        self.validate_contract()

    def rows(self, workbook, table):
        return self.tables[workbook][table].rows

    def index(self, workbook, table, field=None):
        info = self.tables[workbook][table]
        fields = (field,) if field else info.keys
        cache_key = (workbook, table, fields)
        if cache_key not in self.indexes:
            indexed = {}
            for row in info.rows:
                values = tuple(row[k] for k in fields)
                key = values[0] if len(values) == 1 else values
                if any(v is None or v == "" for v in values) or key in indexed:
                    raise CatalogError(f"{workbook}.{table}: missing or duplicate key {fields}: {key!r}")
                indexed[key] = row
            self.indexes[cache_key] = indexed
        return self.indexes[cache_key]

    def source(self, workbook, table, key):
        pin = self.release["workbooks"][workbook]
        return {"workbook": workbook, "version": pin["version"], "filename": pin["filename"],
                "table": table, "key": key}

    def validate_contract(self):
        registry = self.rows("WB-00", "registry_python_tables")
        contracts = {(r["owner_workbook_id"], r["table_name"]): r for r in registry}
        if len(contracts) != len(registry):
            raise CatalogError("WB-00.registry_python_tables: duplicate owner/table contract")
        for owner, tables in self.tables.items():
            for name, table in tables.items():
                contract = contracts.get((owner, name))
                if not contract:
                    raise CatalogError(f"WB-00: no contract for {owner}.{name}")
                expected = tuple(contract["required_headers"].split("|"))
                if expected != table.headers:
                    raise CatalogError(f"{owner}.{name}: expected headers {expected}, found {table.headers}")
                keys = tuple(v.strip() for v in (contract["primary_key"] or "").split("+") if v.strip())
                # These two registry tables describe their own compound keys as prose.
                keys = {
                    ("WB-00", "registry_release_manifest"): ("release_id", "workbook_id"),
                    ("WB-00", "registry_python_tables"): ("owner_workbook_id", "table_name"),
                }.get((owner, name), keys)
                if keys and set(keys).issubset(table.headers):
                    table.keys = keys
                    self.index(owner, name)
                elif owner in ("WB-01", "WB-02", "WB-03"):
                    raise CatalogError(f"{owner}.{name}: invalid primary-key contract {keys}")
        self.validate_relationships()

    def foreign_key(self, child, source_field, parent, target_field=None, *, optional=False):
        entries = self.index(*parent, target_field)
        for row in self.rows(*child):
            key = row[source_field]
            if key is None and optional:
                continue
            if key not in entries:
                owner, table = child
                fields = self.tables[owner][table].keys
                row_key = "/".join(str(row[f]) for f in fields)
                raise CatalogError(f"{owner}.{table}[{row_key}].{source_field}={key!r} "
                                   f"does not resolve in {'.'.join(parent)}")

    def validate_relationships(self):
        relations = (
            ("01", "mission_rule_terms", "rule_id", "01", "mission_class_rules"),
            ("01", "mission_class_rules", "input_field_id", "01", "mission_input_fields"),
            ("01", "mission_class_rules", "mission_class_id", "01", "mission_classes"),
            ("01", "mission_class_handoff", "class_decision_id", "01", "mission_class_decisions"),
            ("02", "mission_function_map", "mission_class_id", "01", "mission_classes"),
            ("02", "mission_function_map", "function_id", "02", "operational_functions"),
            ("02", "function_dimensions", "function_id", "02", "operational_functions"),
            ("02", "function_dimensions", "dimension_id", "02", "capability_dimensions"),
            ("02", "mission_selected_functions", "mapping_id", "02", "mission_function_map"),
            ("02", "mission_selected_functions", "class_decision_id", "01", "mission_class_decisions"),
            ("02", "mission_selected_dimensions", "selection_id", "02", "mission_selected_functions"),
            ("02", "function_dimension_handoff", "dimension_selection_id", "02", "mission_selected_dimensions"),
            ("03", "bl_dimension_links", "baseline_id", "03", "baseline_capabilities"),
            ("03", "bl_dimension_links", "dimension_id", "02", "capability_dimensions"),
            ("03", "requirement_templates", "dimension_id", "02", "capability_dimensions"),
            ("03", "criterion_measures", "requirement_id", "03", "requirement_templates"),
            ("03", "requirement_function_contexts", "requirement_id", "03", "requirement_templates"),
            ("03", "requirement_function_contexts", "function_dimension_id", "02", "function_dimensions"),
            ("03", "bl_criterion_links", "dimension_link_id", "03", "bl_dimension_links"),
            ("03", "bl_criterion_links", "baseline_id", "03", "baseline_capabilities"),
            ("03", "bl_criterion_links", "requirement_id", "03", "requirement_templates"),
            ("03", "baseline_constraint_functions", "function_id", "02", "operational_functions"),
            ("03", "baseline_constraint_functions", "constraint_id", "03", "baseline_constraints"),
            ("03", "baseline_criterion_instances", "dimension_selection_id", "02", "mission_selected_dimensions"),
            ("03", "baseline_instances", "criterion_instance_id", "03", "baseline_criterion_instances"),
            ("03", "baseline_conditioning_handoff", "baseline_instance_id", "03", "baseline_instances"),
            ("03", "ef_scope_review", "context_id", "03", "requirement_function_contexts"),
            ("03", "ef_obligation_memberships", "obligation_id", "03", "ef_case_obligations"),
            ("04", "scenario_instances", "mission_id", "01", "mission_instances"),
            ("04", "criterion_conditioning_rules", "criterion_instance_id", "03", "baseline_criterion_instances"),
            ("05", "active_function_links", "function_link_id", "05", "function_links"),
            ("05", "active_function_links", "source_function_selection_id", "02", "mission_selected_functions"),
            ("05", "active_function_links", "target_function_selection_id", "02", "mission_selected_functions"),
            ("05", "interface_requirement_instances", "active_link_id", "05", "active_function_links"),
            ("06", "capability_deltas", "criterion_instance_id", "03", "baseline_criterion_instances"),
            ("06", "delta_baseline_references", "criterion_link_id", "03", "bl_criterion_links"),
            ("07", "mccrv_criteria", "delta_id", "06", "capability_deltas"),
            ("07", "mccrv_criteria", "requirement_context_id", "03", "requirement_function_contexts"),
            ("07", "mccrv_constraints", "constraint_handoff_id", "06", "delta_constraint_handoff"),
        )
        primary = {
            ("02", "mission_selected_functions"): "selection_id",
            ("02", "mission_selected_dimensions"): "dimension_selection_id",
            ("03", "baseline_constraints"): "constraint_id",
            ("03", "baseline_criterion_instances"): "criterion_instance_id",
            ("05", "active_function_links"): "active_link_id",
            ("06", "capability_deltas"): "delta_id",
            ("06", "delta_constraint_handoff"): "constraint_handoff_id",
        }
        for wb, table, field, owner, target in relations:
            self.foreign_key(("WB-" + wb, table), field, ("WB-" + owner, target),
                             primary.get((owner, target)), optional=field in {
                                 "mapping_id", "criterion_instance_id", "active_link_id", "constraint_handoff_id",
                             })
        for number, upstream, target, field in (
            ("04", "03", "ef_case_obligations", "obligation_id"),
            ("06", "04", "ef_obligation_handoff_04", "handoff_id"),
            ("07", "06", "ef_obligation_handoff_06", "handoff_id"),
        ):
            self.foreign_key(("WB-" + number, f"ef_obligation_handoff_{number}"), "upstream_record_id",
                             ("WB-" + upstream, target), field)
        dimensions = self.index("WB-02", "function_dimensions")
        requirements = self.index("WB-03", "requirement_templates")
        dimension_links = self.index("WB-03", "bl_dimension_links")
        rules = self.index("WB-01", "mission_class_rules")
        measures = self.index("WB-03", "criterion_measures", "requirement_id")
        if set(measures) != set(requirements):
            raise CatalogError("WB-03: expected exactly one measure per requirement template in this release")
        for row in self.rows("WB-03", "requirement_function_contexts"):
            dim = dimensions[row["function_dimension_id"]]
            if (row["function_id"], row["dimension_id"]) != (dim["function_id"], dim["dimension_id"]):
                raise CatalogError(f"WB-03.requirement_function_contexts[{row['context_id']}]: incompatible function or dimension")
            if row["dimension_id"] != requirements[row["requirement_id"]]["dimension_id"]:
                raise CatalogError(f"WB-03.requirement_function_contexts[{row['context_id']}]: incompatible requirement dimension")
        for row in self.rows("WB-03", "bl_criterion_links"):
            link = dimension_links[row["dimension_link_id"]]
            if (row["baseline_id"], requirements[row["requirement_id"]]["dimension_id"]) != (
                link["baseline_id"], link["dimension_id"]
            ):
                raise CatalogError(f"WB-03.bl_criterion_links[{row['criterion_link_id']}]: incompatible capability/dimension join")
        for row in self.rows("WB-01", "mission_rule_terms"):
            if row["input_field_id"] != rules[row["rule_id"]]["input_field_id"]:
                raise CatalogError(f"WB-01.mission_rule_terms[{row['rule_id']}]: term field disagrees with rule")
            if row["matching_convention"] != "casefold_literal_phrase_with_word_boundaries":
                raise CatalogError(f"WB-01.mission_rule_terms[{row['rule_id']}]: unsupported matching convention")


def load_catalog(thesis_root, release_id):
    if release_id not in SUPPORTED:
        raise CatalogError(f"Incompatible release {release_id!r}. Implemented release: {', '.join(SUPPORTED)}")
    workbook_root = relative_to_root(thesis_root, str(THESIS_RELATIVE / "Workbooks"))
    review = workbook_root / "Release_Reviews" / release_id
    manifest_data = read_bytes(review / "release_hashes.json")
    if digest(manifest_data) != SUPPORTED[release_id]:
        raise CatalogError(f"{release_id}: release_hashes.json differs from the verified release manifest")
    manifest = json.loads(manifest_data)
    pins = {}
    tables = {}
    diagnostics = []
    for code, info in manifest.items():
        owner = f"WB-{code}"
        path = relative_to_root(workbook_root, info["relative_path"])
        try:
            data = read_bytes(path)
            actual = digest(data)
        except CatalogError:
            if owner != "WB-04A":
                raise
            actual = "unavailable"
        locator = {"kind": "workbook", "path": str(THESIS_RELATIVE / "Workbooks" / info["relative_path"])}
        if actual != info["sha256"] and owner == "WB-04A":
            archive = review / f"{release_id}_Workbooks_and_Review.zip"
            member = f"Workbooks/{info['relative_path']}"
            try:
                with ZipFile(archive) as bundle:
                    data = bundle.read(member)
            except (OSError, BadZipFile, ValueError, KeyError) as exc:
                raise CatalogError(f"{owner}: use the registered archive member {member}: {exc}") from exc
            diagnostics.append(f"{owner} active copy has SHA-256 {actual}. Using the registered archive member.")
            locator = {"kind": "archive_member", "path": archive.relative_to(thesis_root).as_posix(),
                       "member": member}
            actual = digest(data)
        if actual != info["sha256"] or len(data) != info["size_bytes"]:
            raise CatalogError(f"{owner} {info['filename']}: expected SHA-256 {info['sha256']}, found {actual}")
        pins[owner] = {"filename": info["filename"], "sha256": actual, "size_bytes": len(data),
                       "version": Path(info["filename"]).stem.rsplit("_", 1)[-1], "locator": locator}
        if owner in TABLES:
            tables[owner] = read_tables(data, info["filename"], TABLES[owner])
    registered = {r["workbook_id"]: r for r in tables["WB-00"]["registry_release_manifest"].rows
                  if r["release_id"] == release_id}
    if registered.keys() != pins.keys():
        raise CatalogError(f"{release_id}: Workbook 00 registry and physical release enumerate different workbooks")
    for owner, pin in pins.items():
        row = registered[owner]
        if (row["filename"], row["file_version"]) != (pin["filename"], pin["version"]):
            raise CatalogError(f"{owner}: Workbook 00 and the release manifest disagree about the file version")
        pin["schema_version"] = row["schema_version"]
        pin["release_status"] = row["release_status"]
    return Catalog({"id": release_id, "manifest_sha256": digest(manifest_data), "workbooks": pins},
                   tables, diagnostics)
