# -*- coding: utf-8 -*-
"""取料上砧板按行走距离就近选空板（trace-20261118-224142 t=142）。

Mine_5_3 两块空砧板同名，插件按 InstanceID 后缀区分。P2 拿着鸡块站在
(8.45, 0.0)，左板 (7.2, -4.8) 走 4 步、右板 (20.4, -4.8) 走 13 步。
旧实现按 workstations 枚举顺序给候选，右板排前 → 同分平手时被选中，
P2 舍近求远。修：按 interact_cost 升序排，近板排前。
"""
import gzip
import json
import os

from ai.core import planner
from ai.query.recipes import RecipeBook
from ai.state import world as W
from ai.state.bb_factory import make_bb

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mine",
                       "mine53-two-empty-boards.ndjson.gz")
LEFT = "countertop_01_chopping_board_wood"
RIGHT = "countertop_01_chopping_board_wood (1)"


def _frame():
    with gzip.open(FIXTURE, "rt", encoding="utf8") as fh:
        return json.loads(next(line for line in fh if line.strip()))


def test_fetch_to_board_prefers_nearest_empty_board():
    w = W.World(_frame())
    book = RecipeBook(w.recipes, w.stations)
    bb = make_bb(100)
    task, rec = planner.plan(w, bb, None, book)
    fetch = [c[0] for c in rec["candidates"] if c[0].TYPE == "FetchToBoard"]
    assert fetch, "应有取料上砧板候选"
    # 第一张单（鸡块）的取料候选应按距离把近板排前面
    assert fetch[0].board_id == LEFT, "近板应排前面，实际 %r" % fetch[0].board_id
    assert task.TYPE == "FetchToBoard"
    assert task.board_id == LEFT
