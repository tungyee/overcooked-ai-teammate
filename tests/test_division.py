# -*- coding: utf8 -*-
"""分工表：写入、清空、planner 偏好与动态签名。"""
from types import SimpleNamespace

from ai.dialog import division as D
from ai.dialog.schema import preference_matches_task


def _task(task_type, item):
    # type: (str, str) -> SimpleNamespace
    return SimpleNamespace(TYPE=task_type, item=item)


def test_you_gets_no_bonus():
    """分给你的动作不加分：只靠「别抢玩家的活」来分工。

    加分会让自己的活压过更值钱但没分工的事（组装/送餐/救锅）——真机
    trace-20261109-124818 里 55% 的时间都在切菜，披萨组装不起来。
    """
    state = D.DivisionState()
    assert state.set("切", D.OWNER_YOU)
    assert state.preferences() == []


def test_set_item_level_and_claim():
    state = D.DivisionState()
    assert state.set("切", D.OWNER_PLAYER, "Meat")
    pref = state.preferences()[0]
    assert pref.kind == "claim"
    assert pref.weight == D.WEIGHT_CLAIM
    assert pref.scope == frozenset({("Chop", "meat")})


def test_preferences_with_carry_map_expands_fetch():
    """「切 → player」要连取料上砧板（FetchToBoard）一起扣分。"""
    state = D.DivisionState()
    state.set("切", D.OWNER_PLAYER, "Meat")
    carry_map = {"Chop": frozenset({"FetchToBoard"})}
    pref = state.preferences(carry_map)[0]
    assert pref.scope == frozenset({("Chop", "meat"), ("FetchToBoard", "meat")})


def test_preferences_without_carry_map_is_goal_only():
    """不传 carry_map（派生失败 / 旧调用）时退回只扣目标步，不破坏行为。"""
    state = D.DivisionState()
    state.set("切", D.OWNER_PLAYER, "Meat")
    pref = state.preferences()[0]
    assert pref.scope == frozenset({("Chop", "meat")})


def test_generic_does_not_override_specific_owner():
    """specific 覆盖 generic：泛化「切→player」不该误扣具体归 AI 的土豆，
    也不该和具体归 player 的鸡块重复扣。"""
    state = D.DivisionState()
    state.set("切", D.OWNER_PLAYER)                    # 泛化
    state.set("切", D.OWNER_YOU, "Potato")             # 土豆归 AI
    state.set("切", D.OWNER_PLAYER, "NuggetChicken")   # 鸡块归玩家（具体）
    prefs = state.preferences()

    # 土豆是 AI 的活：不命中任何负偏好
    assert not any(preference_matches_task(p, _task("Chop", "Potato"))
                   for p in prefs)
    # 鸡块命中恰好一条，只 -6.0（不叠成 -12）
    chicken = [p for p in prefs
               if preference_matches_task(p, _task("Chop", "NuggetChicken"))]
    assert len(chicken) == 1
    assert chicken[0].weight == D.WEIGHT_CLAIM
    # 其它料（生菜）由泛化兜底
    lettuce = [p for p in prefs
               if preference_matches_task(p, _task("Chop", "Lettuce"))]
    assert len(lettuce) == 1
    assert lettuce[0].weight == D.WEIGHT_CLAIM


def test_generic_exclude_also_covers_carry():
    """泛化「切→player」的 exclude 要连取料上砧板一起扣掉（carry 同 item 口径）。"""
    state = D.DivisionState()
    state.set("切", D.OWNER_PLAYER)
    state.set("切", D.OWNER_YOU, "Potato")
    carry_map = {"Chop": frozenset({"FetchToBoard"})}
    prefs = state.preferences(carry_map)

    # 土豆的取料也归 AI，不命中
    assert not any(preference_matches_task(p, _task("FetchToBoard", "Potato"))
                   for p in prefs)
    # 其它料的取料仍被泛化扣分
    assert any(preference_matches_task(p, _task("FetchToBoard", "NuggetChicken"))
               for p in prefs)


def test_both_has_no_preference():
    state = D.DivisionState()
    state.set("装盘", D.OWNER_BOTH)
    assert state.preferences() == []
    assert state.snapshot()["both"] == ["plate"]


def _chicken_scope_ctx():
    steps = frozenset({
        ("FetchToBoard", "nuggetchicken"),
        ("Chop", "nuggetchicken"),
        ("FetchToCooker", "friedchickennuggets"),
        ("TakeCookedToPlate", "friedchickennuggets"),
    })
    items = frozenset({"nuggetchicken", "friedchickennuggets"})
    return {"friedchickennuggets": steps}, {"friedchickennuggets": items}


