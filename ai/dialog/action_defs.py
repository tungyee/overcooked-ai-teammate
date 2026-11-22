# -*- coding: utf-8 -*-
"""动作定义与作用域编译（spec §5.1 / §7.6）。

本模块是「动作」的单一来源，供分工（set_division）与命令（execute_actions）
共用：

- 动作名（中英文）+ 动作 → 站点类型；
- `DIVISION_TASK_TYPES`：动作 → 「这一步」task TYPE（= 目标步），既用于分工
  scope，也用于命令 scope 的目标步（命令 scope 从它派生上游前缀）；
- `COMMAND_UPSTREAM`：命令里哪些动作自动补上游前缀（切/下锅/拌）；
- `DIVISION_ACTIONS`：可分工动作（送餐/洗盘/装盘谁近谁做，不在其中）。

本模块纯数据 + 纯函数，不 import `ai.tasks`（避免反向依赖）；task TYPE 用
字符串字面量写死，由 `tests/test_actions.py::test_action_partition_covers_all_task_types`
钉住「映射恰好覆盖全部 TASK_TYPES、无重叠、无遗漏」。
"""
from typing import Any, Dict, FrozenSet, Iterable, Optional, Tuple

# 动作 → 「这一步」task TYPE（= 目标步）。分工 scope 和命令 scope 的目标步
# 都从这里取；命令 scope 对加工动作（切/下锅/拌）再自动补上游前缀。
DIVISION_TASK_TYPES = {
    "切": ("Chop",),
    # 「下锅」= 把料送进灶：含 FetchToCooker（取料下锅这一步）。
    "下锅": ("FetchToCooker", "FillCooker", "PlaceCarrierInCooker"),
    "拌": ("Mix",),
    "装盘": ("FetchToPlate", "TakeCookedToPlate", "PlaceCleanPlate"),
    "送餐": ("DeliverPlate",),
    "洗盘": ("WashPlate",),
    "按开关": ("ReceiveConveyor",),
}  # type: Dict[str, Tuple[str, ...]]

# 命令里「自动补上游前缀」的加工动作：切黄瓜前先取料上砧板，下锅前先切。
# 收尾动作（装盘/送餐/洗盘/按开关）不补上游——料已经备好 / 盘已经装好。
COMMAND_UPSTREAM = frozenset(("切", "下锅", "拌"))

# 取料/搬运：planner 按料源可达性自动归位，不进 LLM 枚举。
FETCH_TASK_TYPES = ("FetchToBoard", "FetchToCarrier", "FillCarrier",
                    "Prefetch")  # type: Tuple[str, ...]

# 会「吃进搬运步」的加工目标步：这些步要把料搬到本站才算完成，分工 scope
# 要把喂料它的搬运步一起算进去（切→取料上砧板、拌→取料到混合站）。复合搬运
# 步（FetchToCooker / FetchToPlate）不在此列——它们本身就是「搬运 + 下锅/装盘」，
# 上游（Chop 链）归别的分工动作，不能算作下锅/装盘的搬运。
CARRY_BOUNDARY_TYPES = ("Chop", "Mix", "FillCooker")  # type: Tuple[str, ...]

# auto_only / 跨边交接 / 救援：不开放认领。
OTHER_TASK_TYPES = (
    "ReturnPot", "RescueCooked", "MergePlates", "SendAcross", "ThrowBatch",
    "Discard", "RecoverLoosePot", "StashHeld", "ResetPlate", "Extinguish",
    "FetchConveyorPlate",
    # 换边：布局窗口里把自己挪到两种布局都对的格，不产生菜品、不认领，
    # 不该出现在分工枚举里。
    "Reposition",
    # 5-1 开舢板过河：纯移动、不产生菜品、不认领。
    "RideRaft",
)  # type: Tuple[str, ...]

# 每个动作绑定的站点类型（frame stations[].t），供「判」做粗粒度校验
# （站点在本关存在、P2 是否够得着）。装盘/送餐都归到 plate_station（盘/出餐
# 口一侧），精确站点由 planner 每拍选。
ACTION_STATION_TYPES = {
    "切": "chopping",
    "下锅": "cooking",
    "拌": "mixing",
    "装盘": "plate_station",
    "送餐": "plate_station",
    "洗盘": "washing",
    "按开关": "switch",
}  # type: Dict[str, str]

