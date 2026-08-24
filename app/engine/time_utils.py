"""惰性时间结算:睡眠/治疗恢复、禁区日界推进、滞留处决。

对等原版语义:
- 恢复仅在玩家下一次「主动交互」(命令/登录)时结算(pref.cgi + lib2.cgi STS);
  状态轮询(GET /state)不结算,避免自动轮询把睡眠打断。
- 禁区推进由任意请求触发(pref.cgi):跨过自然日 0:00 → ar+=3、滞留者处决、
  黑客标志重置。games.last_tick_day 记录已结算到的自然日。
"""
import datetime
import json

from .. import config
from .. import db as dbmod
from . import util


def settle_rest(conn, player, now, texts) -> str:
    """结算睡眠/治疗恢复(原版 lib2.cgi STS 80-106)。

    player 为可变 dict:直接修改 sta/hit/status;调用方负责落库。
    返回日志 HTML(可为空)。
    """
    if player["rest_since"] is None:
        return ""
    up = int((now - player["rest_since"]) / config.KAIFUKU_TIME)
    if "腹" in (player["injuries"] or ""):
        up = int(up / 2)
    if player["status"] == "sleeping":
        gained = max(0, min(up, config.MAXSTA - player["sta"]))
        player["sta"] += gained
        msg = texts["messages"]["sleep_effect"].format(up=gained)
    elif player["status"] == "healing":
        up = int(up / config.KAIFUKU_RATE)
        gained = max(0, min(up, player["mhit"] - player["hit"]))
        player["hit"] += gained
        msg = texts["messages"]["heal_effect"].format(up=gained)
    else:
        return ""
    player["status"] = "alive"
    player["rest_since"] = None
    return msg


def forbidden_places(game) -> list:
    """当前禁区地点索引列表(前 forbidden_count 个;黑客解除时视为空)。"""
    if game["hack_active"]:
        return []
    order = json.loads(game["forbidden_order"])
    return order[: game["forbidden_count"]]


def next_forbidden_places(game) -> list:
    """下次公布的禁区(顺序表中接下来的 3 个)。"""
    order = json.loads(game["forbidden_order"])
    return order[game["forbidden_count"]: game["forbidden_count"] + 3]


def today(now=None) -> str:
    return datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d") if now \
        else datetime.datetime.now().strftime("%Y-%m-%d")


def advance_world(conn, game, now, texts, rng) -> list:
    """禁区日界推进 + 滞留处决(原版 pref.cgi)。返回状态变化说明列表。

    自带 BEGIN IMMEDIATE 保护(未处于外层事务时),避免并发双跳。
    """
    events = []
    if game["status"] != "running":
        return events
    day = today(now)
    if game["last_tick_day"] is not None and day <= game["last_tick_day"]:
        return events

    own_tx = not conn.in_transaction
    if own_tx:
        conn.execute("BEGIN IMMEDIATE")
    # 取写锁后重读,防止并发请求重复推进
    game = conn.execute("SELECT * FROM games WHERE id=?", (game["id"],)).fetchone()
    if game["status"] != "running" or (
            game["last_tick_day"] is not None and day <= game["last_tick_day"]):
        if own_tx:
            conn.execute("COMMIT")
        return events

    order = json.loads(game["forbidden_order"])
    new_count = min(game["forbidden_count"] + 3, len(order))
    added = order[game["forbidden_count"]: new_count]
    game_id = game["id"]

    conn.execute(
        "UPDATE games SET forbidden_count=?, hack_active=0, last_tick_day=? WHERE id=?",
        (new_count, day, game_id))

    # [安全] 顺带清理无限增长的表:过期感知日志(查询侧已按 expire_at 过滤,
    # 行本身此前永不删除)与过期会话(原先仅在被再次访问时惰性删除)
    conn.execute("DELETE FROM sense_logs WHERE expire_at<?", (now,))
    conn.execute("DELETE FROM sessions WHERE expires_at<?", (now,))

    # 新闻:禁区追加(含当前与下次禁区)
    from .news import add_news
    cur = [config.PLACE[i] for i in order[:new_count]]
    nxt = [config.PLACE[i] for i in order[new_count: new_count + 3]]
    add_news(conn, game_id, now, "AREA", subject_id=None, opponent_id=None,
             extra=dict(count=new_count),
             text=f"禁止区域追加:{('、'.join(config.PLACE[i] for i in added) or '无')}。"
                  f"现在禁止的地区:{'、'.join(cur)}。下次禁止的地区:{'、'.join(nxt) or '无'}。")
    events.append(f"禁止区域追加:{('、'.join(config.PLACE[i] for i in added) or '无')}。")

    # 滞留处决:位于全部当前禁区(order[:new_count])的存活玩家(政府系除外)。
    # 含旧禁区:黑客解除期间进入的玩家在次日标志重置时同样被处决(对等 pref.cgi)
    players = conn.execute(
        "SELECT * FROM players WHERE game_id=? AND status IN ('alive','sleeping','healing')",
        (game_id,)).fetchall()
    all_forbidden = set(order[:new_count])
    for p in players:
        if p["is_government"]:
            continue
        if p["place"] in all_forbidden:
            from .death import kill_player
            kill_player(conn, game, dict(p), now, texts, rng, death_type=config.DEATH_AREA)
            events.append(f"{p['f_name']} {p['l_name']} 因禁区滞留被处决。")
    if own_tx:
        conn.execute("COMMIT")
    return events


def check_victory(conn, game, now, texts, rng) -> dict | None:
    """优胜/EX 判定(原版 lib2.cgi IDCHK 57-74)。

    自带 BEGIN IMMEDIATE(未处于外层事务时)+ 取锁后重读,防并发双写。
    """
    if game["status"] != "running":
        return None
    own_tx = not conn.in_transaction
    if own_tx:
        conn.execute("BEGIN IMMEDIATE")
    game = conn.execute("SELECT * FROM games WHERE id=?", (game["id"],)).fetchone()
    if game["status"] != "running":
        if own_tx:
            conn.execute("COMMIT")
        return None
    alive = conn.execute(
        "SELECT * FROM players WHERE game_id=? AND hit>0 AND is_government=0",
        (game["id"],)).fetchall()
    mem = len(alive)
    b_limit = config.BATTLE_LIMIT * 3 + 1
    result = None
    if mem == 1 and game["forbidden_count"] > b_limit:
        winner = alive[0]
        conn.execute("UPDATE players SET win_flag=1, status='won' WHERE id=?",
                     (winner["id"],))
        conn.execute("UPDATE games SET status='finished_win', winner_player_id=?, "
                     "end_reason='优胜' WHERE id=?", (winner["id"], game["id"]))
        from .news import add_news
        add_news(conn, game["id"], now, "WINEND", subject_id=winner["id"],
                 extra=dict(),
                 text=f"{winner['f_name']} {winner['l_name']} 成为优胜者。游戏结束。")
        result = dict(kind="win", winner=winner["id"])
    elif mem == 0:
        # [FIX] 全员死亡(禁区处决/毒等同日耗尽存活者)也需终局,否则永久卡在 running
        conn.execute("UPDATE games SET status='finished_win', winner_player_id=NULL, "
                     "end_reason='全员死亡' WHERE id=?", (game["id"],))
        from .news import add_news
        add_news(conn, game["id"], now, "WINEND", subject_id=None,
                 extra=dict(),
                 text="最后的生存者倒下了。游戏落幕,无优胜者。")
        result = dict(kind="wipeout")
    if own_tx:
        conn.execute("COMMIT")
    return result
