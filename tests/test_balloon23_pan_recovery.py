"""2-2（Balloon_2_3）煎锅被端下灶后：空锅回灶要排得上，空煎灶不当意面投放点。

实机 trace-20261119-005513 / 004632：RescueCooked 把熟料连锅放到台面，装盘后
空锅留在台面 64~140 秒，RecoverLoosePot 落在 L7、一次都没选中；同时没锅的
煎灶 cooker_01 (5) 被当成意面的 ThrowBatch 消费站。
基于真实帧 tests/fixtures/balloon/balloon23-20261030-224658-plate-to-cooked。
"""
import copy
import gzip
import json
import os

import pytest

from ai import tasks as T
from ai.core import planner
from ai.core import planner_layers as PL
from ai.query.recipes import RecipeBook
from ai.revenue import throw_supply as TS
from ai.state import world as W

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "balloon",
                       "balloon23-20261030-224658-plate-to-cooked.ndjson.gz")

_EMPTY_HOB = "workstation_cooker_01 (4)"   # 煎灶，锅被端走
_PAN = "utensil_frying_pan_01 (1)"


@pytest.fixture(scope="module")
def frame():
    with gzip.open(FIXTURE, "rt", encoding="utf8") as fh:
        return [json.loads(line) for line in fh if line.strip()][-1]


def _pan_off_hob(frame, dish="Pasta_MeatOnly_New"):
    """把 cooker_01 (4) 的煎锅挪到台面（空锅），订单全换成 dish。"""
    f = copy.deepcopy(frame)
    comp = {"Pasta_MeatOnly_New": ["BoiledPasta", "FriedBurritoMeat"],
            "Pasta_Marinara_New": ["BoiledPasta", "PanFriedPrawns", "PanFriedFish"]}[dish]
    f["orders"] = [{"id": str(i), "dish": dish, "remaining": 100.0 + i, "lifetime": 150,
                    "composition": comp, "optional": []} for i in (1, 2, 3)]
    f["plates"] = [p for p in f["plates"] if not p.get("detail")]
    hob = next(c for c in f["cookers"] if c["n"] == _EMPTY_HOB)
    hob.update(cookware=None, cook_type=None, cooked=None, burning=None,
               isCooking=False, cooking_progress=None, cooking_time=None,
               pot_contents=[])
    for it in f["items"]:
        if it.get("n") == _PAN:
            it.update(on_station="attach:countertop_01_standard_dark_wood",
                      x=24.0, z=-5.0, cooked="Raw", has_contents=False, detail=[])
    return W.World(f)


def _recover_task(world):
    hob = next(c for c in world.cookers if c["n"] == _EMPTY_HOB)
    from ai.query import predicates as P
    return T.RecoverLoosePot(resources=(P.resource_id(hob),), item=_PAN)


def test_recover_pan_enters_prep_layer_when_fried_topping_short(frame):
    w = _pan_off_hob(frame)
    task = _recover_task(w)
    assert PL.layer_of_task(task, w) == PL.L_PREP


def test_recover_pan_scored_like_fill_cooker(frame):
    w = _pan_off_hob(frame)
    book = RecipeBook(w.recipes, w.stations)
    shortfall, item = planner._loose_pot_shortfall(_recover_task(w), w, book)
    assert item == "FriedBurritoMeat"
    assert shortfall > 0
    assert planner._cooker_idle_bonus(shortfall) > 0


def test_recover_pan_stays_cleanup_without_fried_demand(frame):
    """订单不要煎料（只剩意面需求时）→ 煎锅回灶不抢备菜，留 L7。"""
    w = _pan_off_hob(frame)
    for o in w.orders:
        o["composition"] = ["BoiledPasta"]
        o["dish"] = "Pasta_Plain_Test"
    w.recipes = list(w.recipes) + [{"name": "Pasta_Plain_Test", "comp": ["BoiledPasta"],
                                    "cook": "null", "plate": "CompositePasta",
                                    "chop": "null", "chop_stages": "null",
                                    "chop_node": "null"}]
    assert PL.layer_of_task(_recover_task(w), w) == PL.L_CLEANUP


def test_pasta_not_thrown_to_hob_without_pan(frame):
    w = _pan_off_hob(frame)
    book = RecipeBook(w.recipes, w.stations)
    names = [st["n"] for st in TS.dest_candidates(w, book, TS.CONSUMER_COOKER, "BoiledPasta")]
    # 本帧 cooker_01 (2) 也没锅（实机煮锅同样被端走），两口空灶都不该当消费站
    assert _EMPTY_HOB not in names
    assert "workstation_cooker_01 (2)" not in names
    # 有煮锅的灶照常是消费站；有煎锅的灶按炊具过滤掉
    assert names == ["workstation_cooker_01"]
