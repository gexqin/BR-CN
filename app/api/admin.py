"""管理 API(对等 admin.cgi)。登录/开新局先行;完整管理功能见 P7。

[FIX] 管理操作与玩家命令彻底分离(原版 battle.cgi 可无鉴权调用 RESET/BSAVE/BREAD)。
"""
import datetime
import hmac
import json
import random

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import config, ratelimit, security
from ..db import transaction
from ..engine.news import add_news
from ..services import auth as auth_svc
from .deps import get_conn

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request, conn):
    s, _ = auth_svc.session_player(conn, request.cookies.get(auth_svc.SESSION_COOKIE))
    if not s or not s["is_admin"]:
        raise HTTPException(401, "需要管理员权限")


class AdminLoginForm(BaseModel):
    password: str


@router.post("/login")
def admin_login(form: AdminLoginForm, request: Request, response: Response,
                conn=Depends(get_conn)):
    # [安全] 无默认密码:未配置 BR_ADMIN_PASS 时管理登录整体禁用
    if not config.ADMIN_PASSWORD:
        raise HTTPException(503, "未设置管理密码:请通过环境变量 BR_ADMIN_PASS 配置后重启")
    ip = request.client.host if request.client else "?"
    key = f"admin:ip:{ip}"
    if ratelimit.is_locked(key):
        raise HTTPException(429, "尝试次数过多,请稍后再试")
    # [安全] 常数时间比较,防时序侧信道
    if not hmac.compare_digest(form.password, config.ADMIN_PASSWORD):
        ratelimit.record_fail(key, max_fails=5, lock_secs=900)
        raise HTTPException(401, "管理密码不正确")
    ratelimit.clear(key)
    with transaction(conn):
        token = auth_svc.create_session(conn, None, None, is_admin=1)
    response.set_cookie(auth_svc.SESSION_COOKIE, token, httponly=True,
                        samesite="lax", secure=config.COOKIE_SECURE)
    return dict(ok=True)


def new_game(conn, rng=None) -> int:
    """数据初始化(对原 admin.cgi DATARESET;每局一行 games)。
    - [需求] 开新局即清除旧局全部用户:旧局玩家及其会话删除(会话含登录态),
      旧局玩家再登录将提示"学员不存在,请注册";games/news 记录保留
    - 禁区顺序洗牌,分校固定第 1(即刻为禁区)
    - 重撒区域物品(99=随机撒入 1..21)
    - NPC 入场(班主任+士兵,政府系,守分校,携带程序解除钥匙)
    """
    rng = rng or random.Random()
    now = datetime.datetime.now().timestamp()
    order = list(range(1, 22))
    rng.shuffle(order)
    order = [0] + order          # 分校恒第 1

    with transaction(conn):
        # 旧局作废:残留 running 状态会干扰"最新局"判定
        # (登录/注册按最新 running 局查找,旧空局会顶在前导致查无此 ID)
        conn.execute("UPDATE games SET status='abandoned', end_reason='开新局作废' "
                     "WHERE status='running'")
        # 清除旧局用户信息(先删会话,sessions 外键引用 players;管理会话保留)
        conn.execute("DELETE FROM sessions WHERE player_id IS NOT NULL")
        conn.execute("DELETE FROM players")
        cur = conn.execute(
            "INSERT INTO games(status, start_at, last_tick_day, forbidden_order, "
            "forbidden_count) VALUES('running',?,?,?,1)",
            (now, datetime.datetime.now().strftime("%Y-%m-%d"),
             json.dumps(order)))
        game_id = cur.lastrowid

        # 撒物品
        items = config.load_seed("items.json")
        for place, lst in items.items():
            for it in lst:
                p = int(place)
                if p == 99:
                    p = rng.randint(1, 21)
                conn.execute(
                    "INSERT INTO area_items(game_id, place, name, code, eff, uses, "
                    "trap, created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (game_id, p, it["name"], it["code"], it["eff"], it["uses"],
                     1 if it["code"] == "TO" else 0, now))

        # NPC 入场(政府系,守分校)
        for i, npc in enumerate(config.load_seed("npcs.json"), start=1):
            gov = npc["class_name"] in (config.BOSS_CLASS, config.ZAKO_CLASS)
            wep = npc["weapon"]
            body = npc["body_armor"]
            items_json = json.dumps(
                [it if it else None for it in npc["items"]], ensure_ascii=False)
            att = rng.randrange(10) + (config.NPC_GOV_ATT if gov else 8)
            deff = rng.randrange(10) + (config.NPC_GOV_ATT if gov else 8)
            hit = rng.randrange(30) + (config.NPC_GOV_HIT if gov else 40)
            cols = ("game_id, username, pass_hash, f_name, l_name, sex, class_name, "
                    "class_no, is_npc, is_government, att, deff, hit, mhit, level, "
                    "prof_wn, prof_wp, prof_wa, prof_wg, prof_we, prof_wc, prof_wd, "
                    "prof_wb, prof_wf, prof_ws, wep_name, wep_code, wep_att, "
                    "wep_uses, bou_name, bou_code, bou_def, bou_uses, items, place, "
                    "sta, created_at")
            conn.execute(
                f"INSERT INTO players({cols}) VALUES({','.join(['?'] * 37)})",
                (game_id, f"{config.ADMIN_USER}.{i}", security.new_token(),
                 npc["f_name"], npc["l_name"], npc["sex"], npc["class_name"],
                 npc["class_no"], 1, 1 if gov else 0,
                 att, deff, hit, hit,
                 config.NPC_GOV_LEVEL if gov else 1,
                 *[config.NPC_GOV_PROF if gov else 0] * 10,
                 wep["name"], wep["code"], wep["att"], wep["uses"],
                 body["name"], body["code"], body["deff"], body["uses"],
                 items_json, 0, config.MAXSTA, now))

        add_news(conn, game_id, now, "NEWGAME",
                 text="新的游戏开始了。")
    return game_id


