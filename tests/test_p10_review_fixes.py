"""第二轮审查修复回归测试(2026-08-19):
管理密码/限速、尸体发现率、并发快照竞态、loot 空槽、∞ 耐久、全灭结局。
"""
import datetime

import pytest


@pytest.fixture()
def game2p(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    for uname, fname, sex in (("k1", "攻", "男生"), ("v1", "受", "女生")):
        client.post("/api/auth/register", json=dict(
            username=uname, password="pass1234", f_name=fname, l_name="方",
            sex=sex, msg="", dmes="", com=""))
    # 挪离分校(注册默认在分校,与守关 NPC 混战会干扰用例)
    conn = _db()
    conn.execute("UPDATE players SET place=2 WHERE username IN ('k1','v1')")
    conn.commit()
    conn.close()
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


def _kill_v1_by_k1(client):
    """k1 探索+攻击直至击杀 v1(交战锁要求守方交替行动清 bid),返回最后响应。
    强化 k1/弱化 v1,排除被伏击反杀的随机性。"""
    conn = _db()
    conn.execute("UPDATE players SET hit=5, mhit=5, att=0, deff=0 "
                 "WHERE username='v1'")
    conn.execute("UPDATE players SET hit=500, mhit=500, att=40, deff=40 "
                 "WHERE username='k1'")
    conn.commit()
    conn.close()
    _login(client, "k1")
    for _ in range(80):
        res = _cmd(client, "explore")
        if res["view"] == "main":
            # 伏击未分胜负会互设交战锁:让 v1 行动清锁,保证其仍是遭遇候选
            _login(client, "v1")
            _cmd(client, "change_msg", msg="哼")
            _login(client, "k1")
        if res["view"] == "battle":
            tid = res["extras"]["battle"]["target"]["id"]
            for _ in range(40):
                res = _cmd(client, "attack", target_id=tid)
                if res["view"] in ("loot", "dead"):
                    return res
                # 守方行动清自身交战锁,攻方才可继续攻击(对等原版机制)
                _login(client, "v1")
                _cmd(client, "change_msg", msg="哼")
                _login(client, "k1")
        if res["view"] in ("loot", "dead"):
            return res
    pytest.fail("80 次探索未分胜负")


# --- 安全 ---

def test_admin_login_disabled_without_password(client, monkeypatch):
    """未设置 BR_ADMIN_PASS 时管理登录整体禁用(503)。"""
    import app.config as config
    monkeypatch.setattr(config, "ADMIN_PASSWORD", None)
    r = client.post("/api/admin/login", json=dict(password="anything"))
    assert r.status_code == 503


def test_admin_login_lockout(client):
    """管理登录连续失败 5 次后锁定(429)。"""
    for _ in range(5):
        r = client.post("/api/admin/login", json=dict(password="wrong"))
        assert r.status_code == 401
    r = client.post("/api/admin/login", json=dict(password="790923"))
    assert r.status_code == 429


def test_login_lockout_and_no_enumeration(game2p):
    """登录失败 5 次锁定;用户不存在与密码错误可区分(产品需求)。"""
    a = client_post_login(game2p, "nobody", "x")
    b = client_post_login(game2p, "k1", "x")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"]["key"] == "no_id"
    assert "请注册" in a.json()["detail"]["message"]
    assert b.json()["detail"]["key"] == "wrong_pass"
    # 连续失败直至锁定(两种失败都计入;u:k1 已因上面的检查计 1 次)
    locked = False
    for _ in range(6):
        r = client_post_login(game2p, "k1", "badpass")
        if r.status_code == 429:
            locked = True
            break
        assert r.status_code == 401
        assert r.json()["detail"]["key"] == "wrong_pass"
    assert locked, "6 次失败后仍未锁定"


def client_post_login(client, username, password):
    client.cookies.clear()
    return client.post("/api/auth/login", json=dict(username=username, password=password))


def test_register_rate_limit(game2p):
    """同一 IP 每小时最多 20 次注册。"""
    for i in range(20 - 2):        # fixture 已注册 2 个
        r = game2p.post("/api/auth/register", json=dict(
            username=f"u{i}", password="pass1234", f_name="批", l_name="量",
            sex="男生", msg="", dmes="", com=""))
        if r.status_code == 400:   # 撞姓名/上限等业务拒绝不计
            continue
        assert r.status_code == 200, r.text
    r = game2p.post("/api/auth/register", json=dict(
        username="overflow", password="pass1234", f_name="超", l_name="限",
        sex="男生", msg="", dmes="", com=""))
    assert r.status_code == 429


def test_password_longer_than_8_accepted(client):
    """密码上限放宽到 32。"""
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    r = client.post("/api/auth/register", json=dict(
        username="longpw", password="a" * 32, f_name="长", l_name="密",
        sex="男生", msg="", dmes="", com=""))
    assert r.status_code == 200, r.text


# --- 引擎 ---

def test_corpse_find_rate_not_always(game2p):
    """尸体发现率为 10%,而非修复前的 100%。"""
    _kill_v1_by_k1(game2p)
    found = 0
    for _ in range(60):
        res = _cmd(game2p, "explore")
        if "尸体" in res["log"] + res.get("inbox", ""):
            found += 1
    # 期望约 6 次(10%);修复前为 60 次(100%)。放宽上界排除偶发噪声。
    assert found < 30, f"尸体发现率异常:60 次探索发现 {found} 次"


def test_loot_empty_slot_guard(game2p):
    """对空手尸体夺武器 → 放弃拾取,不生成"空手"物品。"""
    res = _kill_v1_by_k1(game2p)
    tid = res["extras"]["loot"]["target"]["id"]
    conn = _db()
    conn.execute("UPDATE players SET wep_name='空手', wep_code='WP', wep_att=0 "
                 "WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    # 腾出至少一个背包位(满包检查先于空槽守卫)
    while None not in game2p.get("/api/game/state").json()["player"]["items"][:5]:
        items = game2p.get("/api/game/state").json()["player"]["items"]
        idx = next(i for i, it in enumerate(items[:5]) if it is not None)
        _cmd(game2p, "drop_item", slot=idx)
    res = _cmd(game2p, "loot", target_id=tid, slot="weapon")
    assert "放弃了拾取" in res["log"]
    items = game2p.get("/api/game/state").json()["player"]["items"]
    assert all(it is None or it["name"] != "空手" for it in items)


def test_poison_infinite_uses(game2p):
    """uses=None(∞)毒药投毒后不消失。"""
    _login(game2p, "k1")
    conn = _db()
    row = conn.execute("SELECT items FROM players WHERE username='k1'").fetchone()
    items = json_loads(row["items"])
    items[0] = dict(name="毒药", code="DS", eff=0, uses=None)
    items[1] = dict(name="面包", code="SH", eff=20, uses=2)
    conn.execute("UPDATE players SET items=? WHERE username='k1'",
                 (json_dumps(items),))
    conn.commit()
    conn.close()
    _cmd(game2p, "poison", slot=1)
    items = game2p.get("/api/game/state").json()["player"]["items"]
    poison = [it for it in items if it and it["name"] == "毒药"]
    assert poison, "∞ 毒药一次投毒即耗尽(回归)"


def json_loads(s):
    import json
    return json.loads(s)


def json_dumps(o):
    import json
    return json.dumps(o, ensure_ascii=False)


def test_stale_snapshot_race(game2p):
    """命令事务外的并发修改不得被陈旧快照覆盖(审查竞态修复)。"""
    _login(game2p, "k1")
    # 模拟:API 层在事务外读取玩家行(hit=31),另一连接并发把 hit 写为 5 提交
    import app.db as db
    import app.engine.game as engine
    import app.config as config

    conn = db.connect(config.DB_PATH)
    player = conn.execute("SELECT * FROM players WHERE username='k1'").fetchone()
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()

    other = db.connect(config.DB_PATH)
    other.execute("UPDATE players SET hit=5 WHERE username='k1'")
    other.commit()
    other.close()

    import random
    texts = config.load_seed("texts.json")
    engine.run_command(conn, dict(game), dict(player), "change_msg",
                       dict(msg="hi"), random.Random(),
                       datetime.datetime.now().timestamp(), texts)
    conn.close()

    check = _db()
    hit = check.execute("SELECT hit FROM players WHERE username='k1'").fetchone()["hit"]
    check.close()
    assert hit == 5, f"并发写入被陈旧快照覆盖:hit={hit}(期望 5)"


def test_admin_execute_no_game(client):
    """未开局时处刑 → 友好 400(原为 500)。"""
    client.post("/api/admin/login", json=dict(password="790923"))
    r = client.post("/api/admin/execute", json=dict(player_id=1, message=""))
    assert r.status_code == 400


def test_admin_execute_last_player_ends_game(game2p):
    """处刑最后一名存活玩家 → 立即终局(不再等玩家请求触发)。"""
    game2p.post("/api/admin/login", json=dict(password="790923"))
    conn = _db()
    # 移除 NPC 的非政府干扰:政府系不计存活;直接杀掉另一名玩家
    other = conn.execute("SELECT id FROM players WHERE username='v1'").fetchone()
    conn.execute("UPDATE players SET hit=0, status='dead' WHERE id=?", (other["id"],))
    conn.commit()
    conn.close()
    k1 = _db().execute("SELECT id FROM players WHERE username='k1'").fetchone()
    r = game2p.post("/api/admin/execute", json=dict(player_id=k1["id"], message="违规"))
    assert r.status_code == 200, r.text
    status = _db().execute(
        "SELECT status FROM games ORDER BY id DESC LIMIT 1").fetchone()["status"]
    assert status == "finished_win", f"处刑最后一人后游戏状态={status}"


def test_dead_player_login_across_games(game2p):
    """同局死亡 → 死亡画面;开新局清除旧局用户 → 学员不存在请注册。"""
    conn = _db()
    conn.execute("UPDATE players SET hit=0, status='dead', death_type='被杀' "
                 "WHERE username='k1'")
    conn.commit()
    conn.close()
    # 同局死亡 → 200 + dead 标记(死亡画面可进入)
    r = client_post_login(game2p, "k1", "pass1234")
    assert r.status_code == 200
    assert r.json()["dead"] is True
    # 开新局 → 旧局玩家全部清除,登录提示学员不存在
    game2p.post("/api/admin/login", json=dict(password="790923"))
    game2p.post("/api/admin/new_game")
    remain = _db().execute(
        "SELECT COUNT(*) c FROM players WHERE username='k1'").fetchone()["c"]
    assert remain == 0, "开新局未清除旧局玩家"
    r = client_post_login(game2p, "k1", "pass1234")
    assert r.status_code == 401
    assert r.json()["detail"]["key"] == "no_id"
    assert "请注册" in r.json()["detail"]["message"]
    # 新局可重新注册同名 ID
    game2p.post("/api/auth/register", json=dict(
        username="k1", password="pass1234", f_name="新", l_name="员",
        sex="男生", msg="", dmes="", com=""))


def test_dead_login_with_stale_running_game(game2p):
    """终局后的死亡角色仍可登录:即使旧局残留 running 状态也不得挡住查找。"""
    conn = _db()
    conn.execute("UPDATE players SET hit=0, status='dead', death_type='被杀' "
                 "WHERE username='k1'")
    # 模拟脏数据:更早的局残留 running(开新局作废机制上线前的遗留)
    conn.execute("UPDATE games SET status='running' "
                 "WHERE id=(SELECT MIN(id) FROM games)")
    conn.commit()
    conn.close()
    r = client_post_login(game2p, "k1", "pass1234")
    assert r.status_code == 200, r.text
    assert r.json()["dead"] is True


def test_new_game_abandons_old_running(client):
    """开新局后,旧局不得残留 running 状态。"""
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    client.post("/api/admin/new_game")
    conn = _db()
    statuses = [r["status"] for r in conn.execute(
        "SELECT status FROM games ORDER BY id").fetchall()]
    conn.close()
    assert statuses[-1] == "running"
    assert "running" not in statuses[:-1], statuses


def test_js_syntax():
    """前端 JS 语法检查(node --check;views.js 曾因多余括号整体解析失败)。"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用")
    import glob
    import os
    js_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "static", "js")
    for f in glob.glob(os.path.join(js_dir, "*.js")):
        r = subprocess.run([node, "--check", f], capture_output=True, text=True)
        assert r.returncode == 0, f"{f}: {r.stderr}"


def test_wipeout_ending(game2p):
    """全员死亡 → 游戏终局(无优胜者),不再永久卡在 running。"""
    conn = _db()
    # 两人同置当前禁区,推进日界 → 双双处决 → mem==0
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    import json as _json
    order = _json.loads(game["forbidden_order"])
    conn.execute("UPDATE players SET place=? WHERE username IN ('k1','v1')",
                 (order[0],))
    tomorrow = datetime.datetime.now().timestamp() + 86400
    conn.execute("UPDATE games SET last_tick_day=? WHERE id=?",
                 ("2000-01-01", game["id"]))
    conn.commit()
    conn.close()

    _login(game2p, "k1")
    import app.config as config
    import app.db as db
    import app.services.state as state_svc
    conn = db.connect(config.DB_PATH)
    from app.services import auth as auth_svc
    token = None
    # 直接推进世界+胜负检查(等价于任一玩家请求触发的路径)
    import random
    texts = config.load_seed("texts.json")
    game = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    from app.engine import time_utils
    time_utils.advance_world(conn, dict(game), tomorrow, texts, random.Random())
    time_utils.check_victory(conn, dict(game), tomorrow, texts, random.Random())
    status = conn.execute("SELECT status FROM games ORDER BY id DESC LIMIT 1"
                          ).fetchone()["status"]
    conn.close()
    assert status == "finished_win", f"全灭后游戏状态={status}(期望终局)"


def _reg(client, username, password):
    """注册辅助:返回 (status, error_key)。"""
    client.cookies.clear()
    r = client.post("/api/auth/register", json=dict(
        username=username, password=password, f_name="测", l_name="试",
        sex="男生", msg="", dmes="", com=""))
    key = r.json()["detail"]["key"] if r.status_code == 400 else None
    return r.status_code, key


def test_register_password_strict_halfwidth(client):
    """[FIX] 密码/ID 须全串半角英数字:含符号、全角、控制字符一律拒绝。"""
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    # 混合符号/全角/空格/控制字符:原 search() 放行,fullmatch() 必须拒绝
    for pw in ("abc!@#$", "abc++--", "abc密码", "abc\nx", "abcd."):
        st, key = _reg(client, "pwtest1", pw)
        assert (st, key) in ((400, "pw_half"), (400, "pw_forbidden")), (pw, st, key)
    for uid in ("id!bad", "ID密码", "ab\nid"):
        st, key = _reg(client, uid, "pass1234")
        assert (st, key) in ((400, "id_half"), (400, "id_forbidden")), (uid, st, key)
    # 纯半角英数字(含 32 位)仍可注册
    st, _ = _reg(client, "okuser1", "a" * 32)
    assert st == 200
