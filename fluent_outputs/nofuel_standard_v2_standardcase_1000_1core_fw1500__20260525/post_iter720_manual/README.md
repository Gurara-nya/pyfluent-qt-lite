# nofuel standard-v2 four-grid 16-core post-processing and mesh independence

## Data range

- Post directory: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_1000_1core_fw1500__20260525\post_iter720_manual`
- DAT source: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_1000_1core_fw1500__20260525\cas_dat`
- Selected DAT files: `1`; all selected records match `iter720` and are checked against `700` residual iterations.
- Requested target grids: `fw1500`.
- Metrics are computed from fuel-wall UDM rows where `udm_FuelWallFlag > 0.5`, area-weighted by `udm_FaceArea`.
- Per-DAT HDF5 figures live under `dat_plots/`; aggregate mesh-independence figures live under `figures/`.

## Verdict

- Physical validation accepted `1/1` selected DAT files.
- Finest accepted grid for this run: `fw1500`.
- Campaign completion: all requested grids produced accepted DAT files.
- Strict same-setup adjacent-grid verdict is unavailable because fewer than two accepted 16-core primary cases were available.

## Finest Adjacent Check

| metric | comparison | relative diff % | threshold % | verdict |
|---|---|---:|---:|---|
| - | - | - | - | unavailable |

## Summary Metrics

| fw | status | setup | cells | fuel-wall cells | area m2 | burn mm/s | Tsurf K | Gf kg/m2/s | wall T K | cont. final |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1500 | accepted | primary standard case, 16 cores | 168286 | 1500 | 0.001050 | 1.652844 | 832.148 | 1.520617 | 832.148 | 1.198e-04 |

## Relative Difference To `fw1500`

| fw | burn diff % | Tsurf diff % | Gf diff % | wall T diff % |
|---:|---:|---:|---:|---:|
| 1500 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Adjacent Mesh Change

| pair | status | mixed setup | burn change % | Tsurf change % | Gf change % | wall T change % |
|---|---|---|---:|---:|---:|---:|

## Figures

- [figures/mesh_metrics_vs_fw.png](figures/mesh_metrics_vs_fw.png)
- [figures/relative_difference_to_fw1500.png](figures/relative_difference_to_fw1500.png)
- [figures/adjacent_mesh_change.png](figures/adjacent_mesh_change.png)
- [figures/fuelwall_profile_burn_rate.png](figures/fuelwall_profile_burn_rate.png)
- [figures/fuelwall_profile_tsurf.png](figures/fuelwall_profile_tsurf.png)
- [figures/fuelwall_profile_gf_total.png](figures/fuelwall_profile_gf_total.png)
- [figures/continuity_residual_histories.png](figures/continuity_residual_histories.png)

## Output Files

- `mesh_independence_metrics.csv`: fuel-wall area-weighted metrics for each selected DAT.
- `mesh_independence_convergence.csv`: relative differences to `fw1500`.
- `mesh_independence_adjacent.csv`: adjacent-grid changes.
- `fuelwall_profiles_binned.csv`: binned fuel-wall axial profiles.
- `residual_summary.csv`: residual final values and iteration counts.
- `post_summary.json`: machine-readable verdict metadata.
