"""玩家状态聚合视图(GET /api/game/state)。

- 不结算睡眠/治疗(对等原版:仅主动交互结算;轮询只展示);
- 触发世界惰性推进(禁区日界,任意请求都会推进,对等原版 pref.cgi);
- 组装:玩家面板/地点/禁区提示/感知日志/剩余人数/增量游标。
"""
import datetime
import json

from .. import config
from ..engine import time_utils
from ..engine.news import add_sense


def visible_senses(conn, game_id, player, now, since_id=0):
    """可见感知(原版 IDCHK 枪声/悲鸣/扩音器 26-37):
    枪声 15 秒内且非当事人;悲鸣 15 秒内非当事人且同地点;扩音 30 秒内全员。"""
    rows = conn.execute(
        "SELECT * FROM sense_logs WHERE game_id=? AND expire_at>? AND id>? ORDER BY id",
        (game_id, now, since_id)).fetchall()
    texts = config.load_seed("texts.json")["messages"]
    out = []
    for r in rows:
        if r["player_id"] == player["id"] or r["target_id"] == player["id"]:
            continue
        if r["kind"] in ("gunshot",) and now < r["expire_at"]:
            place = config.PLACE[r["place"]] if r["place"] is not None else ""
            out.append(dict(id=r["id"], html=texts["gunshot_near"].format(place=place)))
        elif r["kind"] == "scream" and r["place"] == player["place"]:
            out.append(dict(id=r["id"], html=texts["scream_near"]))
        elif r["kind"] == "announce":
            place, name, speech = (r["message"] or "||").split("|", 2) \
                if r["message"] and "|" in r["message"] else ("", "", r["message"] or "")
            out.append(dict(id=r["id"],
                            html=texts["announce_near"].format(place=place, name=name, speech=speech)))
    return out


def game_state(conn, token, since_id=0):
    """聚合主界面状态。since_id 为客户端感知游标(增量返回 id 更大的感知)。"""
    from .auth import session_player
    s, player = session_player(conn, token)
    if not s or player is None:
        return None, dict(error="not_logged_in")
    game = conn.execute("SELECT * FROM games WHERE id=?", (player["game_id"],)).fetchone()
    now = datetime.datetime.now().timestamp()

    # 世界惰性推进(禁区日界;不结算个人恢复)+ 胜负判定
    import random
    texts = config.load_seed("texts.json")
    time_utils.advance_world(conn, game, now, texts, random.Random())
    game = conn.execute("SELECT * FROM games WHERE id=?", (player["game_id"],)).fetchone()
    time_utils.check_victory(conn, game, now, texts, random.Random())
    game = conn.execute("SELECT * FROM games WHERE id=?", (player["game_id"],)).fetchone()
    # 玩家可能在推进中被处决,重读
    player = conn.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()

    # 死亡/结局只读视图
    if player["hit"] <= 0 or player["status"] in ("dead",):
        return dict(view="dead", player=_dead_info(player)), None
    if player["status"] == "escaped" or game["status"] == "finished_escape":
        return dict(view="ending_escape", player=_brief(player),
                    key_user=bool(player["key_flag"])), None
    if player["status"] == "won" or (game["status"] == "finished_win"):
        winner = conn.execute("SELECT * FROM players WHERE id=?",
                              (game["winner_player_id"],)).fetchone() if game["winner_player_id"] else None
        return dict(view="ending_win", player=_brief(player),
                    winner=_brief(winner) if winner else None), None

    texts = config.load_seed("texts.json")
    forbidden = time_utils.forbidden_places(game)
    in_forbidden = player["place"] in forbidden
    alive = conn.execute(
        "SELECT COUNT(*) c FROM players WHERE game_id=? AND hit>0 AND is_government=0",
        (game["id"],)).fetchone()["c"]

    senses = visible_senses(conn, game["id"], player, now, since_id)
    sense_html = "".join(x["html"] for x in senses)

    log = player["log"] or ""
    state = dict(
        view="main",
        senses=senses,           # 增量感知(前端轮询按 id 追加)
        player=_panel(player),
        place=dict(
            index=player["place"], name=config.PLACE[player["place"]],
            coord=config.AREA[player["place"]],
            desc=texts["arinfo"][player["place"]],
            is_forbidden=in_forbidden,
        ),
        forbidden=dict(
            names=[config.PLACE[i] for i in forbidden],
            next_names=[config.PLACE[i] for i in time_utils.next_forbidden_places(game)],
            hacked=bool(game["hack_active"]),
        ),
        alive=alive,
        status=player["status"],        # alive|sleeping|healing
        log=(sense_html + log) if sense_html else log,
        sense_last=max((x["id"] for x in senses), default=0),
        news_last=conn.execute("SELECT MAX(id) m FROM news WHERE game_id=?",
                               (game["id"],)).fetchone()["m"] or 0,
        game=dict(status=game["status"], day=_game_day(game)),
    )
    return state, None