def test_prepare_preference_covers_full_chain():
    """prepare（备料）→ player 的 claim scope = 该物料整链全部 steps。"""
    state = D.DivisionState()
    state.set("备料", D.OWNER_PLAYER, "FriedChickenNuggets")
    material_steps, material_items = _chicken_scope_ctx()
    prefs = state.preferences(None, material_steps, material_items)
    assert len(prefs) == 1
    assert prefs[0].scope == material_steps["friedchickennuggets"]
    assert prefs[0].exclude == frozenset()
    # 整链里的每一步都被扣
    assert preference_matches_task(prefs[0], _task("Chop", "NuggetChicken"))
    assert preference_matches_task(
        prefs[0], _task("TakeCookedToPlate", "FriedChickenNuggets"))


def test_prepare_overrides_fine_grained_actions():
    """prepare X 覆盖 chop/cook/mix 对 X 的归属：切→player 不该再扣鸡块。"""
    state = D.DivisionState()
    state.set("备料", D.OWNER_YOU, "FriedChickenNuggets")   # AI 备整条鸡块
    state.set("切", D.OWNER_PLAYER)                          # 玩家切所有
    material_steps, material_items = _chicken_scope_ctx()
    prefs = state.preferences(None, material_steps, material_items)

    # 鸡块整链（含取料/切）都不被「切→player」扣
    assert not any(preference_matches_task(p, _task("Chop", "NuggetChicken"))
                   for p in prefs)
    assert not any(preference_matches_task(p, _task("FetchToBoard", "NuggetChicken"))
                   for p in prefs)
    # 其它料的切仍由「切→player」兜底
    assert any(preference_matches_task(p, _task("Chop", "Lettuce")) for p in prefs)


def test_prepare_skips_shadowed_item_entry():
    """prepare X 接管后，chop:X 这类物料级细粒度条目直接跳过，不产生死偏好。"""
    state = D.DivisionState()
    state.set("备料", D.OWNER_YOU, "FriedChickenNuggets")   # AI 备鸡块整链
    state.set("切", D.OWNER_PLAYER)                          # 玩家切所有（泛化）
    state.set("切", D.OWNER_PLAYER, "NuggetChicken")         # 被 prepare 覆盖
    material_steps, material_items = _chicken_scope_ctx()
    prefs = state.preferences(None, material_steps, material_items)

    # 只有泛化「切→player」一条；chop:NuggetChicken 被 prepare 覆盖直接跳过。
    assert len(prefs) == 1
    # 鸡块链仍被 exclude，不误扣；其它料仍由泛化兜底。
    assert not preference_matches_task(prefs[0], _task("Chop", "NuggetChicken"))
    assert preference_matches_task(prefs[0], _task("Chop", "Lettuce"))


def test_validate_entry_prepare_requires_item_and_real_material():
    world = SimpleNamespace(stations=[{"t": "chopping"}])
    kitchen = SimpleNamespace(materials={
        "FriedChickenNuggets": SimpleNamespace(
            items={"NuggetChicken", "FriedChickenNuggets"})})

    ok, reason, _ = D.validate_entry(world, None, kitchen, None,
                                     "prepare", "you")
    assert not ok and "item" in reason

    ok, reason, _ = D.validate_entry(world, None, kitchen, None,
                                     "prepare", "you", "Chips")
    assert not ok and "没有物料" in reason

    ok, reason, _ = D.validate_entry(world, None, kitchen, None,
                                     "prepare", "you", "NuggetChicken")
    assert ok, reason


def test_overwrite_and_clear():
    state = D.DivisionState()
    state.set("切", D.OWNER_PLAYER, "Meat")
    assert state.set("切", D.OWNER_YOU, "Meat") is True
    assert len(state.entries) == 1
    assert state.preferences() == []
    assert state.clear("切", "Meat") is True
    assert state.entries == []


def test_clear_action_removes_item_entries():
    state = D.DivisionState()
    state.set("切", D.OWNER_PLAYER, "Meat")
    state.set("切", D.OWNER_YOU, "Lettuce")
    state.set("下锅", D.OWNER_PLAYER)
    assert state.clear("切") is True
    assert [e.action for e in state.entries] == ["下锅"]
    assert state.clear_all() is True
    assert state.entries == []


