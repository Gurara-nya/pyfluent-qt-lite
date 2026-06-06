# nofuel standard-v2 后处理与网格无关性验证

## 数据范围

- 后处理目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\post`
- DAT 来源：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat`
- 共解析 `6` 个当前选用 `.dat.h5`，每个文件均来自 700 步计算结果。
- 同一个 `fw` 如果存在重算 DAT，则优先选用重算结果，旧异常 DAT 保留但不进入当前网格无关性统计。
- 指标主要来自 fuel-wall UDM：`udm_FuelWallFlag > 0.5` 的单元，并用 `udm_FaceArea` 做面积加权。
- 空间云图、直方图、残差图等逐 DAT 图件位于 `dat_plots/`；汇总网格无关性图件位于 `figures/`。

## 重要说明

- `fw1250` 是 8 核标准 case 重算结果；原始 `fw1250` 物理异常，已被该重算 DAT 替代。
- `fw1500` 是 8 核 `flowsoft-lr` 补算结果；其基准 case 和核数与主批处理结果不同。
- 因此 `fw1250` 和 `fw1500` 可以用于补齐结果覆盖和趋势观察，但不作为严格同条件网格无关性判据。
- 物理校验通过 `6/6` 个 DAT；物理校验失败的 DAT 不进入严格网格无关性判据。
- 严格同条件判据采用主批处理序列中最细的 `fw2000` 作为参考，并重点比较相邻较细网格 `fw1750`。

## 判定结论

- 当前主批处理序列在 `fw1750` 到 `fw2000` 的关键面积加权指标仍有超过阈值的变化，严格意义上不建议直接判定完全网格无关。
- 若后续论文/报告需要更严格结论，建议将 6 个网格统一用相同 `flowsoft-lr` case 和相同核数重跑，以消除 `fw1500` 补算条件差异。

### 未纳入当前统计的旧 DAT

| fw | tag | 来源 | 原因 |
|---:|---|---|---|
| 1250 | nofuel-standard-v2-fw1250 | primary standard case, 16 cores | superseded by nofuel-standard-v2-fw1250-standard-rerun-8core |

### 最细主批处理相邻网格检查

| 指标 | 比较 | 相对差异 % | 阈值 % | 结论 |
|---|---|---:|---:|---|
| fuel-wall area mean burn rate (mm/s) | fw1750 vs fw2000 | 1.8086 | 1.000 | 未通过 |
| fuel-wall area mean Tsurf (K) | fw1750 vs fw2000 | 0.0647 | 0.500 | 通过 |
| fuel-wall area mean Gf_total (kg/m2/s) | fw1750 vs fw2000 | 1.8086 | 1.000 | 未通过 |
| fuel-wall face SV_WALL_T_INNER (K) | fw1750 vs fw2000 | 0.0647 | 0.500 | 通过 |

## 汇总指标

| fw | 状态 | 来源 | cells | fuel-wall cells | area m2 | burn mm/s | Tsurf K | Gf kg/m2/s | wall T K | cont. final |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 750 | accepted | primary standard case, 16 cores | 136324 | 750 | 0.001050 | 1.643525 | 831.808 | 1.512043 | 831.808 | 1.662e-05 |
| 1000 | accepted | primary standard case, 16 cores | 144052 | 1000 | 0.001050 | 1.634993 | 831.600 | 1.504194 | 831.600 | 3.151e-05 |
| 1250 | accepted | standard case rerun, 8 cores | 155166 | 1250 | 0.001050 | 1.609177 | 831.222 | 1.480443 | 831.222 | 9.053e-05 |
| 1500 | accepted | flowsoft-lr recovery, 8 cores | 168286 | 1500 | 0.001050 | 1.632273 | 831.701 | 1.501691 | 831.701 | 4.279e-05 |
| 1750 | accepted | primary standard case, 16 cores | 182650 | 1750 | 0.001050 | 1.658564 | 832.069 | 1.525879 | 832.069 | 2.498e-05 |
| 2000 | accepted | primary standard case, 16 cores | 198816 | 2000 | 0.001050 | 1.629101 | 831.531 | 1.498773 | 831.531 | 3.722e-05 |

## 相对最细网格 `fw2000` 的差异

| fw | burn diff % | Tsurf diff % | Gf diff % | wall T diff % |
|---:|---:|---:|---:|---:|
| 750 | 0.8854 | 0.0333 | 0.8854 | 0.0333 |
| 1000 | 0.3617 | 0.0083 | 0.3617 | 0.0083 |
| 1250 | -1.2230 | -0.0372 | -1.2230 | -0.0372 |
| 1500 | 0.1947 | 0.0204 | 0.1947 | 0.0204 |
| 1750 | 1.8086 | 0.0647 | 1.8086 | 0.0647 |
| 2000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## 相邻网格变化

| pair | status | mixed setup | burn change % | Tsurf change % | Gf change % | wall T change % |
|---|---|---|---:|---:|---:|---:|
| fw750 -> fw1000 | accepted -> accepted | False | -0.5191 | -0.0250 | -0.5191 | -0.0250 |
| fw1000 -> fw1250 | accepted -> accepted | True | -1.5790 | -0.0454 | -1.5790 | -0.0454 |
| fw1250 -> fw1500 | accepted -> accepted | True | 1.4352 | 0.0576 | 1.4352 | 0.0576 |
| fw1500 -> fw1750 | accepted -> accepted | True | 1.6107 | 0.0443 | 1.6107 | 0.0443 |
| fw1750 -> fw2000 | accepted -> accepted | False | -1.7764 | -0.0647 | -1.7764 | -0.0647 |

## 图件

- [figures/mesh_metrics_vs_fw.png](figures/mesh_metrics_vs_fw.png)
- [figures/strict_primary_metrics_accepted_only.png](figures/strict_primary_metrics_accepted_only.png)
- [figures/relative_difference_to_fw2000.png](figures/relative_difference_to_fw2000.png)
- [figures/adjacent_mesh_change.png](figures/adjacent_mesh_change.png)
- [figures/fuelwall_profile_burn_rate.png](figures/fuelwall_profile_burn_rate.png)
- [figures/fuelwall_profile_tsurf.png](figures/fuelwall_profile_tsurf.png)
- [figures/fuelwall_profile_gf_total.png](figures/fuelwall_profile_gf_total.png)
- [figures/continuity_residual_histories.png](figures/continuity_residual_histories.png)

## 输出文件

- `mesh_independence_metrics.csv`：每个 DAT 的 fuel-wall 面积加权指标。
- `mesh_independence_convergence.csv`：相对 `fw2000` 的偏差。
- `mesh_independence_adjacent.csv`：相邻网格之间的变化。
- `fuelwall_profiles_binned.csv`：沿 fuel-wall 归一化轴向位置的分箱剖面。
- `residual_summary.csv`：残差最终值和迭代步数。
- `post_summary.json`：后处理元数据和判定结果。
