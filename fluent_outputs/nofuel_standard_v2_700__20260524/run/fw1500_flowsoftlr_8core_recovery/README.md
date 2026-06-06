# fw1500_flowsoftlr_8core_recovery

这是 `nofuel_standard_v2_700__20260524` 主项目内部的 `fw1500` 补算记录，日期为 2026-05-24。该补算用于补齐主批处理中失败的 `nofuel-standard-v2-fw1500` 700 步 DAT。

## 背景

主项目的 16 核批处理在 `fw1500` 上连续 3 次于 `/solve/iterate` 期间断开，未生成有效 DAT。为判断并绕开稳定性问题，本次补算改用 nofuel 网格包说明中匹配的 `standard-bl12um-h290um-flowsoft-lr.cas.h5` 基准 case，并将核数降为 8。

## 文件位置

- 补算 CAS/DAT：`../../cas_dat/fw1500_flowsoftlr_8core_recovery/`
- runner state：`fw1500_flowsoftlr_probe_8core_state.json`
- Fluent 日志：`fw1500_flowsoftlr_probe_8core_fluent.log`
- stdout/stderr：`fw1500_flowsoftlr_probe_8core_stdout.log`、`fw1500_flowsoftlr_probe_8core_stderr.log`

## 输入

- 网格：`D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1500\d40-nofuel-standard-v2-fw1500-fluent.msh`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um-flowsoft-lr.cas.h5`
- 迭代步数：`700`
- 核数：`8`

## 结果

- DAT：`../../cas_dat/fw1500_flowsoftlr_8core_recovery/combo-256-nofuel-standard-v2-fw1500-flowsoftlr-probe-iter700-8core.dat.h5`
- 文件级校验：HDF5 可读，continuity residual 迭代步数为 `700`，UDM shape 为 `116700x60`。

该结果已经作为 `nofuel_standard_v2_700__20260524` 的 `fw1500` 有效覆盖结果归档。
