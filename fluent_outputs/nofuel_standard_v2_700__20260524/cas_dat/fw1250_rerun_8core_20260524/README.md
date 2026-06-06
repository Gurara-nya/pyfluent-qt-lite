# fw1250_rerun_8core_20260524

这是 `nofuel_standard_v2_700__20260524` 主项目内部的 `fw1250` 8 核标准 case 重算结果。该结果用于替代原始物理异常的 `fw1250` DAT，并已进入当前 `post/` 后处理统计。

## 输入

- 网格：`D:\Workshop\Mesh\d-40\codex-mesh-package\06-nofuel-standard-v2\nofuel-standard-v2-fw1250\d40-nofuel-standard-v2-fw1250-fluent.msh`
- 基准 case：`D:\Workshop\Case\DPM-cal-steady-msh-nofuel\standard-bl12um-h290um.cas.h5`
- 核数：`8`
- 迭代步数：`700`

## 文件

- CAS：`standard-bl12um-h290um-nofuel-standard-v2-fw1250-rerun2-iter700-8core.cas.h5`
- DAT：`combo-256-nofuel-standard-v2-fw1250-rerun2-iter700-8core.dat.h5`

## 校验结果

- HDF5 文件级校验：通过
- continuity residual 迭代步数：`700`
- UDM shape：`116700x60`
- fuel-wall 面积加权燃速：约 `1.609177 mm/s`
- fuel-wall 面积加权 Tsurf：约 `831.222 K`
- fuel-wall 面积加权 Gf_total：约 `1.480443 kg/m2/s`
- continuity final residual：`9.053e-05`

当前状态：`accepted`。
