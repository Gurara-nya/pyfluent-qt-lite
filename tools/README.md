# 参数扫描接口

本目录提供 **纯接口库** (`sweep.py`)，用于生成 Fluent Scheme/TUI 命令字符串。
不包含任何 Fluent 调用、文件 I/O、或后处理逻辑 —— 这些由你的外部应用自己实现。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    你的外部应用 (Python)                          │
│                                                                   │
│  1. import sweep, sweep_config                                    │
│  2. combos = sweep.list_combos(sweep_config.PARAM_GRID)           │
│  3. 对每个 combo:                                                 │
│       a. cmds = sweep.get_set_combo_commands(combo)                │
│       b. reload = sweep.get_reload_command()                       │
│       c. 把 cmds + reload 发给 Fluent (PyFluent / journal / pipe) │
│       d. 控制 Fluent 迭代、导出结果                                │
│  4. 汇总所有组合的结果, 做后处理                                  │
└─────────────────────────────────────────────────────────────────┘
        │                                    ▲
        │ Scheme/TUI 命令 (str)              │ 结果 (你自己定义格式)
        ▼                                    │
┌─────────────────────────────────────────────────────────────────┐
│                         Fluent 求解器                             │
│                                                                   │
│  rpvar 'udf/sweep-active' = 1                                     │
│  rpvar 'udf/a-ent'        = 当前组合值                            │
│  rpvar 'udf/lambda-ent'   = ...                                   │
│  rpvar 'udf/theta-ent'    = ...                                   │
│  rpvar 'udf/evap-a'       = ...                                   │
│  rpvar 'udf/evap-ea'      = ...                                   │
│                                                                   │
│  on-demand "Reload_Sweep_Params::libudf"                          │
│       ↓                                                           │
│  UDF 全局缓存更新:                                                │
│    g_A_ent, g_lambda_ent, g_theta_ent, g_evap_A, g_evap_Ea       │
│       ↓                                                           │
│  热路径 (kinetics.c / surface_solver.c) 立刻使用新参数             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 工作流程 (详细步骤)

### 第零步: 编译 UDF (只需做一次)

把 `sweep_params.c` 加入编译列表。编译出的 `libudf` 对所有参数组合通用，
**不需要为每组参数重新编译**。

```
编译文件列表:
  udf_main.c kinetics.c enthalpy.c mass_flow_axial.c
  surface_solver.c sources.c dpm_paraffin.c grid_motion.c sweep_params.c
```

### 第一步: 创建 rpvar (整个扫描只做一次)

```python
import sweep, sweep_config

# 生成幂等的 rpvar 创建命令
define_cmds = sweep.get_define_rpvar_commands(sweep_config.PARAM_GRID)
# -> ['(if (not (rp-var-object ...)) (rp-var-define ...))', ...]

for cmd in define_cmds:
    fluent.execute_tui(cmd)  # 或写入 journal
```

这一步会在 Fluent session 里注册 6 个 rpvar（含 sentinel）。
**多次执行不会报错**（幂等设计）。

### 第二步: 获取全部参数组合

```python
combos = sweep.list_combos(sweep_config.PARAM_GRID)
# -> [{"udf/a-ent": 5e-13, "udf/lambda-ent": 1.3, ...}, ...]

print(f"共 {len(combos)} 个组合")
```

### 第三步: 对每个组合，设置参数 + 刷新 UDF

```python
for i, combo in enumerate(combos):
    # (a) 生成设值命令
    set_cmds = sweep.get_set_combo_commands(combo)
    # -> ["(rpsetvar 'udf/sweep-active 1.0)",
    #     "(rpsetvar 'udf/a-ent 5.000000000e-13)",
    #     ...]

    # (b) 发给 Fluent
    for cmd in set_cmds:
        fluent.execute_tui(cmd)

    # (c) 让 UDF 重新读取 rpvar 到全局缓存
    fluent.execute_tui(sweep.get_reload_command())

    # (d) 你的外部逻辑: 初始化、迭代、导出结果...
    fluent.execute_tui('/solve/initialize/hyb-initialization')
    fluent.execute_tui('/solve/iterate 2000')
    fluent.execute_tui(f'/file/write-data "combo-{i:03d}.dat.h5" yes')
```

### 第四步 (可选): 验证参数是否生效

```python
fluent.execute_tui(sweep.get_print_command())
# Fluent 控制台会输出:
#   [sweep] A_ent     = 5.000000e-13
#   [sweep] lambda    = 1.300000
#   [sweep] theta     = 1.300000
#   [sweep] fast_path = no (lambda==theta==1.5)
#   [sweep] evap_A    = 2.678100e+02
#   [sweep] evap_Ea   = 1.256040e+05 J/mol
```

