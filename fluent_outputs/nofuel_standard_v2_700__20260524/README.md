# nofuel_standard_v2_700__20260524

本项目是 nofuel standard-v2 六个 Fluent 网格的 700 步计算归档，日期为 2026-05-24。

## 目录结构

- `cas_dat/`：主批处理的 prepared case、DAT 文件、report 文件和 UDF 工作副本。
- `cas_dat/fw1250_rerun_20260524/`：`fw1250` 16 核同条件重算诊断目录；Fluent 在 41-50 步附近断开，未生成 DAT。
- `cas_dat/fw1250_rerun_8core_20260524/`：`fw1250` 8 核标准 case 重算结果；这是当前后处理选用的 `fw1250` DAT。
- `cas_dat/fw1500_flowsoftlr_8core_recovery/`：`fw1500` 的 8 核 `flowsoft-lr` 补算 CAS/DAT、report 文件和相关 Fluent 工作文件。
- `run/`：主批处理 manifest、batch state、日志和状态说明。
- `run/fw1250_rerun_20260524/`：`fw1250` 16 核重算失败诊断日志。
- `run/fw1250_rerun_8core_20260524/`：`fw1250` 8 核重算 runner state、Fluent 日志、stdout/stderr。
- `run/fw1500_flowsoftlr_8core_recovery/`：`fw1500` 补算的 runner state、Fluent 日志、stdout/stderr 和补算说明。
- `post/`：本项目 DAT 后处理、逐 DAT 图件、汇总曲线和网格无关性验证报告。
- `workspace/`：预留给后续复查、重跑或手动检查的项目工作目录。

## 输入条件

- 网格根目录：`D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2`
- 主批处理基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- `fw1250` 8 核重算基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- `fw1500` 补算基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um-flowsoft-lr.cas.h5`
- 迭代步数：`700`
- 主批处理核数：`16`
- `fw1250` 当前选用重算核数：`8`
- `fw1500` 补算核数：`8`

## 结果摘要

主批处理完成了 `fw750`、`fw1000`、`fw1250`、`fw1750`、`fw2000` 五个网格的 700 步 DAT。后处理发现原始 `fw1250` 虽然文件级可读，但物理结果异常：continuity final residual 为 `2.799e+06`，fuel-wall 面积加权燃速约 `0.001146 mm/s`，Tsurf 约 `565 K`。

随后对 `fw1250` 做了重算：

- 16 核同条件重算：Fluent 在 41-50 步附近断开，错误为 `StatusCode.UNAVAILABLE` / connection reset `10054`，未生成 DAT。
- 8 核标准 case 重算：成功跑满 700 步，DAT 通过 HDF5 文件级校验和物理校验；该 DAT 已替代旧 `fw1250` 进入当前后处理统计。

`fw1500` 在 16 核主批处理中 3 次于 `/solve/iterate` 期间断开，未生成有效 DAT。随后使用 nofuel 包中匹配的 `flowsoft-lr` 基准 case，并降为 8 核，对 `fw1500` 做了稳定补算。该补算已并入本项目内部。

## 当前选用覆盖

| 网格 | 当前选用结果来源 | 文件级状态 | 物理状态 |
|---|---|---|---|
| `fw750` | 16 核主批处理 | 700 步 DAT 已通过 HDF5 校验 | accepted |
| `fw1000` | 16 核主批处理 | 700 步 DAT 已通过 HDF5 校验 | accepted |
| `fw1250` | 8 核标准 case 重算 | 700 步 DAT 已通过 HDF5 校验 | accepted |
| `fw1500` | 8 核 `flowsoft-lr` 补算 | 700 步 DAT 已通过 HDF5 校验 | accepted |
| `fw1750` | 16 核主批处理 | 700 步 DAT 已通过 HDF5 校验 | accepted |
| `fw2000` | 16 核主批处理 | 700 步 DAT 已通过 HDF5 校验 | accepted |

详细状态表和验证说明见 `run/STATUS.md`。

后处理图件与网格无关性验证见 `post/README.md`。当前不同 msh 的选用 DAT 均已通过物理校验，但由于 `fw1250` 和 `fw1500` 使用了 8 核补算路径，严格同条件网格无关性仍不完整；主批处理同条件序列中 `fw1750` 到 `fw2000` 的 fuel-wall 面积加权燃速/Gf 变化约 `1.81%`，超过 1% 判据，因此暂不建议判定为完全网格无关。

## 使用提醒

当前目录已经补齐六个网格的 700 步有效 DAT。若后续要做严格同条件对比，建议统一用同一个基准 case 和同一核数重跑六个网格。
