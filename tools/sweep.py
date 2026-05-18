"""
sweep.py
--------
参数扫描接口库. 本模块只提供数据生成函数, 不调用 Fluent、不生成文件、
不做 I/O. 外部应用 (PyFluent / journal 生成器 / 自动化脚本) 导入本模块
后, 按需调用下列接口:

    list_combos(param_grid) -> list[dict]
    get_define_rpvar_commands(param_grid) -> list[str]
    get_set_combo_commands(combo) -> list[str]
    get_reload_command() -> str
    get_print_command() -> str

所有返回的 str 都是 **Fluent TUI / Scheme 命令**, 你的外部应用直接发给
Fluent 即可 (无论是通过 PyFluent session.execute_tui(), journal 文件,
还是 Fluent 的 batch stdin pipe).

示例:
    import sweep, sweep_config
    combos = sweep.list_combos(sweep_config.PARAM_GRID)
    for combo in combos:
        cmds = sweep.get_set_combo_commands(combo)
        # ... 通过 PyFluent 或其他方式逐条发送给 Fluent ...
"""
from __future__ import annotations

import itertools
from typing import Dict, List


# =====================================================================
# 公开接口
# =====================================================================


def list_combos(param_grid: Dict[str, List[float]]) -> List[Dict[str, float]]:
    """
    对 param_grid 做笛卡尔积, 返回全部参数组合.

    参数:
        param_grid: 键为 rpvar 名, 值为该参数要尝试的数值列表.
                    例: {"udf/a-ent": [1e-12, 2e-12], "udf/lambda-ent": [1.3, 1.5]}

    返回:
        list of dict, 每个 dict 是一次仿真运行对应的参数组合.
        例: [{"udf/a-ent": 1e-12, "udf/lambda-ent": 1.3},
             {"udf/a-ent": 1e-12, "udf/lambda-ent": 1.5},
             {"udf/a-ent": 2e-12, "udf/lambda-ent": 1.3},
             {"udf/a-ent": 2e-12, "udf/lambda-ent": 1.5}]

    说明:
        - 按 key 字典序排列, 保证组合顺序可复现.
        - 总组合数 = 各参数取值数之积 (笛卡尔积).
    """
    keys = sorted(param_grid.keys())
    value_lists = [param_grid[k] for k in keys]
    combos = []
    for values in itertools.product(*value_lists):
        combos.append(dict(zip(keys, values)))
    return combos


def get_define_rpvar_commands(param_grid: Dict[str, List[float]]) -> List[str]:
    """
    生成 Fluent Scheme 命令列表, 用于幂等地创建所有 rpvar (含 sentinel).

    参数:
        param_grid: 与 list_combos() 相同.

    返回:
        list of str, 每个元素是一条完整的 Scheme 表达式, 可直接发给 Fluent.

    说明:
        - 这些命令只需要在整个扫描流程开始前执行一次.
        - 使用 make-new-fl-rpvar 注册 solver 可见的 rpvar; 多次执行不会破坏已有值.
        - 包含 sentinel 'udf/sweep-active', 初始值 0 (未激活).
        - 对每个参数创建对应的 rpvar, 默认值 0.

    示例输出:
        [
            "(make-new-fl-rpvar 'udf/sweep-active 0.0 'real)",
            "(make-new-fl-rpvar 'udf/a-ent 0.0 'real)",
            ...
        ]
    """
    cmds = []
    # Use Fluent's solver-side rpvar creator unconditionally.  A case can
    # contain an rp-var-object that PyFluent can read while the UDF-side
    # RP_Variable_Exists_P still returns false; guarding with rp-var-object
    # would preserve that broken state.
    cmds.append("(make-new-fl-rpvar 'udf/sweep-active 0.0 'real)")
    for k in sorted(param_grid.keys()):
        cmds.append(f"(make-new-fl-rpvar '{k} 0.0 'real)")
    return cmds


def get_set_combo_commands(combo: Dict[str, float]) -> List[str]:
    """
    生成 Fluent Scheme 命令列表, 用于激活扫描 + 设置当前参数组合.

    参数:
        combo: 一个参数组合 dict, 由 list_combos() 返回.
               例: {"udf/a-ent": 1e-12, "udf/lambda-ent": 1.5, ...}

    返回:
        list of str, 包含:
          1. 激活 sentinel: (rpsetvar 'udf/sweep-active 1.0)
          2. 逐参数设值:    (rpsetvar 'udf/a-ent 1.000000000e-12)
          ...

    说明:
        - 执行完本列表后, 必须再调用 get_reload_command() 让 UDF 重新读取.
        - 数值用 %.9e 格式以避免浮点精度丢失.

    示例输出:
        [
            "(rpsetvar 'udf/sweep-active 1.0)",
            "(rpsetvar 'udf/a-ent 1.000000000e-12)",
            "(rpsetvar 'udf/lambda-ent 1.500000000e+00)",
            ...
        ]
    """
    cmds = ["(rpsetvar 'udf/sweep-active 1.0)"]
    for k, v in sorted(combo.items()):
        cmds.append(f"(rpsetvar '{k} {v:.9e})")
    return cmds


def get_reload_command() -> str:
    """
    返回让 UDF 重新从 rpvar 读取参数的 Fluent TUI 命令.

    说明:
        - 对应 UDF 侧 DEFINE_ON_DEMAND(Reload_Sweep_Params).
        - 执行后 UDF 会把当前 rpvar 值缓存到全局变量, 热路径立刻生效.
        - 同时会在 Fluent 控制台打印当前参数值 (便于日志确认).

    返回:
        str, 一条 Fluent TUI 命令.

    示例输出:
        '/define/user-defined/execute-on-demand "Reload_Sweep_Params::libudf"'
    """
    return '/define/user-defined/execute-on-demand "Reload_Sweep_Params::libudf"'


def get_print_command() -> str:
    """
    返回让 UDF 打印当前缓存参数值的 Fluent TUI 命令.

    说明:
        - 对应 UDF 侧 DEFINE_ON_DEMAND(Print_Sweep_Params).
        - 不修改任何值, 只打印到 Fluent 控制台/日志.
        - 输出格式:
            [sweep] A_ent     = 1.000000e-12
            [sweep] lambda    = 1.500000
            [sweep] theta     = 1.500000
            [sweep] fast_path = yes (lambda==theta==1.5)
            [sweep] evap_A    = 2.678100e+02
            [sweep] evap_Ea   = 1.256040e+05 J/mol

    返回:
        str, 一条 Fluent TUI 命令.
    """
    return '/define/user-defined/execute-on-demand "Print_Sweep_Params::libudf"'


# =====================================================================
# 便利函数 (组合信息)
# =====================================================================


def combo_label(index: int) -> str:
    """生成标准化的组合标签, 例: 'combo-004'."""
    return f"combo-{index:03d}"


def combo_summary(combo: Dict[str, float]) -> str:
    """将 combo dict 格式化为可读的单行摘要, 例: 'udf/a-ent=1e-12, udf/lambda-ent=1.5'."""
    return ", ".join(f"{k}={v:g}" for k, v in sorted(combo.items()))


# =====================================================================
# CLI: python sweep.py --list
# =====================================================================

if __name__ == "__main__":
    import sweep_config
    combos = list_combos(sweep_config.PARAM_GRID)
    print(f"Total combos: {len(combos)}\n")
    for i, c in enumerate(combos):
        print(f"  {combo_label(i)}: {combo_summary(c)}")
