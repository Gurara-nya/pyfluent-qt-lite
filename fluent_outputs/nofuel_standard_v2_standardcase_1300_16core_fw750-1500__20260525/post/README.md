# nofuel standard-v2 four-grid 16-core post-processing and mesh independence

## Data range

- Post directory: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_1300_16core_fw750-1500__20260525\post`
- DAT source: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_1300_16core_fw750-1500__20260525\cas_dat`
- Selected DAT files: `4`; all selected records match `iter1300` and are checked against `1300` residual iterations.
- Requested target grids: `fw750, fw1000, fw1250, fw1500`.
- Metrics are computed from fuel-wall UDM rows where `udm_FuelWallFlag > 0.5`, area-weighted by `udm_FaceArea`.
- Per-DAT HDF5 figures live under `dat_plots/`; aggregate mesh-independence figures live under `figures/`.

## Verdict

- Physical validation accepted `4/4` selected DAT files.
- Finest accepted grid for this run: `fw1500`.
- Campaign completion: all requested grids produced accepted DAT files.
- The strict same-setup adjacent comparison `fw1250 -> fw1500` is within all configured thresholds.

## Finest Adjacent Check

| metric | comparison | relative diff % | threshold % | verdict |
|---|---|---:|---:|---|
| fuel-wall area mean burn rate (mm/s) | fw1250 vs fw1500 | 0.0161 | 1.000 | pass |
| fuel-wall area mean Tsurf (K) | fw1250 vs fw1500 | -0.0084 | 0.500 | pass |
| fuel-wall area mean Gf_total (kg/m2/s) | fw1250 vs fw1500 | 0.0161 | 1.000 | pass |
| fuel-wall face SV_WALL_T_INNER (K) | fw1250 vs fw1500 | -0.0084 | 0.500 | pass |

## Summary Metrics

| fw | status | setup | cells | fuel-wall cells | area m2 | burn mm/s | Tsurf K | Gf kg/m2/s | wall T K | cont. final |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 750 | accepted | primary standard case, 16 cores | 136324 | 750 | 0.001050 | 1.651672 | 831.951 | 1.519538 | 831.951 | 1.309e-05 |
| 1000 | accepted | primary standard case, 16 cores | 144052 | 1000 | 0.001050 | 1.650825 | 831.847 | 1.518759 | 831.847 | 1.008e-04 |
| 1250 | accepted | primary standard case, 16 cores | 155166 | 1250 | 0.001050 | 1.652849 | 831.983 | 1.520621 | 831.983 | 1.209e-04 |
| 1500 | accepted | primary standard case, 16 cores | 168286 | 1500 | 0.001050 | 1.652582 | 832.053 | 1.520376 | 832.053 | 1.286e-04 |

## Relative Difference To `fw1500`

| fw | burn diff % | Tsurf diff % | Gf diff % | wall T diff % |
|---:|---:|---:|---:|---:|
| 750 | -0.0551 | -0.0122 | -0.0551 | -0.0122 |
| 1000 | -0.1064 | -0.0247 | -0.1064 | -0.0247 |
| 1250 | 0.0161 | -0.0084 | 0.0161 | -0.0084 |
| 1500 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Adjacent Mesh Change

| pair | status | mixed setup | burn change % | Tsurf change % | Gf change % | wall T change % |
|---|---|---|---:|---:|---:|---:|
| fw750 -> fw1000 | accepted -> accepted | False | -0.0513 | -0.0124 | -0.0513 | -0.0124 |
| fw1000 -> fw1250 | accepted -> accepted | False | 0.1226 | 0.0163 | 0.1226 | 0.0163 |
| fw1250 -> fw1500 | accepted -> accepted | False | -0.0161 | 0.0084 | -0.0161 | 0.0084 |

## Figures

- [figures/mesh_metrics_vs_fw.png](figures/mesh_metrics_vs_fw.png)
- [figures/strict_primary_metrics_accepted_only.png](figures/strict_primary_metrics_accepted_only.png)
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
