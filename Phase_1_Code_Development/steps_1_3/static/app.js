"use strict";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[c]);
const pretty = value => JSON.stringify(value, null, 2);
const lines = text => text.split("\n").map(x => x.trim()).filter(Boolean);
const label = key => String(key || "").replaceAll("_", " ");
const list = data => data.map(x => `<li>${esc(x)}</li>`).join("");
const pre = data => `<pre>${esc(pretty(data))}</pre>`;
const opts = (items, current) => items.map(([id, name]) =>
  `<option value="${esc(id)}" ${current === id ? "selected" : ""}>${esc(name)}</option>`).join("");
const roles = ["active", "supporting", "conditional", "outside_scope", "unknown"];
const statuses = ["known", "missing", "unknown", "not_applicable"];
const specKinds = ["baseline_specification", "case_specification", "case_obligation"];
let config;
let draft = null;
let mission = null;
let currentNode = null;

function message(id, text, error = false) {
  const element = $(id);
  element.hidden = !text;
  element.textContent = text;
  element.classList.toggle("error", error);
}

async function request(url, method = "GET", body) {
  const response = await fetch(url, {
    method,
    headers: body ? {"Content-Type": "application/json"} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return response;
}

const api = async (...args) => (await request(...args)).json();
const draftUrl = () => `/api/drafts/${draft.id}`;
const entry = () => ({revision: draft.revision, analyst: $("analyst").value.trim()});
const checked = id => $(id).checked;

function tab(name) {
  for (const section of document.querySelectorAll(".page")) section.hidden = section.id !== name;
  for (const button of document.querySelectorAll("[data-tab]")) {
    if (button.dataset.tab === name) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  }
}

function safe(action, errorId = "message") {
  return async event => {
    message(errorId, "");
    try { await action(event); }
    catch (error) { message(errorId, error.message, true); }
  };
}

function badge(value) {
  const pending = !["active", "accepted", "conditionally_accepted", "include", "supporting"].includes(value);
  return `<span class="badge ${pending ? "pending" : ""}">${esc(label(value))}</span>`;
}

function sourceDetails(items = []) {
  return `<ul>${items.map(s => `<li>${esc(s.workbook)} ${esc(s.version)} · ${esc(s.table)} · <code>${esc(Array.isArray(s.key) ? s.key.join(" / ") : s.key)}</code></li>`).join("")}</ul>`;
}

function factEditor(key, title, item, kind, help = "") {
  const value = item?.value;
  const plain = Array.isArray(value) ? value.join("\n") : value ?? "";
  const main = ({
    text: () => `<textarea data-value rows="2">${esc(plain)}</textarea>`,
    select: () => `<select data-value>${opts([["", "Select class"], ...["IA", "EA", "LFO", "WSP", "FRM"].map(x => [x, x])], plain)}</select>`,
    window: () => `<div class="grid">
      <label>Start with UTC offset <input data-part="start" placeholder="2006-10-26T06:00:00-07:00" value="${esc(value?.start)}"></label>
      <label>End with UTC offset <input data-part="end" value="${esc(value?.end)}"></label>
      <label>Time zone <input data-part="zone" placeholder="America/Los_Angeles" value="${esc(value?.zone)}"></label></div>`,
    area: () => `<label>Area description <input data-part="description" value="${esc(value?.description)}"></label>
      <label>Provisional area in km² <input type="number" step="any" min="0" data-part="provisional_km2" value="${esc(value?.provisional_km2)}"></label>`,
    fire: () => `<label>Fire state at the start <textarea data-part="description" rows="2">${esc(value?.description)}</textarea></label>
      <label>Is the main fire known?
        <select data-part="main_fire_known">${opts([["", "Unspecified"], ["true", "Yes"], ["false", "No"]], value?.main_fire_known == null ? "" : String(value.main_fire_known))}</select>
      </label>`,
    assets: () => `<label>Assets or values at risk (JSON list)
      <textarea data-value class="code" rows="5" placeholder='[{"asset_id":"A1","name":"Example asset"}]'>${esc(pretty(value ?? []))}</textarea></label>`,
  }[kind])();
  return `<fieldset data-fact="${esc(key)}" data-kind="${kind}">
    <legend>${esc(title)}</legend><label>Status <select data-status>${opts(statuses.map(x => [x, label(x)]), item?.status || "missing")}</select></label>
    ${help ? `<small>${esc(help)}</small>` : ""}
    <div data-known ${item?.status === "known" ? "" : "hidden"}>${main}</div>
    <label data-reason-control ${item?.status === "not_applicable" ? "" : "hidden"}>Reason <input data-reason value="${esc(item?.reason)}"></label>
    <details><summary>Source references</summary><label>One per line <textarea data-refs rows="2">${esc((item?.refs || []).join("\n"))}</textarea></label></details>
  </fieldset>`;
}

function taskEditor(task) {
  const functions = config.functions.map(f => [f.function_id, f.name]);
  return `<fieldset class="task" data-task="${esc(task.task_id)}">
    <legend>${esc(task.task_id)}</legend>
    <div class="grid">
      <label>Operational function <select data-task-field="function_id">${opts(functions, task.function_id)}</select></label>
      <label>Task disposition <select data-task-field="status">${opts(roles.map(x => [x, label(x)]), task.status)}</select></label>
      <label class="wide">Task description <textarea data-task-field="description" rows="2">${esc(task.description)}</textarea></label>
      <label>Activation condition <input data-task-field="condition" value="${esc(task.condition)}"></label>
      <label>Asset IDs (one per line) <textarea data-task-list="asset_ids" rows="2">${esc((task.asset_ids || []).join("\n"))}</textarea></label>
      <label>Dimension context IDs (one per line) <textarea data-task-list="dimension_ids" rows="2">${esc((task.dimension_ids || []).join("\n"))}</textarea></label>
      <label>Source references (one per line) <textarea data-task-list="refs" rows="2">${esc((task.refs || []).join("\n"))}</textarea></label>
    </div>
    <button type="button" data-remove-task>Remove task</button>
  </fieldset>`;
}

function showMission() {
  if (!mission) return;
  const fields = mission.fields || {};
  const core = ["MI-02", "MI-03", "MI-04", "MI-05", "MI-07", "MI-08", "MI-09"];
  const render = f => factEditor(f.field_id, f.label, fields[f.field_id], f.field_id === "MI-03" ? "select" : "text", f.notes);
  $("mission-form").innerHTML = `
    <div class="panel"><label>Mission ID <input id="mission-id" value="${esc(mission.mission_id)}" ${draft ? "readonly" : ""}></label></div>
    <div class="grid">${config.fields.filter(f => core.includes(f.field_id)).map(render).join("")}
      ${factEditor("area", "Area of interest", mission.area, "area")}
      ${factEditor("window", "Mission time window", mission.window, "window")}
      ${factEditor("fire_at_start", "Known fire state", mission.fire_at_start, "fire")}
      ${factEditor("assets", "Assets and values at risk", mission.assets, "assets")}
    </div>
    <details class="item"><summary>Operating period and other workbook context</summary>
      <div class="grid">${config.fields.filter(f => !core.includes(f.field_id) && f.field_id !== "MI-01").map(render).join("")}</div>
    </details>
    <div class="section-head"><h3>Operational tasks</h3><button type="button" id="add-task">Add task</button></div>
    <div id="task-list" class="grid">${(mission.tasks || []).map(taskEditor).join("")}</div>
    <div class="panel grid">
      <label>Mission notes <textarea id="notes" rows="3">${esc(mission.notes)}</textarea></label>
      <label>Mission source references <textarea id="source-refs" rows="3">${esc((mission.source_refs || []).join("\n"))}</textarea></label>
    </div>`;
  $("add-task").onclick = () => {
    const ids = new Set([...document.querySelectorAll("[data-task]")].map(x => x.dataset.task));
    let n = 1;
    while (ids.has(`T-${n}`)) n++;
    $("task-list").insertAdjacentHTML("beforeend", taskEditor({
      task_id: `T-${n}`, function_id: config.functions[0].function_id, status: "active"
    }));
  };
}

function readMission() {
  const next = structuredClone(mission);
  next.mission_id = $("mission-id").value.trim();
  next.notes = $("notes").value;
  next.source_refs = lines($("source-refs").value);
  for (const box of document.querySelectorAll("[data-fact]")) {
    const key = box.dataset.fact;
    const previous = key.startsWith("MI-") ? next.fields[key] : next[key];
    const current = {status: box.querySelector("[data-status]").value, value: null,
      refs: lines(box.querySelector("[data-refs]").value)};
    if (current.status === "known") {
      const value = box.querySelector("[data-value]");
      if (key === "MI-07") current.value = lines(value.value);
      else if (key === "assets") current.value = JSON.parse(value.value);
      else if (value) current.value = value.value.trim();
      else {
        current.value = {...(previous?.value || {})};
        for (const input of box.querySelectorAll("[data-part]")) {
          const name = input.dataset.part;
          if (!input.value) delete current.value[name];
          else current.value[name] = (input.type === "number" ? Number(input.value) :
            name === "main_fire_known" ? input.value === "true" : input.value.trim());
        }
      }
    }
    if (current.status === "not_applicable") current.reason = box.querySelector("[data-reason]").value.trim();
    if (key.startsWith("MI-")) next.fields[key] = current;
    else next[key] = current;
  }
  const priorTasks = new Map((mission.tasks || []).map(task => [task.task_id, task]));
  next.tasks = [...document.querySelectorAll("[data-task]")].map(box => {
    const task = {...priorTasks.get(box.dataset.task), task_id: box.dataset.task};
    for (const el of box.querySelectorAll("[data-task-field]")) {
      if (el.dataset.taskField === "condition" && !el.value.trim()) delete task.condition;
      else task[el.dataset.taskField] = el.value.trim();
    }
    for (const el of box.querySelectorAll("[data-task-list]")) task[el.dataset.taskList] = lines(el.value);
    return task;
  });
  return next;
}

function statusOf(node) {
  if (!node) return "pending";
  if (node.stale_decision) return "review again";
  return node.decision?.disposition || (node.review_required ? "review required" : "proposed");
}

function reviewButton(node, title = "Review") {
  return node ? `<button type="button" data-review="${esc(node.id)}" ${draft?.read_only ? "disabled" : ""}>${esc(title)}</button>` : "";
}

function renderClass() {
  const e = draft?.evaluation;
  if (!e) { $("class-result").textContent = "Generate proposals from a mission input."; return; }
  const a = e.class_assessment;
  const proposed = a.candidates.find(c => c.id === a.proposed_class);
  $("class-result").innerHTML = `<div class="panel">
    <h3>${proposed ? esc(proposed.name) : "Class review required"}</h3>
    <p>${badge(statusOf(e.nodes.mission_class))}${e.approved_class ? ` Approved class <strong>${esc(e.approved_class)}</strong>` : ""}</p>
    ${reviewButton(e.nodes.mission_class, "Review class")}
  </div>${a.candidates.map(c => `<details class="item" ${c.rank === "primary" ? "open" : ""}>
    <summary>${esc(c.id)} · ${esc(c.name)} · Score ${c.score} · ${esc(label(c.rank))}</summary>
    <p>${esc(c.definition)}</p>
    ${c.hits.map(hit => `<p><code>${esc(hit.rule_id)}</code> · ${esc(hit.field_id)} · +${hit.weight}<br>${esc(hit.fact)}<br><small>${esc(hit.reason)}</small></p>`).join("")}
  </details>`).join("")}`;
}

function renderFunctions() {
  const e = draft?.evaluation;
  if (!e?.approved_class) { $("function-result").textContent = "Approve the governing mission class to review functions."; return; }
  $("function-result").innerHTML = e.functions.map(fn => `<article class="panel">
    <div class="section-head"><h3>${esc(fn.name)} · <code>${esc(fn.function_id)}</code></h3>
      <div class="actions compact">${badge(fn.role || fn.proposal || "unresolved")} ${reviewButton(e.nodes[fn.node_id], "Review function")}</div>
    </div>
    ${fn.task_scope.map(t => `<p>${esc(t.description)}</p>`).join("")}
    <details><summary>Linked capability dimensions</summary>
      ${e.dimensions.filter(d => d.function_id === fn.function_id).map(d => `<div class="row">
        <span>${esc(d.name)} · <code>${esc(d.function_dimension_id)} / ${esc(d.dimension_id)}</code></span>
        ${badge(d.disposition || d.proposal)} ${reviewButton(e.nodes[d.node_id], "Review dimension")}
        <details><summary>Definition</summary><p>${esc(d.definition)}</p></details>
      </div>`).join("")}
    </details>
  </article>`).join("") + e.supporting_roles.map(role => `<div class="panel">
    <h3>${esc(role.role)} · Supporting</h3><p>${esc(role.treatment)}</p></div>`).join("");
}

function displaySpec(node, type, prerequisite) {
  if (!node) return "";
  const selected = node.decision && ["accepted", "conditionally_accepted"].includes(node.decision.disposition);
  const s = selected ? node.decision.value : node.proposal;
  const comparator = ({"<=": "≤", ">=": "≥", "==": "="})[s.comparator] ?? s.comparator ?? "";
  const value = s.target == null ? "Unresolved" : s.kind === "range"
    ? `${esc(s.target.lower)} to ${esc(s.target.upper)}`
    : typeof s.target === "object" ? "See recorded service profile" : esc(s.target);
  const title = type === "baseline" ? "Baseline" : "Case setting";
  const sensitivity = (s.sensitivity || []).map(q =>
    `<small>${esc(label(q.field))} · ${esc(q.points.join(" / "))} ${esc(q.unit)}</small>`).join("<br>");
  const condition = node.decision?.condition || node.condition;
  const reference = node.decision?.action !== "revise" ? referenceSummary(s) : "";
  return `<div class="measure-spec"><strong>${title}</strong> · ${s.target == null ? esc(value) : esc(comparator) + " " + value} ${esc(s.unit)} ${badge(statusOf(node))}
    ${reference ? `<p>${esc(reference)}</p>` : ""}
    ${condition ? `<p><small>${esc(condition)}</small></p>` : ""}
    ${s.pending ? `<p>${badge(prerequisite?.decision?.disposition === "accepted" ? "resolved prerequisite" : "open prerequisite")} <small>${esc(s.pending)}</small></p>` : ""}
    ${sensitivity ? `<p>${sensitivity}</p>` : ""}
    ${type !== "baseline" && s.reference_conditions ? `<details><summary>Specification and reference conditions</summary><p>${esc(s.reference_conditions)}</p></details>` : ""}
  </div>`;
}

function referenceSummary(specification) {
  if (!specification?.source_display) return "";
  if (specification.kind === "boolean" && specification.comparator === "TRUE") {
    return specification.reference_conditions || "";
  }
  return specification.source_display.split("\nSensitivity ·")[0].replace(/^Reference · /, "");
}

function renderBaseline() {
  const e = draft?.evaluation;
  const capDef = checked("toggle-capability");
  const measureDef = checked("toggle-measure");
  const query = $("measure-search").value.trim().toLowerCase();
  const columns = [
    ...(capDef ? ["Capability definition"] : []),
    "Baseline capability", "Associated measures and specifications",
    ...(measureDef ? ["Measure definition"] : []),
  ];
  const rows = [];
  for (const cap of e?.capabilities || []) {
    const found = e.criteria.filter(c => c.candidate_memberships.some(b => b.baseline_id === cap.baseline_id));
    const obligations = e.obligations.filter(o => o.baseline_ids.includes(cap.baseline_id));
    const members = [
      ...found.map(c => ({id: c.criterion_instance_id, name: c.name, definition: c.definition, c})),
      ...obligations.map(o => ({id: o.obligation_id, name: o.name, definition: o.definition, o})),
    ].filter(x => [x.id, x.name, x.c?.requirement_id, x.c?.measure_id, cap.baseline_id, cap.name].join(" ").toLowerCase().includes(query));
    members.forEach(({id, name, definition, c, o}, i) => {
      const n = e.nodes[c?.node_id || o?.node_id];
      const prerequisite = e.nodes[c?.case_prerequisite_node_id || o?.case_prerequisite_node_id];
      const specification = c ? displaySpec(e.nodes[c.baseline_spec_node_id], "baseline") +
        displaySpec(e.nodes[c.case_spec_node_id], "case", prerequisite) : displaySpec(n, "obligation", prerequisite);
      const scope = c ? [c.function_dimension_id, c.scope.target_id].filter(Boolean).join(" · ") : "Shared case obligation";
      rows.push(`<tr data-criterion="${esc(id)}">
        ${i === 0 && capDef ? `<td class="definition" rowspan="${members.length}">${esc(cap.definition)}</td>` : ""}
        ${i === 0 ? `<th scope="rowgroup" rowspan="${members.length}">${esc(cap.name)}<br><code>${esc(cap.baseline_id)}</code>
          <div class="actions compact">${reviewButton(e.nodes[cap.node_id], "Review capability")}</div></th>` : ""}
        <td><div class="measure-title"><strong>${esc(name)}</strong> ${badge(statusOf(n))}</div>
          <small><code>${esc(c?.measure_id || id)}</code> · ${esc(scope)}</small>
          ${c?.condition ? `<p><small>${esc(c.condition)}</small></p>` : ""}
          ${specification || `<p><small>${esc(n.why)} · ${esc(c?.native_unit)}</small></p>
            ${c?.case_specification_preview ? `<p><strong>Case proposal</strong> · ${esc(referenceSummary(c.case_specification_preview))}</p>` : ""}`}
          <div class="actions compact">${reviewButton(n, o ? "Review obligation" : "Review measure")}
            ${reviewButton(e.nodes[c?.baseline_spec_node_id], "Review baseline tolerance")}
            ${reviewButton(e.nodes[c?.case_spec_node_id], "Review case specification")}
            ${reviewButton(prerequisite, "Review prerequisite")}</div>
          <details><summary>Rationale and provenance</summary><p>${esc(n.why)}</p>
            ${sourceDetails(n.sources)}${c ? `<details><summary>Criterion scope and dependencies</summary>${pre({scope: c.scope, dependencies: c.specification_dependencies})}</details>` : ""}
          </details>
        </td>${measureDef ? `<td class="definition">${esc(definition)}</td>` : ""}</tr>`);
    });
  }
  const constraints = (e?.constraints || []).map(c => `<li><code>${esc(c.constraint_id)}</code> · ${esc(c.statement)} ${badge(c.assessment_status)}</li>`).join("");
  $("baseline-result").innerHTML = `<div class="table-wrap"><table id="step3-table">
    <thead><tr>${columns.map(col => `<th scope="col">${esc(col)}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("") || `<tr><td colspan="${columns.length}">${query ? "No matches." : "Approve functions and dimension contexts to propose criteria."}</td></tr>`}</tbody>
    </table></div>${constraints ? `<details class="item"><summary>Cross-cutting constraints</summary><ul>${constraints}</ul></details>` : ""}`;
}

function renderIssues() {
  const e = draft?.evaluation;
  const issues = e?.open_items || [];
  $("open-count").textContent = issues.length ? `(${issues.length})` : "";
  $("issues-result").innerHTML = issues.length ? issues.map(i => `<div class="panel">
    <div class="section-head"><h3>${esc(i.description)}</h3>${reviewButton(e.nodes[i.target_id], "Review item")}</div>
    <small><code>${esc(i.target_id)}</code> · ${esc(label(i.kind))}</small>
    ${i.blocks.length ? `<ul>${list(i.blocks)}</ul>` : ""}
  </div>`).join("") : "<p>No open items in the current proposal.</p>";
}

function render() {
  if (draft) mission = draft.mission;
  showMission();
  renderClass();
  renderFunctions();
  renderBaseline();
  renderIssues();
  $("generate").disabled = !!draft?.read_only;
  $("save-case").disabled = !draft || draft.read_only;
  $("export-case").disabled = !draft?.evaluation.approved_class || draft.read_only;
  for (const button of document.querySelectorAll("[data-batch]")) button.disabled = !draft || draft.read_only;
  const release = draft?.release || config.release;
  $("release").textContent = release.id;
  $("release-content").innerHTML = `<ul>${list(draft?.diagnostics || config.diagnostics)}</ul><details><summary>Workbook fingerprints</summary>${pre(release.workbooks)}</details>`;
}

function review(node) {
  currentNode = node;
  $("review-title").textContent = node.label;
  $("decision-action").value = node.proposal === "defer" ? "defer" : "retain";
  $("decision-condition").value = node.condition || "";
  $("rationale").value = "";
  $("decision-evidence").value = node.refs.join("\n");
  $("decision-authority").value = node.proposal?.authority_ref || "";
  $("uncertainty").value = "";
  message("review-message", "");
  const triggerRows = Object.entries(node.triggers).filter(([, value]) => value !== false).map(([key, value]) =>
    `${config.triggers[key]}${value === null ? " · unknown" : ""}`);
  $("review-detail").innerHTML = `<p>${esc(node.why)}</p><p>${badge(statusOf(node))}</p>
    ${node.stale_decision ? "<p>The prior judgment remains in the case history. Its basis changed.</p>" : ""}
    ${triggerRows.length ? `<h3>Intervention triggers</h3><ul>${list(triggerRows)}</ul>` : ""}
    ${node.constraints.length ? `<h3>Constraints</h3><ul>${list(node.constraints)}</ul>` : ""}
    ${node.alternatives.length ? `<p>Alternatives · ${esc(node.alternatives.map(label).join(", "))}</p>` : ""}
    ${node.blocks.length ? `<p>If deferred · ${esc(node.blocks.join(", "))}</p>` : ""}
    <details open><summary>Proposal and source records</summary>${pre(node.proposal)}${sourceDetails(node.sources)}</details>
    ${node.decision || node.stale_decision ? `<details><summary>Previous judgment</summary>${pre(node.decision || node.stale_decision)}</details>` : ""}`;
  setRevision();
  $("review-dialog").showModal();
}

function setRevision() {
  const revision = $("decision-action").value === "revise";
  $("revision-fields").hidden = !revision;
  if (!revision) return;
  if (!specKinds.includes(currentNode.kind)) {
    $("revision-fields").innerHTML = `<label>Revised selection <select id="revised-choice">
      ${opts(currentNode.alternatives.map(x => [x, label(x)]), currentNode.proposal)}</select></label>`;
    return;
  }
  const p = currentNode.proposal || {};
  const editable = {};
  for (const field of ["kind", "comparator", "unit", "target", "reference_conditions", "sensitivity", "distribution", "bound_direction"]) {
    if (field in p) editable[field] = p[field];
  }
  $("revision-fields").innerHTML = `<label>Revised specification JSON
    <textarea id="revised-spec" rows="9" class="code">${esc(pretty(editable))}</textarea></label>
    <small>Declare actual units, comparator, target, reference conditions and any material dependence in the applicable fields.</small>`;
}

function setDraft(value) {
  draft = value;
  if (draft.name) $("case-name").value = draft.name;
  render();
}

async function loadExample(name) {
  mission = await api(`/api/examples/${name}`);
  draft = null;
  $("case-name").value = name === "esperanza" ? "esperanza" : "";
  render();
  tab("mission");
}

async function refreshCases() {
  const {cases} = await api("/api/cases");
  $("saved-cases").innerHTML = opts([["", "Select a saved case"], ...cases.map(x => [x, x])], draft?.name);
}

$("decision-action").onchange = setRevision;
for (const id of ["evidence-quality", "confidence"]) {
  $(id).innerHTML = opts([["0", "0 · Unassessed"], ["1", "1 · Low"], ["2", "2 · Moderate"], ["3", "3 · High"]], "0");
}
document.addEventListener("click", safe(async event => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.tab) tab(button.dataset.tab);
  if (button.dataset.close) $(button.dataset.close).close();
  if (button.dataset.review) review(draft.evaluation.nodes[button.dataset.review]);
  if (button.hasAttribute("data-remove-task")) button.closest("[data-task]").remove();
  if (button.dataset.batch) {
    setDraft(await api(draftUrl() + "/batch", "POST", {...entry(), kind: button.dataset.batch}));
    message("message", `Recorded ${draft.recorded.length} routine judgments.`);
  }
}));
document.addEventListener("change", event => {
  if (event.target.hasAttribute("data-status")) {
    const field = event.target.closest("[data-fact]");
    field.querySelector("[data-known]").hidden = event.target.value !== "known";
    field.querySelector("[data-reason-control]").hidden = event.target.value !== "not_applicable";
  }
});
$("load-template").onclick = safe(() => loadExample("template"));
$("load-esperanza").onclick = safe(() => loadExample("esperanza"));
$("import-mission").onclick = () => $("mission-file").click();
$("mission-file").onchange = safe(async () => {
  const file = $("mission-file").files[0];
  if (!file) return;
  const data = JSON.parse(await file.text());
  if (!data.fields || !Array.isArray(data.tasks)) throw new Error("Choose a mission JSON file.");
  draft = null;
  mission = data;
  $("case-name").value = "";
  $("mission-file").value = "";
  render();
});
$("edit-json").onclick = safe(() => {
  $("mission-json").value = pretty(readMission());
  $("json-dialog").showModal();
});
$("json-form").onsubmit = safe(event => {
  event.preventDefault();
  const data = JSON.parse($("mission-json").value);
  if (!data.fields || !Array.isArray(data.tasks)) throw new Error("Provide mission fields and a list of tasks.");
  if (draft && data.mission_id !== draft.mission.mission_id) throw new Error("Start a new draft to change the mission ID.");
  mission = data;
  $("json-dialog").close();
  showMission();
}, "json-message");
$("generate").onclick = safe(async () => {
  const input = readMission();
  const changed = !!draft;
  const result = draft
    ? await api(draftUrl() + "/mission", "PATCH", {...entry(), mission: input})
    : await api("/api/drafts", "POST", {mission: input});
  setDraft(result);
  tab("classification");
  const stale = Object.values(draft.evaluation.nodes).filter(n => n.stale_decision).length;
  if (changed) message("message", stale ? `${stale} judgment(s) require renewed review.` : "Proposals updated.");
});
$("review-form").onsubmit = safe(async event => {
  event.preventDefault();
  const action = $("decision-action").value;
  const revised = $("revised-spec")?.value;
  const uncertainty = $("uncertainty").value.trim();
  const value = action === "revise" ? (specKinds.includes(currentNode.kind) ? JSON.parse(revised) : $("revised-choice").value) : undefined;
  const result = await api(draftUrl() + "/judgments", "POST", {
    ...entry(), target_id: currentNode.id, basis: currentNode.basis, action, value,
    condition: $("decision-condition").value.trim(), rationale: $("rationale").value.trim(),
    evidence_refs: lines($("decision-evidence").value), authority_ref: $("decision-authority").value.trim(),
    evidence_quality: Number($("evidence-quality").value), confidence: Number($("confidence").value),
    uncertainty: uncertainty ? JSON.parse(uncertainty) : undefined,
  });
  setDraft(result);
  $("review-dialog").close();
  const decision = result.recorded[0];
  const failures = decision.validation.filter(v => v.status === "failed").map(v => v.message);
  message("message", `Decision recorded · ${label(decision.disposition)}${failures.length ? "\n" + failures.join("\n") : ""}`, !!failures.length);
}, "review-message");
$("save-case").onclick = safe(async () => {
  setDraft(await api(draftUrl() + "/save", "POST", {...entry(), name: $("case-name").value.trim()}));
  await refreshCases();
  message("message", `Saved ${draft.name}-case.json.`);
});
$("open-case").onclick = safe(async () => {
  const name = $("saved-cases").value;
  if (!name) throw new Error("Select a saved case.");
  setDraft(await api(`/api/cases/${encodeURIComponent(name)}/open`, "POST", {}));
  tab("classification");
  message("message", draft.read_only ? draft.diagnostics.join("\n") : `Reopened ${name}.`, draft.read_only);
});
$("export-case").onclick = safe(async () => {
  const name = $("case-name").value.trim();
  await request(draftUrl() + "/export", "POST", {...entry(), name, write: true, replace: draft.name === name});
  message("message", `Exported ${name}-step3.json to the configured case directory.`);
});
for (const id of ["toggle-capability", "toggle-measure", "measure-search"]) $(id).oninput = renderBaseline;

safe(async () => {
  config = await api("/api/config");
  await loadExample("template");
  await refreshCases();
})();
