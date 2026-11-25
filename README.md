# ABM-MCTS-GPU-Framework

**ABM-MCTS-GPU-Framework** is a software framework that combines Agent-Based Modeling (ABM), Monte Carlo Tree Search (MCTS), and GPU acceleration using CUDA via CuPy. It simulates wildfire spread and suppression using aerial and ground firefighting agents. The core fire spread model calculations run on a GPU which enables the efficient simulations required for exploring a vast decision space in an uncertain environment.

## Thesis workspace

Open `PhD_Wildfire.code-workspace` to access the code repository and the two configured OneDrive roots. Configure their actual local paths separately on each machine.

- `PHD_THESIS_FOLDER` is the active research and documentation root. Its `README.md` provides navigation to thesis writing, committee records, publications, research management and simulation resources under `DOCS_&_INFORMATION/`.
- The active methodology workbooks are in `PHD_THESIS_FOLDER/DOCS_&_INFORMATION/Thesis_Methodology_Development_New/01_Phase_1/Workbooks/`. Consult the methodology's `START_HERE.md`, Workbook 00 and the migration record before selecting a governing release.
- `PHD THESIS PROCESS` is the legacy research-process root. Selected material was copied into the active root on 16 November 2026. The migration manifest records destinations and retained historical copies. Literature, `_1_OLDMATERIAL` and Mendeley information were excluded.
- This repository contains the ABM–MCTS simulation environment. The historical partial Phase 1 scripts remain with their original workbook inputs under the methodology folder's `01_Phase_1/Supporting_Material/Code/`. Future Phase 1 development must use the approved workbook contracts and explicitly configured external roots.
- Cristian deferred logbook reconciliation and relocation. Confirm the current logbook path and latest entries with him before updating it.

---

## 🔥 Framework Overview

### Wildfire Spread Simulation (GPU-based Fire Spread Model GPU-FSM)
- Implements a Rothermel-based fire spread model in CUDA via CuPy.
- Simulates fire spread across a raster landscape using real topographic and fuel data.
- The `SurrogateFireModelROS` class manages the two kernels designed to run on the GPU.
- One of the kernels 

### Agent-Based Firefighting Model
- Built with the Mesa ABM library.
- Agents include airtankers and ground crews.
- Agents can move, drop retardant, or build fire lines.

### Monte Carlo Tree Search (MCTS) Planner
- Explores action sequences to minimize a reward function composed of area burned and structures destroyed.
- Performs fast forward simulations using GPU-FSM.
- Builds and traverses a search tree to select optimal agent actions.

### Wind Schedules and Uncertainty
- Initial wind conditions are loaded from CSV schedules.
- Each benchmark uses two wind schedules: low uncertainty and high uncertainty.
- Supports stochastic wind forecasts via sampling.

---

## 📁 Benchmark Scenarios
Three real wildfire landscapes were used:

| Fire Name       | GeoTIFF File                  | Description                          |
|----------------|-------------------------------|--------------------------------------|
| Marshall Fire  | `marshall_enhanced.tif`       | Colorado fire, rapid urban spread.   |
| Camp Fire      | `camp_fire_three_enhanced.tif` | California fire, high damage event.  |
| Esperanza Fire | `cali_test_big_enhanced.tif`  | Complex terrain and wind dynamics.   |

Each scenario is run with two wind settings:
- **Medium Uncertainty** (low variability forecast)
- **High Uncertainty** (greater wind prediction error)

---

## ⚙️ Installation and Setup

### Prerequisites
- Python 3.11 (Everything was made with 3.11 other versions may work but not tested)
- NVIDIA GPU with CUDA support

### 1. Clone the Repository
```bash
git clone https://github.com/oabyad1/ABM-MCTS-GPU-Framework.git
cd ABM-MCTS-GPU-Framework
```

### 2. Install CUDA Toolkit
- Download from: https://developer.nvidia.com/cuda-downloads
- Ensure drivers are updated.

### 3. Set Up Python Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Install CuPy (based on your CUDA version)
Examples:
```bash
pip install cupy-cuda118  # for CUDA 11.8
pip install cupy-cuda115  # for CUDA 11.5
```

---

## 🚀 Running Simulations

### Option 1: Interactive Dashboard
```bash
python dashboard.py
```
- Web-based GUI to set landscape, wind, and agent parameters.
- Starts/stops MCTS-controlled simulation.

### Option 2: Batch Experiments
```bash
python run_all_strategies_batch.py --schedule wind_schedule_esper_high.csv --runs 10
```
- Runs multiple strategies over chosen wind schedule.
- Outputs results to CSVs and images.
- This can take a long time depending on the landscape being used and the GPU available
- Esperanza scenarios with three agents required approximately 12 hours per full scenario on an RTX 5090



