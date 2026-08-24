"""注册/登录/会话(对等 regist.cgi REGIST/MAIN + lib2.cgi IDCHK)。

[FIX] 与原版差异:
- 密码 pbkdf2 哈希落库,会话为服务端 token(httpOnly cookie),
  彻底移除原版"每请求携带明文密码 + cookie 存整行明文状态"。
- 姓名长度按字符数(≤4)校验,替代原版按字节(UTF-8 下 3 汉字即 9 字节误判)。
- 随机配发用 randrange(len(list)),修复原版 int(rand($#list)) 最后一项永不出现的 off-by-one。
- "死亡后 2 小时禁注册"以服务端死亡时间生效(原版 cookie 恒写 0 从未生效)。
"""
import datetime
import random
import re

from .. import config, security
from ..engine.news import add_news

HALF_ALNUM = re.compile(r"[A-Za-z0-9]+")   # 全串半角英数字(见下方 [FIX])
FORBIDDEN_CHARS = re.compile(r"[_ ,;<>(){}&/.]")


class RegisterError(Exception):
    def __init__(self, msg_key, **kw):
        self.key = msg_key
        self.params = kw
        super().__init__(msg_key)


def current_game(conn):
    return conn.execute(
        "SELECT * FROM games WHERE status LIKE 'running%' ORDER BY id DESC LIMIT 1").fetchone() \
        or conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()


