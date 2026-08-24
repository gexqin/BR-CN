"""SQLite 连接管理:WAL、BEGIN IMMEDIATE 事务、schema 初始化。

并发模型:所有游戏写操作包在 transaction() 内,BEGIN IMMEDIATE 取得
写锁,天然串行化同局操作(等价原版全局 mkdir 锁);WAL 模式下读不被阻塞。
"""
import os
import sys
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',      -- running|finished_win|finished_escape
    start_at INTEGER NOT NULL,                   -- 开局 epoch(报名/日界基准)
    last_tick_day TEXT,                          -- 已结算到的自然日 YYYY-MM-DD(禁区惰性推进)
    forbidden_order TEXT NOT NULL,               -- JSON: 禁区洗牌序(22 个地点索引,分校恒第 1)
    forbidden_count INTEGER NOT NULL DEFAULT 0,  -- 已生效禁区数 ar
    hack_active INTEGER NOT NULL DEFAULT 0,      -- 黑客解除标志(次日日界重置)
    winner_player_id INTEGER,
    end_reason TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    username TEXT NOT NULL,
    pass_hash TEXT NOT NULL,
    f_name TEXT NOT NULL,
    l_name TEXT NOT NULL,
    sex TEXT NOT NULL,                    -- 男生|女生|男性(NPC)
    class_name TEXT NOT NULL,
    class_no INTEGER NOT NULL,
    club TEXT,
    is_npc INTEGER NOT NULL DEFAULT 0,
    is_government INTEGER NOT NULL DEFAULT 0,   -- 政府系 NPC:不计剩余人数
    -- 战斗数值
    att INTEGER NOT NULL DEFAULT 8,
    deff INTEGER NOT NULL DEFAULT 8,      -- def 为 SQL 关键字嫌疑,用 deff
    hit INTEGER NOT NULL DEFAULT 30,
    mhit INTEGER NOT NULL DEFAULT 30,
    level INTEGER NOT NULL DEFAULT 1,
    exp INTEGER NOT NULL DEFAULT 0,
    kill INTEGER NOT NULL DEFAULT 0,
    -- 熟练度(镜像原版 w_* 十字段)
    prof_wn INTEGER NOT NULL DEFAULT 0,
    prof_wp INTEGER NOT NULL DEFAULT 0,
    prof_wa INTEGER NOT NULL DEFAULT 0,
    prof_wg INTEGER NOT NULL DEFAULT 0,
    prof_we INTEGER NOT NULL DEFAULT 0,
    prof_wc INTEGER NOT NULL DEFAULT 0,
    prof_wd INTEGER NOT NULL DEFAULT 0,
    prof_wb INTEGER NOT NULL DEFAULT 0,
    prof_wf INTEGER NOT NULL DEFAULT 0,
    prof_ws INTEGER NOT NULL DEFAULT 0,
    -- 装备:武器/身体/头/足/腕 + 饰品(名称+码+数值;uses 为弹药/耐久,NULL=∞)
    wep_name TEXT NOT NULL DEFAULT '空手',
    wep_code TEXT NOT NULL DEFAULT 'WP',
    wep_att INTEGER NOT NULL DEFAULT 0,
    wep_uses INTEGER,
    bou_name TEXT NOT NULL DEFAULT '内衣',   -- 身体防具
    bou_code TEXT NOT NULL DEFAULT 'DN',
    bou_def INTEGER NOT NULL DEFAULT 0,
    bou_uses INTEGER,
    bouh_name TEXT NOT NULL DEFAULT '',      -- 头部防具(空串=未装备)
    bouh_code TEXT NOT NULL DEFAULT '',
    bouh_def INTEGER NOT NULL DEFAULT 0,
    bouh_uses INTEGER,
    bouf_name TEXT NOT NULL DEFAULT '',      -- 足部
    bouf_code TEXT NOT NULL DEFAULT '',
    bouf_def INTEGER NOT NULL DEFAULT 0,
    bouf_uses INTEGER,
    boua_name TEXT NOT NULL DEFAULT '',      -- 腕部
    boua_code TEXT NOT NULL DEFAULT '',
    boua_def INTEGER NOT NULL DEFAULT 0,
    boua_uses INTEGER,
    acc_name TEXT NOT NULL DEFAULT '',       -- 饰品(护腹 AD 系/雷达)
    acc_code TEXT NOT NULL DEFAULT '',
    acc_eff INTEGER NOT NULL DEFAULT 0,
    acc_uses INTEGER,
    items TEXT NOT NULL DEFAULT '[]',        -- JSON: 背包 5+1 格 [{name,code,eff,uses}]
    -- 状态
    place INTEGER NOT NULL DEFAULT 0,
    sta INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'alive',    -- alive|sleeping|healing|dead|escaped|won
    injuries TEXT NOT NULL DEFAULT '',       -- 负伤部位串:头/腕/腹/足 组合
    death_type TEXT,
    death_time INTEGER,
    dead_by INTEGER,
    corpse_found INTEGER NOT NULL DEFAULT 0, -- 尸体已被发现标记(原 sta=-1)
    found_by INTEGER,                        -- 尸体发现者(拾取权)
    -- 实时/交互
    rest_since INTEGER,                      -- 睡眠/治疗开始时刻(NULL=未休息)
    bid INTEGER,                             -- 交战锁:最近交战且未行动的对手
    no_reentry_until INTEGER NOT NULL DEFAULT 0,  -- 死亡禁注册截止
    -- 文本
    log TEXT NOT NULL DEFAULT '',
    msg TEXT NOT NULL DEFAULT '',            -- 口癖(杀害时台词)
    dmes TEXT NOT NULL DEFAULT '',           -- 遗言
    com TEXT NOT NULL DEFAULT '',            -- 座右铭
    corpse_desc INTEGER,                     -- 尸体描述变体 0-6
    win_flag INTEGER NOT NULL DEFAULT 0,     -- inf 胜(优胜)
    key_flag INTEGER NOT NULL DEFAULT 0,     -- inf 解(用过解除钥匙)
    created_at INTEGER,
    UNIQUE(game_id, username),
    UNIQUE(game_id, f_name, l_name, sex)
);

