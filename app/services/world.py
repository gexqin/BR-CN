"""公共世界视图:地图/新闻/生存者一览(对等 map.cgi/news.cgi/rank.cgi)。"""
import datetime
import json

from .. import config
from ..engine import time_utils


def map_view(conn, game_id):
    """10×10 网格(行 A-J、列 01-10),22 地点按坐标放置,其余为海。"""
    game = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    forbidden = set(time_utils.forbidden_places(game)) if game else set()
    nxt = set(time_utils.next_forbidden_places(game)) if game else set()
    cells = {}
    for i, coord in enumerate(config.AREA):
        row, col = coord.split("-")
        cells[f"{row}{int(col):02d}"] = dict(
            place=i, name=config.PLACE[i],
            state="forbidden" if i in forbidden else
                  ("next" if i in nxt else "open"))
    return dict(rows=[chr(ord("A") + i) for i in range(10)],
                cols=[f"{i:02d}" for i in range(1, 11)],
                cells=cells, hacked=bool(game["hack_active"]) if game else False)


def news_view(conn, game_id, limit=200):
    rows = conn.execute(
        "SELECT n.*, s.f_name s_f, s.l_name s_l FROM news n "
        "LEFT JOIN players s ON s.id=n.subject_id "
        "WHERE n.game_id=? ORDER BY n.id DESC LIMIT ?", (game_id, limit)).fetchall()
    out = []
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["at"])
        out.append(dict(id=r["id"], at=r["at"], date=d.strftime("%m月%d日"),
                        time=d.strftime("%H:%M"), kind=r["kind"], text=r["text"]))
    return out


def rank_view(conn, game_id):
    """生存者一览(原版 rank.cgi:存活、政府 NPC 不显示)。"""
    rows = conn.execute(
        "SELECT * FROM players WHERE game_id=? AND hit>0 AND is_government=0 "
        "ORDER BY class_name, sex, class_no", (game_id,)).fetchall()
    alive = len(rows)
    dead = conn.execute(
        "SELECT COUNT(*) c FROM players WHERE game_id=? AND status='dead' AND is_government=0",
        (game_id,)).fetchone()["c"]
    return dict(alive=alive, dead=dead, members=[
        dict(id=r["id"], f_name=r["f_name"], l_name=r["l_name"], sex=r["sex"],
             class_name=r["class_name"], class_no=r["class_no"], com=r["com"])
        for r in rows])
