# nofuel_standard_v2_standardcase_1300_16core_fw750-1500__20260525

Four-grid nofuel standard-v2 Fluent rerun package.

- Base case source: `D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard.cas.h5`
- Copied base case: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_1300_16core_fw750-1500__20260525\cas_dat\standard.cas.h5`
- Mesh root: `D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2`
- Included fw values: 750, 1000, 1250, 1500
- Cores: 16
- Iterations: 1300
- Combo index: 256
- Completed DATs: fw750, fw1000, fw1250, fw1500

Run notes:

- fw750 completed after retry; a valid attempt-2 DAT was retained and verified by final residual iteration 1300.
- fw1000 and fw1250 each completed in one clean attempt.
- fw1500 produced a valid attempt-2 DAT; a redundant later retry was stopped after the valid DAT was confirmed.
- Fluent HDF5 residual datasets retain 800 history rows for these 1300-step outputs, so completion is verified by residual final iteration rather than row count alone.

Subdirectories:

- `cas_dat/`: copied base case plus per-fw prepared cases and DAT files.
- `run/`: per-fw batch state, manifests, logs, and final campaign status JSON/CSV.
- `post/`: per-DAT HDF5 plots and aggregate mesh-independence analysis outputs.

Grid-independence verdict:

- Aggregate post-processing accepted 4/4 selected DAT files.
- Finest accepted grid: fw1500.
- Strict same-setup adjacent comparison fw1250 -> fw1500 passes all configured thresholds.
- See `post/README.md` and `post/post_summary.json` for tables, plots, and machine-readable details.