---

## UDF 侧 rpvar 机制详解

### 为什么用 rpvar 而不是重编译?

| 方案 | 优点 | 缺点 |
|------|------|------|
| 改 `#define` 重编译 | 简单 | 每组 ~30s 编译; 需要 Fluent 重启; Windows 路径问题 |
| **rpvar + 全局缓存** | 一次编译; 不重启; 热切换 | 需要 on-demand 触发刷新 |

### rpvar 生命周期

1. **创建**: `(rp-var-define 'udf/a-ent 0.0 'real #f)` — 在 Fluent session 里
   注册一个名为 `udf/a-ent`、类型 real、默认值 0 的变量。保存 case 时会持久化。
2. **设值**: `(rpsetvar 'udf/a-ent 1e-12)` — 立刻生效（只改了 Fluent 端的存储）。
3. **UDF 读取**: UDF 侧通过 `RP_Get_Real("udf/a-ent")` 读取当前值。
4. **缓存刷新**: `Reload_Sweep_Params` on-demand 被触发时，UDF 把所有 rpvar
   读到 `g_A_ent` 等全局变量。热路径只读全局，**不每次都调用 RP_Get_Real**。

### sentinel 机制 (`udf/sweep-active`)

- `= 0` (默认): UDF 忽略所有 rpvar，使用 `properties.h` 的编译期默认值。
  → 你的 baseline case 完全不受影响。
- `= 1`: UDF 读取 rpvar 覆盖全局缓存。
  → 进入扫描模式。

### 全局缓存变量 (sweep_params.h)

```c
extern real g_A_ent;            // <- rpvar 'udf/a-ent'
extern real g_lambda_ent;       // <- rpvar 'udf/lambda-ent'
extern real g_theta_ent;        // <- rpvar 'udf/theta-ent'
extern real g_evap_A;           // <- rpvar 'udf/evap-a'
extern real g_evap_Ea;          // <- rpvar 'udf/evap-ea'
extern int  g_use_fast_ent_path;// 派生: lambda==theta==1.5 时 = 1
```

热路径读这些全局变量的开销 = 读一个普通 C 变量，与之前读 `#define` 完全等价。

---

## API 参考

### `sweep.list_combos(param_grid) -> list[dict]`

对参数网格做笛卡尔积。

**输入**: `{"udf/a-ent": [1e-12, 2e-12], "udf/lambda-ent": [1.3, 1.5]}`
**输出**: `[{"udf/a-ent": 1e-12, "udf/lambda-ent": 1.3}, ...]` (4 个组合)

---

### `sweep.get_define_rpvar_commands(param_grid) -> list[str]`

生成**幂等**的 rpvar 创建命令 (Scheme)。整个扫描只需执行一次。

**输出示例**:
```scheme
(if (not (rp-var-object 'udf/sweep-active)) (rp-var-define 'udf/sweep-active 0.0 'real #f))
(if (not (rp-var-object 'udf/a-ent)) (rp-var-define 'udf/a-ent 0.0 'real #f))
...
```

---

### `sweep.get_set_combo_commands(combo) -> list[str]`

激活 sentinel + 设置一个组合的参数值。

**输入**: `{"udf/a-ent": 5e-13, "udf/lambda-ent": 1.5, ...}`
**输出**:
```scheme
(rpsetvar 'udf/sweep-active 1.0)
(rpsetvar 'udf/a-ent 5.000000000e-13)
(rpsetvar 'udf/lambda-ent 1.500000000e+00)
...
```

---

### `sweep.get_reload_command() -> str`

让 UDF 从 rpvar 刷新全局缓存。**每次改完参数后必须调用**。

**输出**:
```
/define/user-defined/execute-on-demand "Reload_Sweep_Params::libudf"
```

---

### `sweep.get_print_command() -> str`

让 UDF 在 Fluent 控制台打印当前参数缓存值（验证用，不修改任何东西）。

**输出**:
```
/define/user-defined/execute-on-demand "Print_Sweep_Params::libudf"
```

---

### `sweep.combo_label(index) -> str`

生成标准标签: `"combo-004"`

---

### `sweep.combo_summary(combo) -> str`

格式化单行摘要: `"udf/a-ent=5e-13, udf/lambda-ent=1.5, ..."`

---

## 在外部应用中的集成示例

### 用 PyFluent

