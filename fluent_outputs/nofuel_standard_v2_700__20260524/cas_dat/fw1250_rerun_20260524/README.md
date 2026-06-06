# fw1250_rerun_20260524

这是 `nofuel_standard_v2_700__20260524` 主项目内部的 `fw1250` 16 核同条件重算诊断目录。

## 背景

原始 `fw1250` DAT 虽然通过 HDF5 文件级校验，但后处理发现物理异常：continuity final residual 约 `2.799e+06`，fuel-wall 面积加权燃速接近零，Tsurf 约 `565 K`。因此先按主批处理同条件做一次 16 核重算。

## 输入

- 网格：`D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1250\d40-nofuel-standard-v2-fw1250-fluent.msh`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- 核数：`16`
- 迭代步数：`700`

## 结果

Fluent 在 41-50 步附近断开，错误为 `StatusCode.UNAVAILABLE` / connection reset `10054`。本目录只保留 prepared case、UDF 工作副本和诊断文件，未生成可用 DAT。

可用的 `fw1250` 当前结果见相邻目录 `../fw1250_rerun_8core_20260524/`。
