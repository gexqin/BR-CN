"""P4 战斗测试:双人对战全流程(遭遇/先制/被袭/死亡/搜刮/感知/新闻)。"""
import json

import pytest


@pytest.fixture()
def two_players(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    for uname, fname, sex in (("atta", "攻方", "男生"), ("defe", "守方", "女生")):
        client.post("/api/auth/register", json=dict(
            username=uname, password="pass1234", f_name=fname, l_name="员",
            sex=sex, msg="哼哼", dmes="怎么会", com=""))
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


def _setup_fight(hp=100, mhit=100, weapon=("日本刀", "WNS", 25, None), place=2):
    """双方放到同一地点、固定武器与血量,并清空背包前两格以便搜刮。"""
    conn = _db()
    for uname in ("atta", "defe"):
        row = conn.execute("SELECT items FROM players WHERE username=?", (uname,)).fetchone()
        items = json.loads(row["items"])
        items[0] = None
        items[1] = None
        conn.execute(
            "UPDATE players SET place=?, hit=?, mhit=?, wep_name=?, wep_code=?, "
            "wep_att=?, wep_uses=?, items=? WHERE username=?",
            (place, hp, mhit, weapon[0], weapon[1], weapon[2], weapon[3],
             json.dumps(items, ensure_ascii=False), uname))
    conn.close()


def test_preemptive_battle_to_death(two_players):
    _setup_fight(hp=30, mhit=30, weapon=("菜刀", "WNS", 15, None))
    _login(two_players, "atta")
    # 反复探索直到先制遭遇;被袭则让守方行动解锁后继续
    battle = None
    for _ in range(60):
        res = _cmd(two_players, "explore")
        if res["view"] == "battle":
            battle = res["extras"]["battle"]
            break
        if res["view"] in ("dead", "loot"):
            break
        if "突然袭了过来" in res["log"]:
            _login(two_players, "defe")
            _cmd(two_players, "change_msg", msg="哼")
            _login(two_players, "atta")
    if battle is None:
        # 60 次内未取得先制:可能被袭致死(合法结局)——验证后跳过后续
        st = two_players.get("/api/game/state").json()
        assert st["view"] in ("dead", "loot"), "60 次探索无任何遭遇"
        return
    tid = battle["target"]["id"]
    assert "被你发现了" in res["log"]

    # 交战锁:每交换一回合后,对方行动前不能再攻击 → 交替行动直到有人死
    outcome = None
    for _ in range(40):
        res = _cmd(two_players, "attack", target_id=tid, dengon="去死吧")
        if res["view"] == "loot":
            outcome = "win"
            break
        if res["view"] == "dead":
            outcome = "lose"
            break
        # 守方行动(清自身 bid,并反击/被袭由其探索触发——此处仅解锁)
        _login(two_players, "defe")
        _cmd(two_players, "change_msg", msg="哼")
        _login(two_players, "atta")
    assert outcome in ("win", "lose"), f"40 回合未分胜负:{outcome}"

    if outcome == "win":
        # [稳定性] 探索期间可能拾满背包:满包检查先于交战锁(顺序对等原版 WINGET),
        # 先丢 2 件腾位,确保第二次搜刮命中"击杀者仅一件"的交战锁分支
        items = two_players.get("/api/game/state").json()["player"]["items"]
        empties = items[:5].count(None)
        for i, it in enumerate(items[:5]):
            if empties >= 2:
                break
            if it is not None:
                _cmd(two_players, "drop_item", slot=i)
                empties += 1
        # 搜刮:夺武器
        slots = res["extras"]["loot"]["slots"]
        assert slots
        res = _cmd(two_players, "loot", target_id=tid,
                   slot=slots[0]["slot"] if isinstance(slots[0]["slot"], str) else str(slots[0]["slot"]))
        assert "得到了" in res["log"]
        # 第二次搜刮被拒(击杀者只能取一件)
        res = _cmd(two_players, "loot", target_id=tid, slot="body")
        assert "空虚" in res["log"]
        # 攻击方 kill+1
        conn = _db()
        killer = conn.execute("SELECT kill FROM players WHERE username='atta'").fetchone()
        conn.close()
        assert killer["kill"] == 1

    # 新闻含死亡记录
    r = two_players.get("/api/news")
    kinds = [n["kind"] for n in r.json()]
    assert any(k.startswith("DEATH") for k in kinds)


def test_ambush_and_counter(two_players):
    _setup_fight(hp=200, mhit=200, weapon=("球棒", "WB", 12, None))
    _login(two_players, "defe")
    engaged = None
    for _ in range(80):
        res = _cmd(two_players, "explore")
        if "突然袭了过来" in res["log"]:
            engaged = "ambush"
            break
        if res["view"] == "battle":
            engaged = "preempt"
            break
        if res["view"] in ("dead", "loot"):
            engaged = "kill"
            break
    assert engaged, "80 次探索未发生任何遭遇"
    if engaged == "preempt":
        _cmd(two_players, "attack",
             target_id=res["extras"]["battle"]["target"]["id"])
    # 交战后双方互设交战锁
    conn = _db()
    rows = conn.execute("SELECT username, bid FROM players WHERE username IN ('atta','defe')").fetchall()
    conn.close()
    assert all(r["bid"] for r in rows)


def test_bid_lock(two_players):
    """交战锁:被攻击者未行动前不能再被同一人发现。"""
    _setup_fight()
    _login(two_players, "atta")
    for _ in range(80):
        res = _cmd(two_players, "explore")
        if res["view"] == "battle":
            break
        if res["view"] in ("dead", "loot") or "突然袭了过来" in res["log"]:
            return  # 被袭路径已验证交战;先制路径另行覆盖
    tid = res["extras"]["battle"]["target"]["id"]
    _cmd(two_players, "attack", target_id=tid)
    # atta 行动后自身 bid 已清,但 defe 的 bid=atta → 候选排除 defe
    # (defe 未行动)再次探索不应再发现 defe
    for _ in range(30):
        res = _cmd(two_players, "explore")
        if res["view"] == "battle":
            pytest.fail("交战锁失效:再次发现了未行动的对手")
        if res["view"] in ("dead", "loot"):
            break


def test_sense_gunshot(two_players):
    _setup_fight(weapon=("柯尔特政府型45口径", "WG", 25, 6))
    _login(two_players, "atta")
    for _ in range(80):
        res = _cmd(two_players, "explore")
        if res["view"] == "battle":
            break
        if res["view"] in ("dead", "loot"):
            break
        if "突然袭了过来" in res["log"]:
            _login(two_players, "defe")
            _cmd(two_players, "change_msg", msg="哼")
            _login(two_players, "atta")
    else:
        pytest.fail("未遭遇")
    if res["view"] == "battle":
        tid = res["extras"]["battle"]["target"]["id"]
        res = _cmd(two_players, "attack", target_id=tid)   # 单次交战(开枪→枪声日志)
        assert "射击" in res["log"] or "损害" in res["log"] or "躲开" in res["log"]
        # 守方登录:收件箱应有战斗报告(或已死亡)
        _login(two_players, "defe")
        st = two_players.get("/api/game/state").json()
        assert st["view"] in ("main", "dead")
        if st["view"] == "main":
            assert "战斗" in (st["log"] or "") or "枪响" in (st["log"] or "")


def test_runaway(two_players):
    _setup_fight(hp=500, mhit=500)
    _login(two_players, "atta")
    res = _cmd(two_players, "attack", run=True)
    assert "飞快的逃走了" in res["log"]
