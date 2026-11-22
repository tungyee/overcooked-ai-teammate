"""卷饼装馅顺序不固定：包肉卷饼也能直接盛饭（4-6 实机）。

真实帧 tests/fixtures/mine/mine46-20261123-004522-meat-wrap-rice.ndjson.gz
（trace-20261123-004522，Mine_4_6_2P 第二局）：
  [0] t=7255 散熟饭锅在台面，台面上有一只包肉卷饼（Meat_Burrito #6 的），
      旧行为只发「给空卷饼盛饭」，AI 去拿新卷饼。
  [1] t=7880 饭锅刚熟，包肉卷饼（配给 Meat_Burrito #9）仍在台面，同上。
游戏允许任意顺序往卷饼里加熟料（同局实测 (BurritoMeat)→(BurritoMeat,Rice)）。
"""
import gzip
import json
import os

import pytest

from ai.core import planner
from ai.query import carriers as CR
from ai.query import recipe_graph
from ai.query.recipes import RecipeBook
from ai.state import world as W
from ai.state.bb_factory import make_bb

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mine",
                       "mine46-20261123-004522-meat-wrap-rice.ndjson.gz")
MEAT_T = "cooked:burritomeat:fryingpan"
RICE_T = "cooked:rice:pot"


@pytest.fixture(scope="module")
def frames():
    with gzip.open(FIXTURE, "rt", encoding="utf8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _setup(frame):
    w = W.World(frame)
    book = RecipeBook(w.recipes, w.stations)
    bb = make_bb(frame.get("_trace_t", 100))
    pm = planner._match_plates_to_orders(w, bb, book, orders=w.orders)
    car = CR.match_carriers_to_orders(w, book, pm, orders=w.orders)
    cm = planner._match_cookers_to_orders(w, bb, book, pm, orders=w.orders,
                                          carrier_match=car)
    return w, book, bb, pm, car, cm


def test_wrap_node_puts_existing_filling_first():
    """已装肉的卷饼：链底是肉（视为完成），饭的前置内容是肉。"""
    book = RecipeBook([
        {"name": "Meat_Burrito", "comp": ["Tortilla", "BoiledRice", "FriedBurritoMeat"],
         "cook": "null", "plate": "CompositeBurrito"},
        {"name": "Tortilla", "comp": [], "cook": "null", "plate": "CompositeBurrito"},
        {"name": "BoiledRice", "comp": ["Rice"], "cook": "Pot", "plate": "x"},
        {"name": "FriedBurritoMeat", "comp": ["BurritoMeat"], "cook": "FryingPan",
         "plate": "y"},
    ], stations=[])
    if book.wrap_base("Meat_Burrito") is None:
        pytest.skip("合成配方未判成 wrap")
    node = recipe_graph._wrap_node(book, "Meat_Burrito", have={MEAT_T})
    top = node["children"][0]
    assert top["item"] == "BoiledRice"
    assert tuple(top["pre_contents"]) == (MEAT_T,)
    # 默认顺序不变（饭在前）
    node0 = recipe_graph._wrap_node(book, "Meat_Burrito")
    assert node0["children"][0]["item"] == "FriedBurritoMeat"


@pytest.mark.parametrize("idx,order_id", [(0, "6"), (1, "9")])
def test_rice_goes_to_meat_wrap(frames, idx, order_id):
    w, book, bb, pm, car, cm = _setup(frames[idx])
    assert car.get(order_id) is not None and MEAT_T in car[order_id]["contents"]
    # 熟饭源配给包肉卷饼那单
    assert order_id in cm.values(), cm
    order = next(o for o in w.orders if o["id"] == order_id)
    fills = [t for t in recipe_graph.emit(w, bb, book, order, pm, cm, car)
             if t.TYPE == "FillCarrier"]
    assert any(t.item == "BoiledRice" and t.pre_contents == (MEAT_T,)
               for t in fills), [str(t) for t in fills]


def test_planner_fills_meat_wrap_when_rice_cooked(frames):
    """t=7880 饭刚熟：planner 直接端包肉卷饼去盛饭。"""
    w, book, bb, *_ = _setup(frames[1])
    task, _rec = planner.plan(w, bb, None, book)
    assert task is not None and task.TYPE == "FillCarrier", task
    assert task.pre_contents == (MEAT_T,), task
