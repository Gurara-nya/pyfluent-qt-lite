# Nofuel Standard V2 700 步计算状态

运行日期：2026-05-24

网格根目录：

`D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2`

## 主批处理

- Case/DAT 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat`
- 日志/state 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- 核数：16
- 迭代步数：700

## 主批处理结果

| Mesh tag | 状态 | 尝试次数 | DAT 大小 | 残差步数 | 后处理状态 |
|---|---:|---:|---:|---:|---|
| `nofuel-standard-v2-fw750` | complete | 1 | 34008526 | 700 | accepted |
| `nofuel-standard-v2-fw1000` | complete | 1 | 35890976 | 700 | accepted |
| `nofuel-standard-v2-fw1250` | complete | 1 | 36925976 | 700 | 文件级可读但物理异常，已被 8 核重算 DAT 替代 |
| `nofuel-standard-v2-fw1500` | failed | 3 | 0 | 0 | 已由 8 核 `flowsoft-lr` 补算补齐 |
| `nofuel-standard-v2-fw1750` | complete | 2 | 46002060 | 700 | accepted |
| `nofuel-standard-v2-fw2000` | complete | 1 | 48968585 | 700 | accepted |

原始 `fw1250` DAT 的物理异常表现为：continuity final residual `2.799e+06`，fuel-wall 面积加权燃速约 `0.001146 mm/s`，Tsurf 约 `565 K`。

## fw1250 重算

### 16 核同条件重算

- Case/DAT 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat\fw1250_rerun_20260524`
- 日志/state 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run\fw1250_rerun_20260524`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- 核数：16
- 结果：Fluent 在 41-50 步附近断开，错误为 `StatusCode.UNAVAILABLE` / connection reset `10054`，未生成 DAT。

### 8 核标准 case 重算

- Case/DAT 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat\fw1250_rerun_8core_20260524`
- 日志/state 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run\fw1250_rerun_8core_20260524`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- 核数：8
- DAT：`combo-256-nofuel-standard-v2-fw1250-rerun2-iter700-8core.dat.h5`
- DAT 大小：39615390
- 文件级校验：HDF5 可读，continuity residual 迭代步数 700，UDM shape `116700x60`
- 后处理物理指标：fuel-wall 面积加权燃速约 `1.609177 mm/s`，Tsurf 约 `831.222 K`，Gf_total 约 `1.480443 kg/m2/s`，continuity final residual `9.053e-05`
- 当前状态：accepted，并作为当前 `fw1250` 分析输入。

## fw1500 补算

主批处理中的 `fw1500` 多次在 `/solve/iterate` 期间由 Fluent 端断开：

`StatusCode.UNAVAILABLE`，connection reset `10054`。

随后使用 nofuel 网格包说明中匹配的 `flowsoft-lr` 基准 case，并将并行核数降为 8，对 `fw1500` 做独立补算。补算结果已合并在本项目内部：

- Case/DAT 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\cas_dat\fw1500_flowsoftlr_8core_recovery`
- 日志/state 目录：`F:\pyfluent_qt_lit\fluent_outputs\nofuel_standard_v2_700__20260524\run\fw1500_flowsoftlr_8core_recovery`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um-flowsoft-lr.cas.h5`
- 核数：8
- 迭代步数：700
- DAT：`combo-256-nofuel-standard-v2-fw1500-flowsoftlr-probe-iter700-8core.dat.h5`
- DAT 大小：43122378

该补算 DAT 已通过 HDF5 文件级校验，continuity residual 迭代步数为 700，UDM shape 为 `116700x60`。

## 当前有效覆盖

本项目现在已覆盖 nofuel standard-v2 六个网格的 700 步有效 DAT：

- `fw750`、`fw1000`、`fw1750`、`fw2000` 来自 16 核主批处理。
- `fw1250` 来自 8 核标准 case 重算。
- `fw1500` 来自 8 核 `flowsoft-lr` 补算。

当前不同 msh 后处理见 `post/README.md`。若后续需要严格同条件比较，建议将六个网格统一用同一基准 case 和同一核数设置重跑一轮。
