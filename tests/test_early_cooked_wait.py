"""端着容器≠已开工：上一步留在手里的盘/卷饼不能绕过「离熟才去」的时机。

真实帧 tests/fixtures/mine/mine46-20261123-004522-early-wait.ndjson.gz
（trace-20261123-004522，Mine_4_6_2P）：
  [0] t=3498 第一局 lt 186.7：刚给卷饼盛完饭、端着卷饼，FillCarrier(蘑菇)
      离熟 7.7s 就以「执行中」身份可行，到锅边干等 7s。
  [1] t=5800 第二局 lt 75：盛完饭端着盘，TakeCookedToPlate(鸡肉) 离熟
      10.7s 就可行，到锅边干等 9s。
"""
import gzip
import json
import os

import pytest

from ai import tasks as T
from ai.core import planner
from ai.query.recipes import RecipeBook
from ai.state import world as W
from ai.state.bb_factory import make_bb

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mine",
                       "mine46-20261123-004522-early-wait.ndjson.gz")


@pytest.fixture(scope="module")
def frames():
    with gzip.open(FIXTURE, "rt", encoding="utf8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


_TASKS = [
    # [0] FillCarrier(FriedMushrooms, cooker (2), Tortilla, (饭,), order#8)
    lambda: T.FillCarrier("8", (("GridManager", "workstation_cooker_01 (2)"),
                                "Tortilla", ("cooked:rice:pot",)), "FriedMushrooms"),
    # [1] TakeCookedToPlate(FriedChicken, cooker (2), plate -72846, order#3)
    lambda: T.TakeCookedToPlate("3", (("GridManager", "workstation_cooker_01 (2)"),
                                      "-72846"), "FriedChicken"),
]


def _chosen_task(frame, w, book):
    """trace 里被选中的那个 task（按 trace 字符串重建值对象）。"""
    idx = 0 if frame["_trace_chosen"].startswith("FillCarrier") else 1
    task = _TASKS[idx]()
    assert str(task) == frame["_trace_chosen"], (str(task), frame["_trace_chosen"])
    return task


@pytest.mark.parametrize("idx", [0, 1])
def test_held_container_not_started_respects_lead_time(frames, idx):
    w = W.World(frames[idx])
    book = RecipeBook(w.recipes, w.stations)
    task = _chosen_task(frames[idx], w, book)
    ctx = planner._make_context(w, make_bb(frames[idx]["_trace_t"]), book)
    assert task.feasible(ctx) is False, task


@pytest.mark.parametrize("idx", [0, 1])
def test_active_commitment_keeps_task_feasible(frames, idx):
    """已经在执行（承诺就是它）：端着容器在锅边等仍可行，别半路丢掉。"""
    w = W.World(frames[idx])
    book = RecipeBook(w.recipes, w.stations)
    task = _chosen_task(frames[idx], w, book)
    bb = make_bb(frames[idx]["_trace_t"])
    bb.commitment.active_task = task
    ctx = planner._make_context(w, bb, book)
    assert task.feasible(ctx) is True, task


@pytest.mark.parametrize("idx", [0, 1])
def test_planner_does_not_pick_early_wait(frames, idx):
    w = W.World(frames[idx])
    book = RecipeBook(w.recipes, w.stations)
    task, _rec = planner.plan(w, make_bb(frames[idx]["_trace_t"]), None, book)
    assert str(task) != frames[idx]["_trace_chosen"], task
