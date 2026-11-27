# Wildfire mission requirements

This local workbench implements Phase 1 Steps 1–3. It proposes a mission class, derives task-specific functions and dimension contexts, and prepares a reviewed baseline requirements package for Steps 4–7.

## Launch

Use Python 3.11 or later. Run these commands from the code repository root. Set the thesis root to the local OneDrive directory that contains `DOCS_&_INFORMATION`. The case directory must exist and be outside the thesis input tree.

### macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r Phase_1_Code_Development/steps_1_3/requirements.txt
export PHASE1_THESIS_ROOT="/path/to/PHD_THESIS_FOLDER"
.venv/bin/python -B -m Phase_1_Code_Development.steps_1_3 \
  --code-root . --thesis-root "$PHASE1_THESIS_ROOT" --release P1-REL-0007 \
  --case-dir Phase_1_Code_Development/steps_1_3/outputs
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r Phase_1_Code_Development/steps_1_3/requirements.txt
$env:PHASE1_THESIS_ROOT = "C:\path\to\PHD_THESIS_FOLDER"
.\.venv\Scripts\python.exe -B -m Phase_1_Code_Development.steps_1_3 `
  --code-root . --thesis-root "$env:PHASE1_THESIS_ROOT" --release P1-REL-0007 `
  --case-dir Phase_1_Code_Development/steps_1_3/outputs
