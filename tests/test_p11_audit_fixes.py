"""2026-08-24 GitHub 上传前后第三轮审查修复回归测试:
管理登录非 ASCII、备份空库、限速内存上限、esc 单引号、密码下限、
日志清理、∞ 耐久堆叠、注册事务内复查对局。
"""
import datetime
import json
import time

import pytest


@pytest.fixture()
def game1p(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    client.post("/api/auth/register", json=dict(
        username="k1", password="pass1234", f_name="甲", l_name="一",
        sex="男生", msg="", dmes="", com=""))
    return client


def _login(client, username):
    client.cookies.clear()
    r = client.post("/api/auth/login", json=dict(username=username, password="pass1234"))
    assert r.status_code == 200, r.text


def _cmd(client, cmd, **args):
    r = client.post("/api/game/command", json=dict(cmd=cmd, args=args))
    assert r.status_code == 200, r.text
    return r.json()


def _db():
    import app.config as config
    import app.db as db
    return db.connect(config.DB_PATH)


def _items(client):
    return client.get("/api/game/state").json()["player"]["items"]


# --- 37:管理登录非 ASCII 密码 ---

def test_admin_login_non_ascii_wrong_password(client):
    """含中文的管理密码尝试 → 401(原为 TypeError → 500)。"""
    r = client.post("/api/admin/login", json=dict(password="错误密码试错"))
    assert r.status_code == 401, r.text


def test_admin_login_non_ascii_configured_password(client, monkeypatch):
    """BR_ADMIN_PASS 本身含非 ASCII 时,正确密码可登录(原实现永久 500)。"""
    import app.config as config
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "管理密码123")
    r = client.post("/api/admin/login", json=dict(password="管理密码123"))
    assert r.status_code == 200, r.text


# --- 38:管理备份空库 ---

def test_admin_backup_no_game(client):
    """未开局时备份 → 友好 400(原为 500)。"""
    client.post("/api/admin/login", json=dict(password="790923"))
    r = client.post("/api/admin/backup")
    assert r.status_code == 400


# --- 39:限速字典内存上限 ---

def test_ratelimit_prunes_stale_keys(client, monkeypatch):
    """超限时先清已失效(锁定过期)记录,活跃锁定不受影响。"""
    from app import ratelimit
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 5)
    ratelimit._attempts.clear()
    for i in range(4):      # 已过期锁定 → 可清
        ratelimit._attempts[f"stale{i}"] = [3, time.time() - 1]
    ratelimit._attempts["live"] = [3, time.time() + 999]   # 活跃锁定 → 保留
    ratelimit.record_fail("newkey")
    assert "live" in ratelimit._attempts, "活跃锁定被误清"
    assert "newkey" in ratelimit._attempts
    assert "stale0" not in ratelimit._attempts, "过期记录未被清理"
    assert len(ratelimit._attempts) <= 5


def test_ratelimit_flood_fallback_clears(client, monkeypatch):
    """灌键攻击(全部为活跃键,无法增量清理)→ 整体清空兜底,内存有界。"""
    from app import ratelimit
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 5)
    ratelimit._attempts.clear()
    for i in range(5):
        ratelimit._attempts[f"k{i}"] = [3, time.time() + 999]
    ratelimit.record_fail("flood")
    assert len(ratelimit._attempts) < 5, "灌键场景未触发兜底清空"


def test_ratelimit_counts_pruned(client, monkeypatch):
    """_counts 同样有界:过期窗口记录被清。"""
    from app import ratelimit
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 5)
    ratelimit._counts.clear()
    for i in range(5):      # 窗口起点 2 小时前(> 最大注册窗口 1h)→ 失效
        ratelimit._counts[f"old{i}"] = [time.time() - 7200, 1]
    assert ratelimit.allow("fresh", limit=1, window_secs=3600)
    assert "old0" not in ratelimit._counts
    assert len(ratelimit._counts) <= 5


# --- 40:esc 单引号 ---

def test_esc_escapes_single_quote():
    from app.engine.util import esc
    assert esc("a'b\"c<d>&") == "a&#39;b&quot;c&lt;d&gt;&amp;"


# --- 41:密码最小长度 ---

def _reg(client, username, password):
    client.cookies.clear()
    r = client.post("/api/auth/register", json=dict(
        username=username, password=password, f_name="测", l_name="试",
        sex="男生", msg="", dmes="", com=""))
    key = r.json()["detail"]["key"] if r.status_code == 400 else None
    return r.status_code, key