CREATE TABLE IF NOT EXISTS area_items (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    place INTEGER NOT NULL,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    eff INTEGER NOT NULL DEFAULT 0,
    uses INTEGER,
    trap INTEGER NOT NULL DEFAULT 0,        -- TO 已激活陷阱
    owner_id INTEGER,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_area_items ON area_items(game_id, place);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    at INTEGER NOT NULL,
    kind TEXT NOT NULL,     -- NEWGAME|ENTRY|DEATH|DEATH1..4|DEATHAREA|WINEND|EX_END|AREA
    subject_id INTEGER,
    opponent_id INTEGER,
    extra TEXT,             -- JSON: 死因/遗言/禁区数/留言等
    text TEXT               -- 预渲染的新闻行文本(与原版 news.cgi 等价)
);
CREATE INDEX IF NOT EXISTS idx_news ON news(game_id, id);

CREATE TABLE IF NOT EXISTS sense_logs (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    at INTEGER NOT NULL,
    expire_at INTEGER NOT NULL,
    scope TEXT NOT NULL,    -- place|island
    place INTEGER,
    kind TEXT NOT NULL,     -- gunshot|scream|announce
    player_id INTEGER,
    target_id INTEGER,      -- gunshot/scream 的另一方(自身不可见判定)
    message TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    game_id INTEGER,
    player_id INTEGER REFERENCES players(id),
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_backups (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL,
    at INTEGER NOT NULL,
    label TEXT,
    snapshot TEXT NOT NULL   -- JSON: games+players+area_items+news 全量
);
"""


def connect(db_path=None):
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=10,
                           isolation_level=None)   # 显式事务管理
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # [FIX] 与 connect(timeout=10) 一致,避免 5s 即抛 database is locked
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    conn = connect(db_path)
    with conn:
        conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn):
    """写事务:BEGIN IMMEDIATE 立即取写锁(串行化对等原版全局锁)。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    init_db(path)
    print("schema initialized")
