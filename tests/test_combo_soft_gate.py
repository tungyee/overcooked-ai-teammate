"""combo 闸软化：队首不「马上能送」时，不再扣着别单的料齐盘。

2-2（Balloon_2_3）实机 trace-20261119-005513：Marinara 盘 lt 76 料齐，队首
MeatOnly 的肉还没下锅，`combo_break` 硬拦到 lt 143 才送；三局成品盘被扣
67~125 秒，本关只有 3 只盘，熟锅没盘装、灶位被占。
"""
import copy
import gzip
import json
import os

import pytest

from ai import tasks as T
from ai.core import planner
from ai.state import world as W

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "balloon",
                       "balloon23-20261030-224658-plate-to-cooked.ndjson.gz")

_MEAT_PAN = "workstation_cooker_01 (4)"


@pytest.fixture(scope="module")
def frame():
    with gzip.open(FIXTURE, "rt", encoding="utf8") as fh:
        return [json.loads(line) for line in fh if line.strip()][-1]


def _scenario(frame, meat=None):
    """队首 #1 MeatOnly、#2 Marinara；盘 A = 完整 Marinara，盘 B = 只有意面。

    meat: None = 肉没下锅；(progress, time) = 肉锅在煎、进度如给定；
    "cooked" = 肉已熟在锅里。
    """
    f = copy.deepcopy(frame)
    f["orders"] = [
        {"id": "1", "dish": "Pasta_MeatOnly_New", "remaining": 60.0, "lifetime": 150,
         "composition": ["BoiledPasta", "FriedBurritoMeat"], "optional": []},
        {"id": "2", "dish": "Pasta_Marinara_New", "remaining": 80.0, "lifetime": 150,
         "composition": ["BoiledPasta", "PanFriedPrawns", "PanFriedFish"], "optional": []},
    ]
    for c in f["cookers"]:
        c.update(isCooking=False, cooked=False, burning=False, onFire=False,
                 cooking_progress=0, pot_contents=[])
        if c["n"] == _MEAT_PAN and meat is not None:
            if meat == "cooked":
                c.update(cooked=True, cooking_progress=12, cooking_time=12,
                         pot_contents=["CookedCompositeAssembledNode(FryingPan){ ing:BurritoMeat }"])
            else:
                prog, total = meat
                c.update(isCooking=True, cooking_progress=prog, cooking_time=total,
                         pot_contents=["ing:BurritoMeat"])
    return W.World(f)


def _deliver_marinara():
    return T.DeliverPlate("2", ("-16230",))


def test_releases_when_head_topping_not_started(frame):
    """队首差的肉还没下锅 → 放行送 Marinara。"""
    w = _scenario(frame, meat=None)
    assert planner._head_close(w) is False
    assert planner._breaks_combo(_deliver_marinara(), w) is False


def test_releases_when_head_topping_far_from_done(frame):
    """肉锅才煎 2/12 秒 → 还要 10 秒，不值得扣盘。"""
    w = _scenario(frame, meat=(2.0, 12.0))
    assert planner._head_close(w) is False
    assert planner._breaks_combo(_deliver_marinara(), w) is False


def test_holds_when_head_topping_about_done(frame):
    """肉锅 9/12 秒（3 秒内熟），意面盘只差这份肉 → 仍拦，保连击。"""
    w = _scenario(frame, meat=(9.0, 12.0))
    assert planner._head_close(w) is True
    assert planner._breaks_combo(_deliver_marinara(), w) is True


def test_holds_when_head_topping_cooked(frame):
    w = _scenario(frame, meat="cooked")
    assert planner._head_close(w) is True
    assert planner._breaks_combo(_deliver_marinara(), w) is True


def test_head_dish_delivery_never_blocked(frame):
    w = _scenario(frame, meat=None)
    assert planner._breaks_combo(T.DeliverPlate("1", ("-16228",)), w) is False