```

Open [the local workbench](http://127.0.0.1:8765). Use `--port` for a different local port. Append `--check-release` to verify the files and named-table contracts without starting the web server.

## Workbook configuration

`P1-REL-0007` is the supported release. The loader checks the Workbook 00 manifest against the file versions and SHA-256 fingerprints in `Workbooks/Release_Reviews/P1-REL-0007/release_hashes.json`. It checks named-table headers, primary keys, and reference joins. For WB-04A, a missing or different active copy is reported and the registered member of the release ZIP is read in memory. WB-04A is a downstream reference companion. The app reads the workbooks as immutable inputs.

The Esperanza input also pins the working case workbook and the later consolidated measures workbook. The application checks those fingerprints against the case source files. A case whose release or source bytes differ opens as a saved snapshot for inspection. To rerun or edit it, use the matching source files and release.

## Review a mission

1. Enter your analyst name and load the template, the Esperanza example, or a mission JSON file. The form supports mission effects, incident status, tasks, area, local time with UTC offsets and an IANA zone, known fire state, protected values, notes, and source references. **Edit mission JSON** exposes advanced criterion scopes and case data. A field can be known, missing, unknown, or explicitly inapplicable. Click **Generate proposals** to apply edits.
2. Review the mission class. WB-01 rules match whole phrases within their declared fields, score each rule once, and retain ties and secondary candidates. Open the class evidence to inspect the matching facts and rule IDs. Approve or revise the governing decision before Step 2.
3. Review the functions and their linked dimension contexts. Use the task evidence to confirm active, supporting, conditional, or outside-scope dispositions. The context ID identifies the function-specific use of an LD dimension. A routine batch button applies reviewed recommendations with no open intervention trigger. Review flagged records individually.
4. Review capabilities and measures in Step 3. The two definition checkboxes operate independently. Use the filter to find a capability ID, requirement ID, or measure. Conditional measures stay visible with their trigger. Each selected criterion has independent review controls for its baseline tolerance, scoped case specification, and any implementation prerequisite. Use **Open items** to revisit deferred decisions and other missing inputs.
5. Enter a case name and click **Save case**. Select the saved case to reopen its inputs and history. **Export Step 3 JSON** writes `<case-name>-step3.json` to the case directory. Confirmed decisions stay effective until their basis changes. Affected overrides are flagged for review, and superseded judgments remain in the history.

Section IV.D of SciTech v8 supplies the decision protocol. A record preserves the initial proposal, missing/ambiguity/conflict/quality/authority triggers (including unknowns), action, proposed value, rationale, evidence, separate confidence and evidence quality ratings (0–3), uncertainty, validation, and disposition. Conditional acceptance requires an explicit supported condition, bound, or branch. Numerical review validates the governing unit and comparison, concrete scope and reference conditions, and authorization. Use the proposed or catalog fields already displayed, and give an authorization reference for a revised numerical entry. In the specification JSON, `kind` identifies a threshold, range, Boolean target, or registered service profile. A range records its governing bound direction. Sensitivity sweeps use `field`, `points`, `unit`, and applicable held-fixed settings. A distribution or bounded uncertainty record also declares its reference conditions and material dependence. Confidence ratings guide review and sensitivity and have no mathematical effect on a threshold.

## Esperanza reference case

The example uses the bounded Cabazon/Twin Pines analytical scope for 26 October 2006, 06:00–12:00 PDT. The known fire drives monitoring. Qualifying new ignitions drive detection, with their own event clocks and the candidate test-population definition still open. Decision Support is a supporting role. Confinement is outside the case.

The consolidated numerical settings were authorized for this case in the 26 November 2026 implementation conversation (`EF-APP-20261126`). Their conditions and sensitivity points are retained. The `R-LD09-02` case tolerance of ≤10 m stays distinct from the unresolved WB-03 baseline. The exported case records the baseline deferral and measure inclusion. Required geometry, the qualifying event and opportunity basis, and candidate-dependent verification still have open items. `R-LD21-01` keeps one scoped criterion per dwelling, used by both CB8 and CB10. `EF-OBL-001` is the shared ≥0.98 opportunity obligation. `R-LD01-01` evaluates ≥0.95 conditional detection within 25 minutes. `FL-004` is carried as a conditional Step 5 reference.

## Step 3 export contract

The `phase1.step3` JSON envelope uses schema version `1.0.0`. A `phase1.case` file stores the editable mission, review history, and a reproducible evaluation snapshot. The release ID, exact workbook and case-source fingerprints, and mission hash travel with the records. The historical HTML report and its JSON retain their existing interface.

- **Step 4.** `mission_class_handoff`, `function_dimension_handoff`, and `baseline_conditioning_handoff` connect the mission scope, class and function decisions, and baseline memberships to conditioning. The criterion instance carries its scope, actual unit, comparator, readiness, and the referenced measure. A missing baseline reference blocks baseline-relative conditioning. An independently supported absolute case specification has its own readiness.
- **Step 5.** `mission_selected_functions`, task scopes, and constraint IDs supply the function-link endpoints and candidates for interface review. Optional `later_step_references` carry scoped case facts such as the FL-004 receipt deadline rule.
- **Step 6.** `baseline_criterion_instances` and `baseline_instances` carry scoped criterion IDs and the atomic WB-03 criterion-link keys used by WB-06. Requirements can be conditioned for changes in demand. Supplied performance, candidate feasibility, and mission outcomes have their own later assessment records.
- **Step 7.** Criterion instance, function context, scope, and membership keys connect to the WB-07 `mccrv_*` contracts for MCCRS assembly. The registered legacy names remain in the workbook. Consumer code for arbitrary new exports, scenario rules, function interactions, and delta evaluation is future Phase 1 work. This app stops at the Step 3 package. The subsequent methodology uses the assembled MCCRS for Ways-first generation and screening, then Means and joint assessment.

An unresolved specification has a null target and an explicit readiness and blocking record. Explicit zero and false remain typed values. Case specifications, sensitivity points, distributions, and uncertainty bounds carry separate representations. Shared memberships refer to one criterion instance at each unique required scope.

## Verify

Set `PHASE1_THESIS_ROOT` as above and run from the repository root:

```text
python -B -m unittest discover -s Phase_1_Code_Development/steps_1_3/tests -v
```

Use the Python interpreter in `.venv`. Tests exercise the registered release, malformed tables and joins, the normal web API for Esperanza and a non-Esperanza reconnaissance mission, and persistence and stale decisions. The included Esperanza artifacts record software workflow verification. Operational validity depends on separate evidence.