# 工具协议里的英文动作名；只用于 LLM 可见的 schema/返回值。
ACTION_TOOL_NAMES = {
    "切": "chop",
    "下锅": "cook",
    "拌": "mix",
    "备料": "prepare",
    "装盘": "plate",
    "送餐": "deliver",
    "洗盘": "wash",
    "按开关": "press_switch",
}  # type: Dict[str, str]
TOOL_ACTION_NAMES = {name: action for action, name in ACTION_TOOL_NAMES.items()}

# 英文动作名 → 中文标签（命令返回值/播报用）。fetch/prepare 不在分工动作里。
ACTION_LABELS = {
    "chop": "切",
    "cook": "下锅",
    "mix": "拌",
    "plate": "装盘",
    "deliver": "送餐",
    "wash": "洗盘",
    "fetch": "取料",
    "prepare": "备料",
    "press_switch": "按开关",
}  # type: Dict[str, str]

# 可分工动作：切/下锅/拌/备料。备料是「物料级整链」（取→切→下锅→装盘），
# 必须带 item；送餐/洗盘/装盘谁近谁做，交给 planner 自由选。
DIVISION_ACTIONS = ("切", "下锅", "拌", "备料")  # type: Tuple[str, ...]

_TASK_TO_ACTION = {}  # type: Dict[str, str]
for _action, _types in DIVISION_TASK_TYPES.items():
    for _t in _types:
        _TASK_TO_ACTION[_t] = _action


def task_action(task_type):
    # type: (str) -> Optional[str]
    """task TYPE → 所属动作；取料/交接/救援（不在 DIVISION_TASK_TYPES）返回 None。"""
    return _TASK_TO_ACTION.get(str(task_type))


def action_scope(action, item=None, carry=None):
    # type: (str, Optional[str], Optional[Iterable[str]]) -> FrozenSet[Tuple[Optional[str], Optional[str]]]
    """动作 → 作用域。`item` 为 None 时是动作级 `{(type, None)}`，否则精确到
    节点 `{(type, item.lower())}`。`carry` 是要一起算进来的搬运步类型
    （DAG 派生，见 `input_carry_map`），和动作本身的 item 同口径。"""
    types = DIVISION_TASK_TYPES[action]
    if carry:
        types = types + tuple(t for t in carry if t not in types)
    if item is None:
        return frozenset((t, None) for t in types)
    item_l = str(item).lower()
    return frozenset((t, item_l) for t in types)


def input_carry_map(dag_nodes):
    # type: (Optional[Iterable[Dict[str, Any]]]) -> Dict[str, FrozenSet[str]]
    """从配方 DAG 派生「加工步 → 喂料它的搬运步」（分工 scope 用）。

    与命令侧的 `build_scope` 同源（都读 DAG），但展开深度不同：命令取「到
    目标步为止的完整前缀」，分工只取「喂进目标步的那一层搬运步」。搬运步
    （FETCH_TASK_TYPES）归给离它最近的真·加工步（CARRY_BOUNDARY_TYPES）；
    复合搬运步（FetchToCooker 等）不算边界，所以它子树里的 FetchToBoard
    归给 Chop（切），不归给下锅。

    `dag_nodes` 是 recipe_graph 编译出的 `{type, item, children}` 树根
    （如 `Kitchen.dags.values()`）。返回 {加工步 type: frozenset(搬运步 type)}。
    """
    result = {}  # type: Dict[str, set]

    def walk(node, feeding):
        # type: (Dict[str, Any], Optional[str]) -> None
        task_type = node.get("type")
        if task_type in CARRY_BOUNDARY_TYPES:
            feeding = task_type
        elif task_type in FETCH_TASK_TYPES and feeding is not None:
            result.setdefault(feeding, set()).add(task_type)
            return  # 搬运步是叶子，不往下钻
        for child in node.get("children") or ():
            if isinstance(child, dict):
                walk(child, feeding)

    for root in dag_nodes or ():
        if isinstance(root, dict):
            walk(root, None)
    return {k: frozenset(v) for k, v in result.items()}


def carry_for(goal_types, carry_map):
    # type: (Iterable[str], Optional[Dict[str, FrozenSet[str]]]) -> FrozenSet[str]
    """某个动作的目标步 → 要补进分工 scope 的搬运步类型（并集）。"""
    carry = set()  # type: set
    for goal in goal_types:
        carry |= set((carry_map or {}).get(goal, ()))
    return frozenset(carry)
