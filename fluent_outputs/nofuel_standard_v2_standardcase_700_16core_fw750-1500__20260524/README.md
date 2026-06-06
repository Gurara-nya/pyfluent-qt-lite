# nofuel_standard_v2_standardcase_700_16core_fw750-1500__20260524

Four-grid nofuel standard-v2 Fluent rerun package.

- Base case source: `D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard.cas.h5`
- Copied base case: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_700_16core_fw750-1500__20260524\cas_dat\standard.cas.h5`
- SHA256: `39DA48852D4701856C24BFF5183B351A9FA1E9F15D9402430E068A3C5874FDCE`
- Mesh root: `D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2`
- Included fw values: 750, 1000, 1250, 1500
- Cores: 16
- Iterations: 700
- Combo index: 256
- Completed 700-step DATs: fw750, fw1000, fw1250
- fw1500 status: failed under same-case 16-core conditions; Fluent journal recovery exposed floating point exception / node SIGSEGV, so no fw1500 700-step DAT is included.

Subdirectories:

- cas_dat/: copied base case, prepared cases, DAT files, Fluent report files.
- run/: batch state, manifest, stdout/stderr, Fluent logs.
- post/: DAT plots and mesh-independence analysis outputs.
- workspace/: input manifest and scratch notes.
