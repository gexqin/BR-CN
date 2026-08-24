"""2026-08-24 第四轮审查修复回归测试:
搜刮尸体发现守卫、ADB 饰品装备分支、优胜者状态防覆盖、黑客失败文案。
"""
import json

import pytest


@pytest.fixture()
def game2p(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    for username, f_name in (("k1", "甲"), ("k2", "乙")):
        client.post("/api/auth/register", json=dict(
            username=username, password="pass1234", f_name=f_name, l_name="试",
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


def _ids(conn):
    return {r["username"]: r["id"] for r in conn.execute(
        "SELECT username, id FROM players WHERE username IN ('k1','k2')").fetchall()}


# --- 45:cmd_loot 未发现尸体守卫 ---

def _make_corpse(conn, victim_id, found_by, corpse_found):
    conn.execute(
        "UPDATE players SET place=3, hit=0, status='dead', corpse_found=?, "
        "found_by=?, bid=NULL, wep_name='日本刀', wep_code='WNS', wep_att=10, "
        "wep_uses=NULL WHERE id=?", (corpse_found, found_by, victim_id))


def test_loot_undiscovered_corpse_blocked(game2p):
    """同地第三人凭 target_id 搜刮未发现尸体(corpse_found=0、found_by=他人)
    → 400(原为放行,绕过 cmd_attack 已修的发现掷骰)。"""
    conn = _db()
    ids = _ids(conn)
    _make_corpse(conn, ids["k2"], found_by=ids["k1"] + 100, corpse_found=0)
    # 清空 k1 背包(注册随机到枪/弓系时背包 5 格全满,满包分支提前返回 200)
    conn.execute("UPDATE players SET place=3, items=? WHERE id=?",
                 (json.dumps([None] * 6), ids["k1"]))
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    r = game2p.post("/api/game/command", json=dict(
        cmd="loot", args=dict(target_id=ids["k2"], slot="weapon")))
    assert r.status_code == 400, "未发现尸体被直接搜刮(回归)"


def test_loot_killer_and_discovered_corpse_allowed(game2p):
    """击杀者(found_by=我)与已发现尸体(corpse_found=1)仍可搜刮(对等 cmd_attack)。"""
    conn = _db()
    ids = _ids(conn)
    # 清空 k1 背包腾位
    conn.execute("UPDATE players SET place=3, items=? WHERE id=?",
                 (json.dumps([None] * 6), ids["k1"]))
    _make_corpse(conn, ids["k2"], found_by=ids["k1"], corpse_found=0)
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    res = _cmd(game2p, "loot", target_id=ids["k2"], slot="weapon")
    assert "得到了" in res["log"]

    conn = _db()
    _make_corpse(conn, ids["k2"], found_by=ids["k1"] + 100, corpse_found=1)
    conn.execute("UPDATE players SET wep_name='柴刀', wep_code='WN', wep_att=8 "
                 "WHERE id=?", (ids["k2"],))
    conn.commit()
    conn.close()
    res = _cmd(game2p, "loot", target_id=ids["k2"], slot="weapon")
    assert "得到了" in res["log"]


# --- 46:ADB(护腹 AD 系饰品)装备位次序 ---

def test_equip_adb_goes_to_accessory_slot(game2p):
    """防弹背心(ADB)装备 → 饰品位 5 号(原被 "DB" in code 分支误穿进身体槽,
    致 deftreat 相性/腹部代伤永不生效)。"""
    conn = _db()
    ids = _ids(conn)
    items = [dict(name="防弹背心", code="ADB", eff=5, uses=3),
             None, None, None, None, None]
    conn.execute("UPDATE players SET items=? WHERE id=?",
                 (json.dumps(items, ensure_ascii=False), ids["k1"]))
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    _cmd(game2p, "use_item", slot=0)
    st = game2p.get("/api/game/state").json()
    acc = st["player"]["accessory"]
    assert acc and acc["code"] == "ADB", f"ADB 未进饰品位:{acc}"
    assert st["player"]["body_armor"]["name"] == "内衣", "ADB 误占身体槽(回归)"
    assert st["player"]["items"][0] is None


# --- 47:优胜者状态不被 flush 覆盖 ---

def test_winner_status_survives_flush(game2p):
    """最后存活者发任意命令触发优胜 → 落库 status='won'/win_flag=1
    (原 flush 用陈旧快照覆盖回 alive/0)。"""
    conn = _db()
    g = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    ids = _ids(conn)
    conn.execute("UPDATE games SET forbidden_count=11 WHERE id=?", (g["id"],))
    conn.execute("UPDATE players SET hit=0, status='dead' WHERE id=?", (ids["k2"],))
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    _cmd(game2p, "change_msg", msg="赢了")
    conn = _db()
    w = conn.execute("SELECT status, win_flag FROM players WHERE id=?",
                     (ids["k1"],)).fetchone()
    conn.close()
    assert w["status"] == "won" and w["win_flag"] == 1, \
        f"优胜者状态被覆盖:{dict(w)}(回归)"


# --- 48:黑客失败文案 ---

def test_hack_failure_message(game2p, monkeypatch):
    """黑客失败提示为「黑客程序失败了。」(原文案系翻译错误「成功?」)。"""
    from app.engine import util
    monkeypatch.setattr(util, "dice", lambda rng, n: 5)   # 5:失败且不触发损坏
    conn = _db()
    ids = _ids(conn)
    items = [dict(name="笔记本电脑", code="Y", eff=1, uses=3),
             None, None, None, None, None]
    conn.execute("UPDATE players SET club='田径部', items=? WHERE id=?",
                 (json.dumps(items, ensure_ascii=False), ids["k1"]))
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    res = _cmd(game2p, "hack")
    assert "黑客程序失败了" in res["log"]
    assert "成功" not in res["log"]