@router.post("/new_game")
def admin_new_game(request: Request, conn=Depends(get_conn)):
    _require_admin(request, conn)
    game_id = new_game(conn)
    return dict(ok=True, game_id=game_id)


@router.get("/players")
def admin_players(request: Request, conn=Depends(get_conn)):
    _require_admin(request, conn)
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    if game is None:
        return dict(players=[], game=None)
    rows = conn.execute(
        "SELECT id, f_name, l_name, sex, class_name, class_no, club, status, "
        "death_type, kill, place, is_npc, is_government, username FROM players "
        "WHERE game_id=? ORDER BY is_npc, class_name, sex, class_no",
        (game["id"],)).fetchall()
    from .. import config as cfg
    return dict(game=dict(id=game["id"], status=game["status"]),
                players=[dict(
        id=r["id"], name=f"{r['f_name']} {r['l_name']}", sex=r["sex"],
        class_name=r["class_name"], class_no=r["class_no"], club=r["club"],
        status=r["status"], death=r["death_type"], kill=r["kill"],
        place=cfg.PLACE[r["place"]], npc=bool(r["is_npc"]),
        government=bool(r["is_government"]), username=r["username"]) for r in rows])


class ExecuteForm(BaseModel):
    player_id: int
    message: str = ""


@router.post("/execute")
def admin_execute(form: ExecuteForm, request: Request, conn=Depends(get_conn)):
    """政府处刑(对等 admin.cgi USERDEL/DEATH4):标记死亡并公告,不删除记录。

    [FIX] 处刑不剥夺尸体物品:政府系 NPC 的程序解除钥匙仍在尸体上,EX 路线不受影响。
    """
    import random

    _require_admin(request, conn)
    from ..engine.death import kill_player
    from .. import config
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    if game is None:
        raise HTTPException(400, "尚无游戏数据,请先数据初始化")
    p = conn.execute("SELECT * FROM players WHERE id=? AND game_id=?",
                     (form.player_id, game["id"])).fetchone()
    if p is None or p["hit"] <= 0 or p["status"] in ("dead", "won", "escaped"):
        raise HTTPException(400, "角色不存在、已死亡或已脱离游戏")
    with transaction(conn):
        if form.message:
            from ..engine.util import esc
            conn.execute("UPDATE players SET msg=? WHERE id=?",
                         (esc(form.message[:32]), p["id"]))
            p = conn.execute("SELECT * FROM players WHERE id=?", (p["id"],)).fetchone()
        now = datetime.datetime.now().timestamp()
        kill_player(conn, game, dict(p), now,
                    config.load_seed("texts.json"), random.Random(),
                    death_type=config.DEATH_GOV)
        # [FIX] 处刑可能使存活者归零/归一:立即终局判定(对等玩家命令路径)
        from ..engine.time_utils import check_victory
        check_victory(conn, game, now, config.load_seed("texts.json"),
                      random.Random())
    return dict(ok=True)