def _game_day(game):
    """第几天:自开局起的自然日数 + 1。"""
    d0 = datetime.datetime.fromtimestamp(game["start_at"]).date()
    return (datetime.datetime.now().date() - d0).days + 1


def _brief(p):
    return dict(id=p["id"], f_name=p["f_name"], l_name=p["l_name"],
                sex=p["sex"], class_name=p["class_name"], class_no=p["class_no"],
                club=p["club"])


def _panel(p):
    items = json.loads(p["items"])
    injuries = [x for x in ("头", "腕", "腹", "足") if x in (p["injuries"] or "")]
    wep_att_display = p["wep_att"]
    if ("G" in p["wep_code"] or "A" in p["wep_code"]) and not p["wep_uses"]:
        wep_att_display = int(p["wep_att"] / 10)
    ball = p["bou_def"] + p["bouh_def"] + p["bouf_def"] + p["boua_def"]
    acc = items[5] if items else None
    if acc and "AD" in acc["code"]:
        ball += acc["eff"]
    return dict(
        id=p["id"], f_name=p["f_name"], l_name=p["l_name"], sex=p["sex"],
        class_name=p["class_name"], class_no=p["class_no"], club=p["club"],
        level=p["level"], exp=p["exp"], next_exp=p["level"] * config.BASEEXP + (p["level"] - 1) * config.BASEEXP,
        hit=p["hit"], mhit=p["mhit"], sta=p["sta"], maxsta=config.MAXSTA,
        att=p["att"], wep_att=wep_att_display,
        deff=p["deff"], armor_total=ball,
        weapon=dict(name=p["wep_name"], code=p["wep_code"], att=p["wep_att"],
                    uses=p["wep_uses"]),
        body_armor=dict(name=p["bou_name"], code=p["bou_code"], deff=p["bou_def"], uses=p["bou_uses"]),
        head_armor=_armor(p, "bouh"), foot_armor=_armor(p, "bouf"), arm_armor=_armor(p, "boua"),
        accessory=acc,
        items=[it for it in items],
        injuries=injuries,
        kill=p["kill"],
        msg=p["msg"], dmes=p["dmes"], com=p["com"],
        profs=dict(wn=p["prof_wn"], wp=p["prof_wp"], wa=p["prof_wa"], wg=p["prof_wg"],
                   wc=p["prof_wc"], wd=p["prof_wd"], wb=p["prof_wb"], ws=p["prof_ws"]),
    )


def _armor(p, prefix):
    name = p[f"{prefix}_name"]
    if not name:
        return None
    return dict(name=name, code=p[f"{prefix}_code"], deff=p[f"{prefix}_def"],
                uses=p[f"{prefix}_uses"])


def _dead_info(p):
    texts = config.load_seed("texts.json")["messages"]
    return dict(f_name=p["f_name"], l_name=p["l_name"], death=p["death_type"] or "",
                msg=p["msg"],
                html=texts["already_dead"].format(death=p["death_type"] or "不明",
                                                  msg=p["msg"]))