[//]: # (---)

[//]: # ()
[//]: # (## 📊 Outputs and Visualization)

[//]: # (- **Fire Spread Maps**: PNGs showing final burn perimeters.)

[//]: # (- **MCTS Tree Diagrams**: Visualizes decision paths and rewards.)

[//]: # (- **Logs**: JSON files tracking rollout timings and fire metrics.)

[//]: # (- **CSV Summaries**: Run-by-run statistics &#40;area burned, drops used&#41;.)

---

## 🧪 Main Scripts

| File / Folder                   | Description                                                  |
|---------------------------------|--------------------------------------------------------------|
| `FIRE_MODEL_CUDA.py`            | GPU fire spread arrival time solver.                         |
| `rothermal_ROS_kernal.py`       | Rate of spread solver that uses empirical Rothermel rules    |
| `model.py`                      | Main Mesa wildfire environment.                              |
| `mcts.py`                       | MCTS planner implementation.                                 |
| `airtankeragent.py`             | Airtanker agent behavior.                                    |
| `groundcrew.py`                 | Ground crew agent logic.                                     |
| `dashboard.py`                  | Interactive web GUI with Panel.                              |
| `run_all_strategies_batch.py`   | Batch simulation runner.                                     |
| `wind_schedule_utils.py`        | Helpers for handling wind forecasts.                         |
| `uncertainty_quantification.py` | Tool for uncertainty analysis with visual plots.             |

---
## 🧪 Other Scripts

| File / Folder                                       | Description                                                                                                                                                                         |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `airtanker_agents/CL415_agent.py`                   | CL-415 water scooping airtanker agent configuration (inherits ScooperAgent).                                                                                                        |
| `airtanker_agents/Dash8_400MRE_agent.py`            | Dash 8-400 MRE airtanker agent configuration (heavy turboprop water bomber).                                                                                                        |
| `airtanker_agents/FireHerc_agent.py`                | “FireHerc” firefighting C-130 airtanker agent configuration (night-capable ops).                                                                                                    |
| `airtanker_agents/at_802f_agent.py`                 | AT-802F single-engine airtanker agent configuration (Air Tractor Fire Boss).                                                                                                        |
| `airtanker_agents/c130j_agent.py`                   | C-130J airtanker agent configuration (large air tanker parameters).                                                                                                                 |
| `airtanker_agents/scooper_agent.py`                 | Base class for water-scooping airtankers (supports lake refill operations).                                                                                                         |
| `compare_reward_wins.py`                            | Compares how often each strategy achieves the lowest composite score across two scenarios, outputting a win-count chart and CSV.                                                    |
| `drops_surrogate.py`                                | Defines surrogate-model retardant drop behavior (drop placement and effects on fire spread).                                                                                        |
| `fireline_abm.py`                                   | Utility for computing fireline (containment line) geometry per sector in the ABM.                                                                                                   |
| `FireModel_AT_comparisons.py`                       | Compares GPU surrogate fire spread vs FARSITE under dynamic winds; outputs side-by-side arrival maps, confusion matrices, time-series plots, and metrics.                           |
| `forecast_provider.py`                              | Wind-forecast generator consistent with the actual truth schedule, providing updated forecast tables to the MCTS.                                                                   |
| `optimization_slope_loop.py`                        | Calibrates a slope factor by minimizing differences between FARSITE and the GPU fire model on uniform-fuel landscapes (uses landscapes from `slope_preprocessing.py`).              |
| `raws_to_sched.py`                                  | Builds a binned 120-min forecast/uncertainty table from RAWS weather data (outputs columns: start_min, end_min, speed_mean/σ, dir_mean/σ).                                          |
| `results_postprocessing.py`                         | Post-processes batch run results from `summary.csv`: drops invalid runs, normalizes area/building metrics by baseline, computes composite scores, and generates summary plots/CSVs. |
| `results_postprocessing_depth.py`                   | Post-processes MCTS rollout-depth experiment results: filters to MCTS runs, computes composite performance vs rollout depth, and outputs depth-comparison plots/CSVs.               |
| `slope_preprocessing.py`                            | Prepares landscapes with a constant fuel model across the area (used to generate inputs for slope calibration experiments).                                                         |
| `visualization.py`                                  | Interactive visualization script to run and observe a single wildfire simulation in real-time (no MCTS tree search).                                                                |

---

## Benchmark Heuristic Allocation Strategies

To benchmark the performance of the MCTS-based controller, the framework includes a set of **heuristic allocation strategies** that represent some common tactical decision rules that could be implemented for wildfire suppression. All strategies operate within the same simulation environment, asset constraints, and decision interval (**Δt = 120 minutes**) and are implemented as standalone, non-plotting scripts for scalable batch experimentation.

These heuristic policies are intentionally simpler than the MCTS controller and are designed to isolate the value of different information signals (wind, rate of fire spread, and structural exposure) and decision philosophies.

### Strategy Descriptions

**Baseline.**
*Random Allocation* assigns each available asset to a randomly selected open sector at each decision point. It uses no fire behavior, wind, or structural information and serves as a stochastic lower-bound baseline.

**Rate-of-Spread–Driven.**
*ROS–Truth* and *ROS–Mean* prioritize sectors based on the perimeter rate of spread (ROS). Ground crews are assigned to the highest-ROS sectors, while airtankers are sampled with probability proportional to sector ROS. The Truth variant uses ROS computed from the observed fire state, while the Mean variant evaluates ROS under a forecast-mean wind realization.

**Structure–Driven.**
*Structures–Exposure* allocates assets based on static structure counts per sector. *Structures–Outcome (Mean)* and *Structures–Outcome (Truth)* instead use precomputed estimates of buildings that would burn by ( t_{\max} ) under no suppression, using forecast-mean and truth wind schedules respectively, and allocate assets according to projected structural loss.

**Wind–Driven.**
Wind-based strategies classify sectors as head, flanks, or heel relative to wind direction. *Wind–Truth* and *Wind–Mean* use the current truth or forecast-mean wind, respectively, while *Wind–Mean Lookahead* and *Wind–Truth Lookahead* perform classification using wind at ( t + \Delta t ). Crew and airtanker assignments follow fixed head/flank/heel priority rules.

---

### Heuristic Strategy–Script Mapping

| Script                                       | Strategy Name              | Category              | Allocation Logic / Information Used                                                                           |
| -------------------------------------------- | -------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------- |
| `dashboard_NO_PLOTTING.py`                   | MCTS                       | MCTS                  | Monte Carlo Tree Search over sequential suppression actions using stochastic fire spread and wind uncertainty |
| `random_allocations_NO_PLOTTING.py`          | Random Allocation          | Baseline              | Randomly assigns crews and airtankers to open sectors; no wind, ROS, or structure information                 |
| `ics_ros_weighted_NO_PLOTTING.py`            | ROS–Truth                  | Rate-of-Spread–Driven | Allocates assets based on perimeter ROS computed from the observed (truth) fire state                         |
| `ics_ros_weighted_mean_NO_PLOTTING.py`       | ROS–Mean                   | Rate-of-Spread–Driven | Same ROS logic as ROS–Truth, but evaluated under forecast-mean wind realization                               |
| `ics_buildings_NO_PLOTTING.py`               | Structures–Exposure        | Structure–Driven      | Allocates assets proportional to static structure counts per sector                                           |
| `ics_mean_burned_buildings_NO_PLOTTING.py`   | Structures–Outcome (Mean)  | Structure–Driven      | Uses precomputed burned-structure counts under forecast-mean wind with no suppression                         |
| `ics_truth_burned_buildings_NO_PLOTTING.py`  | Structures–Outcome (Truth) | Structure–Driven      | Uses precomputed burned-structure counts under truth wind with no suppression                                 |
| `ics_dynamic_NO_PLOTTING.py`                 | Wind–Truth                 | Wind–Driven           | Classifies sectors using current truth wind; allocates assets by head/flank/heel priority                     |
| `ics_dynamic_mean_NO_PLOTTING.py`            | Wind–Mean                  | Wind–Driven           | Same as Wind–Truth, but classification uses forecast-mean wind at time ( t )                                  |
| `ics_dynamic_mean_lookahead_NO_PLOTTING.py`  | Wind–Mean Lookahead        | Wind–Driven           | Sector classification based on forecast-mean wind at ( t + \Delta t )                                         |
| `ics_dynamic_truth_lookahead_NO_PLOTTING.py` | Wind–Truth Lookahead       | Wind–Driven           | Sector classification based on truth wind at ( t + \Delta t ) (perfect foresight)                             |

**Notes:**

* All heuristic policies execute at a fixed decision interval of **Δt = 120 minutes**.
* The `*_NO_PLOTTING.py` simply indicates that these scripts do not contain plotting functions.



[//]: # ()
[//]: # (## 📈 Research Usage)

[//]: # (- Framework supports statistical testing under uncertainty.)

[//]: # (- Designed for adaptive decision-making under dynamic conditions.)

[//]: # (- Validated against real wildfire scenarios.)

[//]: # ()
[//]: # (---)

[//]: # ()
[//]: # (## 🙌 Contributing)

[//]: # (Feel free to fork and extend the framework for other disasters, planning models, or improved fire simulations. Please cite relevant research if publishing.)

[//]: # ()
[//]: # (---)

## 📧 Contact
For questions or inquiries you may contact the project maintainer:

**Omar Abyad**  
Ph.D. Candidate, Aerospace Engineering  
Georgia Institute of Technology  
Email: oabyad@gatech.edu

---

## 📄 License
This project is licensed under the **MIT License**.  
You are free to use, modify, and distribute this software with attribution.  
See the `LICENSE` file for full license text.