@router.post("/backup")
def admin_backup(request: Request, conn=Depends(get_conn), label: str = ""):
    """整档快照(对等 admin.cgi BACKSAVE):players+area_items+news+games。"""
    _require_admin(request, conn)
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    snap = dict(
        games=[dict(r) for r in conn.execute("SELECT * FROM games WHERE id=?",
                                             (game["id"],)).fetchall()],
        players=[dict(r) for r in conn.execute(
            "SELECT * FROM players WHERE game_id=?", (game["id"],)).fetchall()],
        area_items=[dict(r) for r in conn.execute(
            "SELECT * FROM area_items WHERE game_id=?", (game["id"],)).fetchall()],
        news=[dict(r) for r in conn.execute(
            "SELECT * FROM news WHERE game_id=?", (game["id"],)).fetchall()],
    )
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO admin_backups(game_id, at, label, snapshot) VALUES(?,?,?,?)",
            (game["id"], datetime.datetime.now().timestamp(), label,
             json.dumps(snap, ensure_ascii=False)))
        bid = cur.lastrowid
    return dict(ok=True, backup_id=bid)


@router.get("/backups")
def admin_backups(request: Request, conn=Depends(get_conn)):
    _require_admin(request, conn)
    rows = conn.execute(
        "SELECT id, game_id, at, label FROM admin_backups ORDER BY id DESC").fetchall()
    return dict(backups=[dict(id=r["id"], game_id=r["game_id"], at=r["at"],
                              label=r["label"]) for r in rows])


class RollbackForm(BaseModel):
    backup_id: int


@router.post("/rollback")
def admin_rollback(form: RollbackForm, request: Request, conn=Depends(get_conn)):
    """回滚整档(对等 admin.cgi BACKREAD)。"""
    _require_admin(request, conn)
    b = conn.execute("SELECT * FROM admin_backups WHERE id=?",
                     (form.backup_id,)).fetchone()
    if b is None:
        raise HTTPException(404, "备份不存在")
    snap = json.loads(b["snapshot"])
    game_id = b["game_id"]
    with transaction(conn):
        # 会话引用 players/games(外键),先清理
        conn.execute("DELETE FROM sessions WHERE game_id=?", (game_id,))
        conn.execute("DELETE FROM sessions WHERE player_id NOT IN "
                     "(SELECT id FROM players)")
        for table in ("players", "area_items", "news"):
            conn.execute(f"DELETE FROM {table} WHERE game_id=?", (game_id,))
        conn.execute("DELETE FROM games WHERE id=?", (game_id,))
        _restore(conn, "games", snap["games"])
        _restore(conn, "players", snap["players"])
        _restore(conn, "area_items", snap["area_items"])
        _restore(conn, "news", snap["news"])
    return dict(ok=True)


def _restore(conn, table, rows):
    for r in rows:
        cols = ", ".join(r.keys())
        ph = ", ".join(["?"] * len(r))
        conn.execute(f"INSERT OR REPLACE INTO {table}({cols}) VALUES({ph})",
                     tuple(r.values()))