def test_overlapping_actions_detects_generic_plus_specific():
    state = D.DivisionState()
    assert state.overlapping_actions() == []
    state.set("切", D.OWNER_PLAYER)
    assert state.overlapping_actions() == []
    state.set("切", D.OWNER_YOU, "Potato")
    assert state.overlapping_actions() == ["chop"]
    # 清掉泛化条目后不再并存
    state.clear("切", None)
    assert state.overlapping_actions() == []


def test_diff_entries():
    old = D.DivisionState()
    old.set("下锅", D.OWNER_YOU)
    new = D.DivisionState()
    new.set("下锅", D.OWNER_PLAYER)
    new.set("装盘", D.OWNER_YOU)
    diff = D.diff_entries(old, new)
    assert {(row["action"], row["from"], row["to"]) for row in diff} == {
        ("cook", "you", "player"),
        ("plate", None, "you"),
    }


def test_tool_actions_excludes_deliver_wash_and_missing_stations():
    stations = [
        {"t": "chopping"}, {"t": "cooking"}, {"t": "plate_station"},
        {"t": "washing"},
    ]
    # 没有 mixing 站 → mix 不进；prepare（物料级整链）不绑站点，恒常驻。
    assert D.tool_actions(stations) == ["chop", "cook", "prepare"]


def test_station_signature_changes_only_when_stations_move():
    a = SimpleNamespace(stations=[
        {"t": "chopping", "grid": "G", "gx": 1, "gz": 2, "x": 1.2, "z": 2.4},
        {"t": "cooking", "grid": "G", "gx": 3, "gz": 4, "x": 3.6, "z": 4.8},
    ])
    b = SimpleNamespace(stations=[
        {"t": "chopping", "grid": "G", "gx": 1, "gz": 2, "x": 1.2, "z": 2.4},
        {"t": "cooking", "grid": "G", "gx": 3, "gz": 4, "x": 3.6, "z": 4.8},
    ])
    c = SimpleNamespace(stations=[
        {"t": "chopping", "grid": "G", "gx": 1, "gz": 2, "x": 1.2, "z": 2.4},
        {"t": "cooking", "grid": "G", "gx": 9, "gz": 4, "x": 10.8, "z": 4.8},
    ])
    assert D.station_signature(a) == D.station_signature(b)
    assert D.station_signature(a) != D.station_signature(c)


def test_station_signature_ignores_world_coords_on_moving_grid():
    """木筏巡航会让 cooking 站点的 x/z 每帧变化；局部 gx/gz 没变就不该复核。"""
    raw = {"grids": [{"id": "MovingRaft", "moving": True}]}
    a = SimpleNamespace(raw=raw, stations=[
        {"t": "cooking", "grid": "MovingRaft", "gx": 1, "gz": 2,
         "x": -8.0, "z": 2.4},
    ])
    b = SimpleNamespace(raw=raw, stations=[
        {"t": "cooking", "grid": "MovingRaft", "gx": 1, "gz": 2,
         "x": -6.0, "z": 2.4},
    ])
    assert D.station_signature(a) == D.station_signature(b)


def test_station_signature_detects_local_move_on_moving_grid():
    """木筏上的站点真的换了局部格，仍要触发复核。"""
    raw = {"grids": [{"id": "MovingRaft", "moving": True}]}
    a = SimpleNamespace(raw=raw, stations=[
        {"t": "cooking", "grid": "MovingRaft", "gx": 1, "gz": 2,
         "x": -8.0, "z": 2.4},
    ])
    b = SimpleNamespace(raw=raw, stations=[
        {"t": "cooking", "grid": "MovingRaft", "gx": 2, "gz": 2,
         "x": -6.8, "z": 2.4},
    ])
    assert D.station_signature(a) != D.station_signature(b)


def test_validate_entry_rejects_unknown_action_and_owner():
    world = SimpleNamespace(stations=[{"t": "chopping"}])
    ok, reason, _ = D.validate_entry(world, None, None, None,
                                     "deliver", "you")
    assert not ok and "不开放" in reason
    ok, reason, _ = D.validate_entry(world, None, None, None,
                                     "chop", "P1")
    assert not ok and "owner" in reason


def test_validate_entry_rejects_non_choppable_item(monkeypatch):
    world = SimpleNamespace(stations=[{"t": "chopping"}])
    kitchen = SimpleNamespace(materials={"Bun": SimpleNamespace(items={"Bun"})})

    class Book(object):
        @staticmethod
        def needs_chopping(item):
            return item.lower() != "bun"

    ok, reason, _ = D.validate_entry(world, None, kitchen, Book(),
                                     "chop", "you", "Bun")
    assert not ok and "不需要切" in reason