def test_register_password_min_length(client):
    """密码 <4 位 → pw_min;恰 4 位可注册。"""
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    st, key = _reg(client, "minpw1", "abc")
    assert (st, key) == (400, "pw_min")
    st, key = _reg(client, "minpw2", "abcd")
    assert st == 200, (st, key)


# --- 42:日界推进清理过期感知/会话 ---

def test_advance_world_purges_expired_rows(game1p):
    """advance_world 清理 expire_at 过期的 sense_logs 与 sessions;未过期保留。"""
    import random
    import app.config as config
    from app.engine import time_utils
    conn = _db()
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    now = datetime.datetime.now().timestamp()
    conn.execute(
        "INSERT INTO sense_logs(game_id, at, expire_at, scope, place, kind, "
        "player_id) VALUES(?,?,?,?,?,?,?)",
        (game["id"], now - 100, now - 50, "place", 1, "gunshot", 1))
    conn.execute(
        "INSERT INTO sense_logs(game_id, at, expire_at, scope, place, kind, "
        "player_id) VALUES(?,?,?,?,?,?,?)",
        (game["id"], now, now + 999, "island", None, "announce", 1))
    conn.execute(
        "INSERT INTO sessions(token, game_id, player_id, created_at, expires_at) "
        "VALUES('expired_tok', NULL, NULL, ?, ?)", (now - 100, now - 50))
    conn.execute(
        "INSERT INTO sessions(token, game_id, player_id, created_at, expires_at) "
        "VALUES('live_tok', NULL, NULL, ?, ?)", (now, now + 999))
    conn.execute("UPDATE games SET last_tick_day='2000-01-01' WHERE id=?",
                 (game["id"],))
    conn.commit()
    tomorrow = now + 86400
    # "存活"感知的过期时间须晚于推进时刻(清理以推进时刻为基准)
    conn.execute("UPDATE sense_logs SET expire_at=? WHERE kind='announce'",
                 (tomorrow + 999,))
    conn.execute("UPDATE sessions SET expires_at=? WHERE token='live_tok'",
                 (tomorrow + 999,))
    conn.commit()
    texts = config.load_seed("texts.json")
    time_utils.advance_world(conn, dict(game), tomorrow, texts, random.Random())
    senses = conn.execute("SELECT COUNT(*) c FROM sense_logs").fetchone()["c"]
    sessions = [r["token"] for r in conn.execute("SELECT token FROM sessions")]
    conn.close()
    assert senses == 1, "过期感知日志未被清理"
    assert "live_tok" in sessions and "expired_tok" not in sessions


# --- 43:∞ 耐久堆叠合并 ---

def test_sort_pack_infinite_uses_merge(game1p):
    """两个 uses=None(∞)同类可堆叠物品整理合并 → 保持 ∞(原变为 0 耐久)。"""
    conn = _db()
    items = [dict(name="飞刀", code="WC", eff=5, uses=None),
             dict(name="飞刀", code="WC", eff=5, uses=None), None, None, None, None]
    conn.execute("UPDATE players SET items=? WHERE username='k1'",
                 (json.dumps(items, ensure_ascii=False),))
    conn.commit()
    conn.close()
    _login(game1p, "k1")
    _cmd(game1p, "sort_pack", a=0, b=1)
    items = _items(game1p)
    merged = [it for it in items if it and it["name"] == "飞刀"]
    assert len(merged) == 1, "同类物品未合并"
    assert merged[0]["uses"] is None, f"∞ 耐久合并后变 {merged[0]['uses']}(回归)"


# --- 44:注册事务内复查对局状态 ---

def test_register_rechecks_game_status_in_transaction(client, monkeypatch):
    """校验(事务外)与写入(事务内)之间对局被作废 → 事务内复查拦截,不再挂进死局。

    用 monkeypatch 绕过事务外校验,直接验证事务内复查路径。
    """
    from app.services import auth as auth_svc
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    conn = _db()
    conn.execute("UPDATE games SET status='abandoned', end_reason='开新局作废'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        auth_svc, "validate_register",
        lambda conn, game, form, texts: dict(
            f_name="竞", l_name="态", sex="女生", username="race1",
            password="pass1234", msg="", dmes="", com=""))
    r = client.post("/api/auth/register", json=dict(
        username="race1", password="pass1234", f_name="竞", l_name="态",
        sex="女生", msg="", dmes="", com=""))
    assert r.status_code == 400
    assert r.json()["detail"]["key"] == "closed"
    conn = _db()
    n = conn.execute("SELECT COUNT(*) c FROM players WHERE username='race1'"
                     ).fetchone()["c"]
    conn.close()
    assert n == 0, "已作废对局写入了玩家(竞态回归)"
