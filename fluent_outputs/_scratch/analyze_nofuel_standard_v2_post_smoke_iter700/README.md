# nofuel standard-v2 four-grid 16-core post-processing and mesh independence

## Data range

- Post directory: `F:\pyfluent_qt_lit\fluent_outputs\_scratch\analyze_nofuel_standard_v2_post_smoke_iter700`
- DAT source: `F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_standardcase_700_16core_fw750-1500__20260524\cas_dat`
- Selected DAT files: `3`; all selected records match `iter700` and are checked against `700` residual iterations.
- Requested target grids: `fw750, fw1000, fw1250, fw1500`.
- Metrics are computed from fuel-wall UDM rows where `udm_FuelWallFlag > 0.5`, area-weighted by `udm_FaceArea`.
- Per-DAT HDF5 figures live under `dat_plots/`; aggregate mesh-independence figures live under `figures/`.

## Verdict

- Physical validation accepted `3/3` selected DAT files.
- Finest accepted grid for this run: `fw1250`.
- Campaign completion: incomplete or caveated; see the campaign completion caveat below.
- The strict same-setup adjacent comparison `fw1000 -> fw1250` is within all configured thresholds.

## Campaign Completion Caveat

- Completed selected grids: `fw750, fw1000, fw1250`.
- Accepted grids: `fw750, fw1000, fw1250`.
- Missing target grids: `fw1500`.

| fw | status | attempts | note |
|---:|---|---:|---|
| 1500 | failed_numerical |  | same-case 16-core attempts failed; PyFluent gRPC reset; Fluent journal showed floating point exception / node SIGSEGV |

## Excluded DAT Files

| fw | tag | setup | reason |
|---:|---|---|---|
| 1500 | nofuel-standard-v2-fw1500 | non-target intermediate data | excluded because filename does not contain iter700 |

## Finest Adjacent Check

| metric | comparison | relative diff % | threshold % | verdict |
|---|---|---:|---:|---|
| fuel-wall area mean burn rate (mm/s) | fw1000 vs fw1250 | 0.1311 | 1.000 | pass |
| fuel-wall area mean Tsurf (K) | fw1000 vs fw1250 | -0.0084 | 0.500 | pass |
| fuel-wall area mean Gf_total (kg/m2/s) | fw1000 vs fw1250 | 0.1311 | 1.000 | pass |
| fuel-wall face SV_WALL_T_INNER (K) | fw1000 vs fw1250 | -0.0084 | 0.500 | pass |

## Summary Metrics

| fw | status | setup | cells | fuel-wall cells | area m2 | burn mm/s | Tsurf K | Gf kg/m2/s | wall T K | cont. final |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 750 | accepted | primary standard case, 16 cores | 136324 | 750 | 0.001050 | 1.638022 | 831.763 | 1.506980 | 831.763 | 4.064e-05 |
| 1000 | accepted | primary standard case, 16 cores | 144052 | 1000 | 0.001050 | 1.645236 | 831.842 | 1.513617 | 831.842 | 8.472e-05 |
| 1250 | accepted | primary standard case, 16 cores | 155166 | 1250 | 0.001050 | 1.643082 | 831.912 | 1.511635 | 831.912 | 1.302e-04 |

## Relative Difference To `fw1250`

| fw | burn diff % | Tsurf diff % | Gf diff % | wall T diff % |
|---:|---:|---:|---:|---:|
| 750 | -0.3080 | -0.0180 | -0.3080 | -0.0180 |
| 1000 | 0.1311 | -0.0084 | 0.1311 | -0.0084 |
| 1250 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Adjacent Mesh Change

| pair | status | mixed setup | burn change % | Tsurf change % | Gf change % | wall T change % |
|---|---|---|---:|---:|---:|---:|
| fw750 -> fw1000 | accepted -> accepted | False | 0.4404 | 0.0096 | 0.4404 | 0.0096 |
| fw1000 -> fw1250 | accepted -> accepted | False | -0.1309 | 0.0084 | -0.1309 | 0.0084 |

## Figures

- [figures/mesh_metrics_vs_fw.png](figures/mesh_metrics_vs_fw.png)
- [figures/strict_primary_metrics_accepted_only.png](figures/strict_primary_metrics_accepted_only.png)
- [figures/relative_difference_to_fw1250.png](figures/relative_difference_to_fw1250.png)
- [figures/adjacent_mesh_change.png](figures/adjacent_mesh_change.png)
- [figures/fuelwall_profile_burn_rate.png](figures/fuelwall_profile_burn_rate.png)
- [figures/fuelwall_profile_tsurf.png](figures/fuelwall_profile_tsurf.png)
- [figures/fuelwall_profile_gf_total.png](figures/fuelwall_profile_gf_total.png)
- [figures/continuity_residual_histories.png](figures/continuity_residual_histories.png)

## Output Files

- `mesh_independence_metrics.csv`: fuel-wall area-weighted metrics for each selected DAT.
- `mesh_independence_convergence.csv`: relative differences to `fw1250`.
- `mesh_independence_adjacent.csv`: adjacent-grid changes.
- `fuelwall_profiles_binned.csv`: binned fuel-wall axial profiles.
- `residual_summary.csv`: residual final values and iteration counts.
- `post_summary.json`: machine-readable verdict metadata.