```python
import ansys.fluent.core as pyfluent
import sweep, sweep_config

solver = pyfluent.launch_fluent(dimension=2, precision="double")
solver.file.read(file_type="case", file_name="baseline.cas.h5")

# 一次性创建 rpvar
for cmd in sweep.get_define_rpvar_commands(sweep_config.PARAM_GRID):
    solver.execute_tui(cmd)

combos = sweep.list_combos(sweep_config.PARAM_GRID)
for i, combo in enumerate(combos):
    # 设置参数
    for cmd in sweep.get_set_combo_commands(combo):
        solver.execute_tui(cmd)
    solver.execute_tui(sweep.get_reload_command())

    # 求解
    solver.solution.initialization.hybrid_initialize()
    solver.execute_tui('/define/user-defined/execute-on-demand "Use_Warmup_Sources::libudf"')
    solver.solution.run_calculation.iterate(iter_count=500)
    solver.execute_tui('/define/user-defined/execute-on-demand "Use_Dynamic_Sources::libudf"')
    solver.solution.run_calculation.iterate(iter_count=2000)

    # 导出
    solver.file.write(file_type="data", file_name=f"combo-{i:03d}.dat.h5")

solver.exit()
```

### 用 Journal 文件

```python
import sweep, sweep_config

combos = sweep.list_combos(sweep_config.PARAM_GRID)
with open("sweep_all.jou", "w") as f:
    # rpvar 定义
    for cmd in sweep.get_define_rpvar_commands(sweep_config.PARAM_GRID):
        f.write(cmd + "\n")

    for i, combo in enumerate(combos):
        f.write(f"\n;; ---- combo {i:03d}: {sweep.combo_summary(combo)} ----\n")
        for cmd in sweep.get_set_combo_commands(combo):
            f.write(cmd + "\n")
        f.write(sweep.get_reload_command() + "\n")
        f.write("/solve/initialize/hyb-initialization\n")
        f.write("/solve/iterate 2000\n")
        f.write(f'/file/write-data "combo-{i:03d}.dat.h5" yes\n')

    f.write("exit\nyes\n")
```

然后: `fluent 2ddp -g -hidden -t4 -i sweep_all.jou`

### 用 subprocess pipe

```python
import subprocess, sweep, sweep_config

proc = subprocess.Popen(
    ["fluent", "2ddp", "-g", "-hidden"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
)

def send(cmd):
    proc.stdin.write(cmd + "\n")
    proc.stdin.flush()

send('/file/read-case "baseline.cas.h5"')
for cmd in sweep.get_define_rpvar_commands(sweep_config.PARAM_GRID):
    send(cmd)

for i, combo in enumerate(sweep.list_combos(sweep_config.PARAM_GRID)):
    for cmd in sweep.get_set_combo_commands(combo):
        send(cmd)
    send(sweep.get_reload_command())
    send("/solve/iterate 2000")
    send(f'/file/write-data "combo-{i:03d}.dat.h5" yes')

send("exit")
send("yes")
proc.wait()
```

---

## 参数默认值 (未启用扫描时)

| rpvar | UDF 默认值 | 物理含义 |
|-------|-----------|----------|
| `udf/a-ent` | 1.0e-12 | 夹带模型前系数 A |
| `udf/lambda-ent` | 1.5 | 夹带指数 λ (G 的幂次的一半) |
| `udf/theta-ent` | 1.5 | 夹带指数 θ (r 的幂次) |
| `udf/evap-a` | 267.81 | 石蜡蒸发 Arrhenius 前指数 (= 0.1 × 2678.1) |
| `udf/evap-ea` | 125604.0 | 石蜡蒸发激活能 (J/mol) |

---

## 注意事项

1. **执行顺序很重要**: `get_define_rpvar_commands` → `get_set_combo_commands` → `get_reload_command()`。跳过任何一步都会导致参数不生效。

2. **笛卡尔积爆炸**: 5 参数各取 3 值 = 243 组合。先用 `list_combos` + `len()` 确认数量合理。

3. **同一 Fluent session 内切换参数**: 只需重新 `get_set_combo_commands` + `get_reload_command`，不需要重启 Fluent 或重载 UDF library。

4. **与手动 GUI 操作共存**: 在 GUI 里 initialize 和 iterate 正常操作，参数扫描机制不干涉 Fluent 的任何其他设置。

5. **保存 case 会持久化 rpvar**: 如果你 write-case 后 read-case，之前设的 rpvar 值会恢复。如果不想受上一次扫描残留影响，每次组合前都执行一遍 `get_set_combo_commands` 即可（已是幂等的）。