def test_validate_entry_warns_when_temporarily_unreachable(monkeypatch):
    import ai.dialog.help as help_mod
    monkeypatch.setattr(help_mod, "reachable_actions", lambda *a, **k: [])
    world = SimpleNamespace(stations=[{"t": "cooking"}])
    ok, reason, warning = D.validate_entry(world, None, None, None,
                                           "cook", "you")
    assert ok and not reason and "够不着" in warning


def test_reach_signature_uses_cost_to(monkeypatch):
    import ai.dialog.help as help_mod
    calls = []

    def fake_cost_to(world, bb, name, station):
        calls.append((name, station["t"]))
        return 0 if name == "Player 2" else None

    monkeypatch.setattr(help_mod, "cost_to", fake_cost_to)
    world = SimpleNamespace(stations=[{"t": "chopping"}, {"t": "cooking"}])
    assert D.reach_signature(world, None) == (
        ("下锅", False, True),
        ("切", False, True),
    )
    assert calls


def test_station_signature_ignores_moving_serving_hatch():
    """3-5 的出餐口挂在移动出餐船上，grid=null；它不该参与分工复核签名。"""
    raw = {"grids": [{"id": "MovingRaft", "moving": True}]}
    a = SimpleNamespace(raw=raw, stations=[
        {"t": "plate_station", "grid": None, "gx": -1, "gz": 8,
         "x": 8.0, "z": 9.0},
    ])
    b = SimpleNamespace(raw=raw, stations=[
        {"t": "plate_station", "grid": None, "gx": -3, "gz": 7,
         "x": 5.0, "z": 8.0},
    ])
    assert D.station_signature(a) == D.station_signature(b)


def test_rapids35_fixture_station_signature_is_stable():
    """真实 3-5 三帧：木筏和出餐船都在动，分工签名不应变。"""
    import gzip
    import json
    import os
    from ai.state.world import World

    path = os.path.join(os.path.dirname(__file__), "fixtures", "rapids",
                        "rapids35-20261101-180609-deliver.ndjson.gz")
    with gzip.open(path, "rt", encoding="utf8") as fh:
        frames = [json.loads(line) for line in fh if line.strip()]
    sigs = {D.station_signature(World(f)) for f in frames[:3]}
    assert len(sigs) == 1


def test_validate_entry_knows_crates_outside_current_orders(monkeypatch):
    """订单只刷到沙拉时，玩家那侧的土豆/鸡块料箱仍要能认领。

    voice-20261110-221304：ChickenOnly + Salad 开局，模型写 Potato/Chicken，
    校验只看当前订单 DAG，把土豆也报成「本关没有物料」。
    """
    import ai.dialog.help as help_mod
    monkeypatch.setattr(help_mod, "reachable_actions", lambda *a, **k: ["切"])
    world = SimpleNamespace(stations=[
        {"t": "chopping"},
        {"t": "crate", "ing": "Potato"},
        {"t": "crate", "ing": "NuggetChicken"},
        {"t": "crate", "ing": "Lettuce"},
    ])
    # 当前订单只有沙拉：DAG 里没有土豆/鸡块
    kitchen = SimpleNamespace(materials={"Lettuce": SimpleNamespace(items={"Lettuce"})})

    class Book(object):
        @staticmethod
        def needs_chopping(item):
            return item.lower() in ("potato", "nuggetchicken")

    for item in ("Potato", "NuggetChicken"):
        ok, reason, _ = D.validate_entry(world, None, kitchen, Book(),
                                         "chop", "player", item)
        assert ok, (item, reason)

    # 模型写「鸡块」→ Chicken：料箱里唯一子串匹配是 NuggetChicken，归一再校验。
    assert D.resolve_material(world, kitchen, "Chicken") == "NuggetChicken"
    ok, reason, _ = D.validate_entry(
        world, None, kitchen, Book(), "chop", "player",
        D.resolve_material(world, kitchen, "Chicken"))
    assert ok, reason

    # 归不到唯一料箱的名字仍要拒绝，并把可用物料列给模型。
    ok, reason, _ = D.validate_entry(world, None, kitchen, Book(),
                                     "chop", "player", "Chips")
    assert not ok and "NuggetChicken" in reason
