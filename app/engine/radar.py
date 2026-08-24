"""雷达(reader.cgi):R2 显示全部区域人数;R1(简易雷达)只显示自己所在区域
(其余空白——对等 reader.cgi 的 R1/R2 分支渲染)。"""
from .. import config
from .time_utils import forbidden_places


def build_radar(ctx, full=True):
    """返回各区域存活人数;黑客解除后不显示禁区。full=False 为 R1。"""
    rows = ctx.conn.execute(
        "SELECT place, COUNT(*) c FROM players WHERE game_id=? AND hit>0 "
        "GROUP BY place", (ctx.game["id"],)).fetchall()
    counts = {r["place"]: r["c"] for r in rows}
    forbidden = set(forbidden_places(ctx.game))
    cells = {}
    for i, coord in enumerate(config.AREA):
        row, col = coord.split("-")
        mine = (i == ctx.player["place"])
        cells[f"{row}{int(col):02d}"] = dict(
            place=i, name=config.PLACE[i],
            count=counts.get(i, 0) if (full or mine) else None,
            mine=mine,
            forbidden=(i in forbidden and not ctx.game["hack_active"]))
    return dict(rows=[chr(ord("A") + i) for i in range(10)],
                cols=[f"{i:02d}" for i in range(1, 11)],
                cells=cells)
