# -*- coding: utf-8 -*-
"""动作级作用域映射：ai/dialog/action_defs.py 的单元测试。"""
from ai import tasks as T
from ai.dialog.action_defs import (ACTION_STATION_TYPES, DIVISION_TASK_TYPES,
                               FETCH_TASK_TYPES, OTHER_TASK_TYPES, action_scope,
                               carry_for, input_carry_map)


def test_action_station_types_cover_all_actions():
    assert set(ACTION_STATION_TYPES) == set(DIVISION_TASK_TYPES)
    assert ACTION_STATION_TYPES["切"] == "chopping"
    assert ACTION_STATION_TYPES["下锅"] == "cooking"
    assert ACTION_STATION_TYPES["洗盘"] == "washing"


def test_action_partition_covers_all_task_types():
    assert set(DIVISION_TASK_TYPES) == {"切", "下锅", "拌", "装盘", "送餐", "洗盘",
                                       "按开关"}
    covered = set()
    for types in DIVISION_TASK_TYPES.values():
        covered |= set(types)
    covered |= set(FETCH_TASK_TYPES) | set(OTHER_TASK_TYPES)
    assert covered == set(T.TASK_TYPES), set(T.TASK_TYPES) - covered


def test_action_scope_without_item_is_type_level():
    assert action_scope("切") == frozenset({("Chop", None)})


def test_action_scope_with_item_is_node_level():
    assert action_scope("切", "Cucumber") == frozenset({("Chop", "cucumber")})


def test_action_scope_includes_carry():
    assert action_scope("切", carry=("FetchToBoard",)) == frozenset({
        ("Chop", None), ("FetchToBoard", None)})
    assert action_scope("切", "Cucumber", ("FetchToBoard",)) == frozenset({
        ("Chop", "cucumber"), ("FetchToBoard", "cucumber")})


def test_action_scope_carry_does_not_duplicate_goal():
    # 「下锅」目标步里已有 FetchToCooker，carry 不该重复加。
    assert action_scope("下锅", carry=("FetchToCooker",)) == frozenset({
        ("FetchToCooker", None), ("FillCooker", None),
        ("PlaceCarrierInCooker", None)})


_CHICKEN_DAG = {
    "type": "TakeCookedToPlate", "item": "FriedChickenNuggets",
    "children": [{
        "type": "FetchToCooker", "item": "FriedChickenNuggets",
        "children": [{
            "type": "Chop", "item": "NuggetChicken",
            "children": [{
                "type": "FetchToBoard", "item": "NuggetChicken", "children": [],
            }],
        }],
    }],
}

_SALAD_DAG = {
    "type": "Mix", "item": "MixedSalad",
    "children": [
        {"type": "Chop", "item": "Lettuce",
         "children": [{"type": "FetchToBoard", "item": "Lettuce", "children": []}]},
        {"type": "Chop", "item": "Tomato",
         "children": [{"type": "FetchToBoard", "item": "Tomato", "children": []}]},
    ],
}


def test_input_carry_map_attributes_fetch_to_chop():
    assert input_carry_map([_CHICKEN_DAG]) == {
        "Chop": frozenset({"FetchToBoard"})}


def test_input_carry_map_does_not_steal_carry_for_mix():
    # 拌的组件是切菜步取来的：FetchToBoard 归 Chop，不归 Mix。
    assert input_carry_map([_SALAD_DAG]) == {
        "Chop": frozenset({"FetchToBoard"})}


def test_carry_for_union():
    carry_map = {"Chop": frozenset({"FetchToBoard"})}
    assert carry_for(("Chop",), carry_map) == frozenset({"FetchToBoard"})
    assert carry_for(("FetchToCooker",), carry_map) == frozenset()
    assert carry_for((), carry_map) == frozenset()
    assert carry_for(("Chop",), None) == frozenset()