def get_running_game(conn):
    return conn.execute("SELECT * FROM games WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()


def validate_register(conn, game, form, texts):
    """注册校验链(原版 regist.cgi MAIN 前置 + REGIST 校验)。返回整理后的字段。"""
    err = texts["register_errors"]
    f_name = (form.get("f_name") or "").strip()
    l_name = (form.get("l_name") or "").strip()
    sex = form.get("sex") or ""
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    msg = (form.get("msg") or "").strip()
    dmes = (form.get("dmes") or "").strip()
    com = (form.get("com") or "").strip()

    if game is None:
        raise RegisterError("closed")
    # 报名截止:游戏结束 或 ar >= limit*3+1
    if game["status"] != "running" or game["forbidden_count"] >= config.LIMIT * 3 + 1:
        raise RegisterError("closed")

    # [FIX] 死亡 2 小时禁注册(按同用户名历史死亡记录,服务端生效)
    now = datetime.datetime.now().timestamp()
    prev = conn.execute(
        "SELECT no_reentry_until FROM players WHERE game_id=? AND username=? AND status='dead'",
        (game["id"], username)).fetchone()
    if prev and prev["no_reentry_until"] and prev["no_reentry_until"] > now:
        t = datetime.datetime.fromtimestamp(prev["no_reentry_until"])
        raise RegisterError("dead_reentry",
                            time=t.strftime("%Y/%m/%d %H:%M:%S"))

    # 人数上限(每性别 5 班×21 人)
    m = conn.execute("SELECT COUNT(*) c FROM players WHERE game_id=? AND sex='男生'",
                     (game["id"],)).fetchone()["c"]
    f = conn.execute("SELECT COUNT(*) c FROM players WHERE game_id=? AND sex='女生'",
                     (game["id"],)).fetchone()["c"]
    if m + f >= config.MAXMEM:
        raise RegisterError("full", max=config.MAXMEM)

    # 姓名校验([FIX] 按字符数,≤4 汉字)
    if not f_name:
        raise RegisterError("f_name_empty")
    if len(f_name) > 4:
        raise RegisterError("f_name_len")
    if HALF_ALNUM.search(f_name):
        raise RegisterError("f_name_half")
    if not l_name:
        raise RegisterError("l_name_empty")
    if len(l_name) > 4:
        raise RegisterError("l_name_len")
    if HALF_ALNUM.search(l_name):
        raise RegisterError("l_name_half")
    if sex not in ("男生", "女生"):
        raise RegisterError("no_sex")

    # ID/密码校验(对等原版意图:半角英数字;≤8/≤32、ID≠密码)
    # [FIX] 原实现 search() 只查"含至少一个英数字",abc!@#$ / abc密码 / 带控制字符
    # 均可放行,与"半角"承诺不符;现收紧为 fullmatch 全串半角英数字。
    # 禁字符表先查,让"含禁字符"拿到更具体的提示。
    if len(username) > 8:
        raise RegisterError("id_len")
    if not username:
        raise RegisterError("id_empty")
    if FORBIDDEN_CHARS.search(username):
        raise RegisterError("id_forbidden")
    if not HALF_ALNUM.fullmatch(username):
        raise RegisterError("id_half")
    if not password:
        raise RegisterError("pw_empty")
    # [安全] 上限放宽到 32(原版 8 位半角口令空间过小,易被爆破)
    if len(password) > 32:
        raise RegisterError("pw_len")
    # [安全] 下限 4 位(原为 1 位即可注册;有登录锁定兜底,但仍收紧口令空间)
    if len(password) < 4:
        raise RegisterError("pw_min")
    if FORBIDDEN_CHARS.search(password):
        raise RegisterError("pw_forbidden")
    if not HALF_ALNUM.fullmatch(password):
        raise RegisterError("pw_half")
    if username == password:
        raise RegisterError("id_eq_pw")
    if len(msg) > 32:
        raise RegisterError("msg_len")
    if len(dmes) > 32:
        raise RegisterError("dmes_len")
    if len(com) > 32:
        raise RegisterError("com_len")

    # 重复检查:同 ID 恒禁;同姓同名且未死禁
    dup = conn.execute(
        "SELECT status FROM players WHERE game_id=? AND (username=? OR "
        "(f_name=? AND l_name=? AND sex=? AND status!='dead'))",
        (game["id"], username, f_name, l_name, sex)).fetchone()
    if dup:
        raise RegisterError("dup")

    # 分班(对等原版 memberfile:m/f/mc/fc)
    if sex == "男生":
        if m // config.MANMAX >= config.CLMAX:
            raise RegisterError("male_full")
    else:
        if f // config.MANMAX >= config.CLMAX:
            raise RegisterError("female_full")

    return dict(f_name=f_name, l_name=l_name, sex=sex, username=username,
                password=password, msg=msg, dmes=dmes, com=com)


def _esc(text):
    """玩家文本落库前转义(对等原版 DECODE)。"""
    from ..engine.util import esc
    return esc((text or "").strip()[:32])


def create_player(conn, game, data, rng=None, texts=None):
    """写入新玩家(对等 regist.cgi REGIST 216-281)。返回新玩家 id。"""
    rng = rng or random.Random()
    weapons = config.load_seed("weapons.json")
    personal = config.load_seed("personal_items.json")

    # [FIX] randrange 全列表均匀(原版 int(rand($#list)) 抽不到最后一项)
    wep = rng.choice(weapons)
    st = rng.choice(personal)

    sex = data["sex"]
    same_sex = conn.execute(
        "SELECT COUNT(*) c FROM players WHERE game_id=? AND sex=?", (game["id"], sex)
    ).fetchone()["c"]
    class_no = same_sex % config.MANMAX + 1
    class_name = config.CLASSES[same_sex // config.MANMAX]

    # 社团(11 选 1)
    club, prof_key = config.CLUBS[rng.randrange(len(config.CLUBS))]

    items = [
        dict(name="面包", code="SH", eff=20, uses=2),
        dict(name="水", code="HH", eff=15, uses=2),
        dict(name=wep["name"], code=wep["code"], eff=wep["att"], uses=wep["uses"]),
    ]
    # 配发弹药仅限枪/弓系(WG/WA/WGB/WAB);防弹背心(ADB)等不配(对等 regist.cgi)
    if "WG" in wep["code"]:
        items.append(dict(name="子弹", code="Y", eff=12, uses=1))
        items.append(dict(name=st["name"], code=st["code"], eff=st["eff"], uses=st["uses"]))
    elif "WA" in wep["code"]:
        items.append(dict(name="箭", code="Y", eff=12, uses=1))
        items.append(dict(name=st["name"], code=st["code"], eff=st["eff"], uses=st["uses"]))
    else:
        items.append(dict(name=st["name"], code=st["code"], eff=st["eff"], uses=st["uses"]))
    while len(items) < 6:
        items.append(None)

    import json
    now = datetime.datetime.now().timestamp()
    hit = rng.randrange(20) + 30
    profs = {f"prof_{k}": 0 for k in ("wn", "wp", "wa", "wg", "we", "wc", "wd", "wb", "wf", "ws")}
    if prof_key:
        profs[f"prof_{prof_key}"] = config.BASE   # 社团初始熟练度 20
    cur = conn.execute(
        "INSERT INTO players(game_id, username, pass_hash, f_name, l_name, sex, "
        "class_name, class_no, club, att, deff, hit, mhit, sta, place, items, "
        "prof_wn, prof_wp, prof_wa, prof_wg, prof_we, prof_wc, prof_wd, prof_wb, "
        "prof_wf, prof_ws, msg, dmes, com, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (game["id"], data["username"], security.hash_password(data["password"]),
         data["f_name"], data["l_name"], sex, class_name, class_no, club,
         rng.randrange(5) + 8, rng.randrange(5) + 8, hit, hit, config.MAXSTA, 0,
         json.dumps(items, ensure_ascii=False),
         profs["prof_wn"], profs["prof_wp"], profs["prof_wa"], profs["prof_wg"],
         profs["prof_we"], profs["prof_wc"], profs["prof_wd"], profs["prof_wb"],
         profs["prof_wf"], profs["prof_ws"],
         _esc(data["msg"]), _esc(data["dmes"]), _esc(data["com"]), now))
    pid = cur.lastrowid

    add_news(conn, game["id"], now, "ENTRY", subject_id=pid,
             extra=dict(club=club),
             text=f"{data['f_name']} {data['l_name']}({class_name} {sex}{class_no}号,{club})办理了入学手续。")
    return pid


# --- 会话 ---

SESSION_COOKIE = "br_session"
SESSION_DAYS = config.__dict__.get("SAVE_LIMIT", 7)


def create_session(conn, game_id, player_id=None, is_admin=0):
    token = security.new_token()
    now = datetime.datetime.now().timestamp()
    conn.execute(
        "INSERT INTO sessions(token, game_id, player_id, is_admin, created_at, expires_at) "
        "VALUES(?,?,?,?,?,?)",
        (token, game_id, player_id, is_admin, now, now + SESSION_DAYS * 86400))
    return token


def session_player(conn, token):
    """返回 (session_row, player_row) 或 (None, None)。过期会话顺手删除。"""
    if not token:
        return None, None
    s = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    if not s:
        return None, None
    if s["expires_at"] < datetime.datetime.now().timestamp():
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None, None
    if s["player_id"] is None:
        return s, None
    p = conn.execute("SELECT * FROM players WHERE id=?", (s["player_id"],)).fetchone()
    return s, p


def delete_session(conn, token):
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def login(conn, username, password):
    """对等 IDCHK:返回 (token, player, error_text_key)。

    查找顺序:最新运行局 → 最新局(后者覆盖终局后的死亡/结局画面登录;
    亦防旧局残留 running 状态时把查找挡在空局上)。
    """
    running = get_running_game(conn)
    latest = current_game(conn)
    if running is None and latest is None:
        return None, None, "no_game"
    p = game = None
    for g in (running, latest):
        if g is None:
            continue
        row = conn.execute("SELECT * FROM players WHERE game_id=? AND username=?",
                           (g["id"], username)).fetchone()
        if row is not None:
            p, game = row, g
            break
    # 开新局会清除旧局玩家:查无此 ID → 学员不存在(与新局注册流程衔接)
    if p is None:
        return None, None, "no_id"
    if not security.verify_password(password, p["pass_hash"]):
        return None, None, "wrong_pass"
    return create_session(conn, game["id"], p["id"]), p, None
