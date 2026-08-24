# BATTLE ROYALE CN v2 — HTML5 现代化重写版

2001 年 Perl CGI 游戏《BATTLE ROYALE》汉化版的完整重写:后端 FastAPI + SQLite,
前端原生 HTML5 SPA(零构建),彻底移除 CGI 技术。玩法、数值、文案与原版对等,
并修复原版已知 bug(见 BUGFIXES.md)。

> **使用说明(部署/开局/玩法)见 [USAGE.md](USAGE.md)**,本文件侧重技术架构。

## 运行

```bash
pip install --user fastapi uvicorn      # 仅两项依赖(Python 3.10+)
python3 run.py 8000                     # http://127.0.0.1:8000/
```

局域网联机:同一网络内访问 `http://<主机IP>:8000/`。

## 开局流程

1. 设置管理密码并启动:`BR_ADMIN_PASS=你的密码 python3 run.py 8000`
   (未设置该环境变量时管理后台登录禁用)。打开 `http://127.0.0.1:8000/#/admin`
   登录后点「数据初始化」开新局。
2. 各玩家在首页「新学员注册」注册角色(班级自动分配、社团随机)。
3. 登录后进入主界面:移动/探索/物品/合成/特殊行动;每天 0:00 追加 3 个禁区。
4. 结局:最后 1 名生存者(且第 5 天起)优胜;或黑客解除禁区 → 回分校杀班主任
   夺「程序解除钥匙」→ 分校使用 → 全员逃生(EX 结局)。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `BR_DB` | `v2/brcn.db` | SQLite 数据库路径 |
| `BR_ADMIN_PASS` | 无(必设) | 管理密码;未设置则管理登录禁用 |
| `BR_ADMIN_USER` | `admin` | NPC 编号前缀 |
| `BR_COOKIE_SECURE` | `0` | HTTPS 部署时置 `1`(会话 cookie 加 Secure 属性) |

## 架构

```
v2/
├── app/
│   ├── config.py        # 全部游戏常量(br.cgi 对等)
│   ├── db.py            # SQLite schema/事务(BEGIN IMMEDIATE 串行化,等价原版全局锁)
│   ├── security.py      # pbkdf2 密码哈希、会话 token
│   ├── engine/          # 游戏引擎(纯逻辑:命令管线/战斗/物品/事件/禁区/结局)
│   ├── services/        # 认证/状态聚合/世界视图
│   └── api/             # REST:auth / game / admin
├── static/              # 前端 SPA(hash 路由 + 10s/3s 轮询)
├── seeds/               # dat/*.dat 迁移出的种子 JSON(含文案)
├── tools/migrate_dat.py # 一次性迁移工具(--check 对照报告)
└── tests/               # 公式黄金值/引擎/战斗/世界/管理 端到端测试
```

- **时间模型**(对等原版):回合=命令请求;睡眠/治疗按真实时间差值在下一次
  交互时结算;禁区由下一次任意请求(含轮询)跨 0 点惰性推进。
- **并发**:所有写操作在 `BEGIN IMMEDIATE` 事务内,SQLite 写锁串行化同局
  操作;WAL 模式读不阻塞。
- **实时性**:前端短轮询(普通 10s,休息中 3s);枪声/悲鸣 15 秒、扩音器
  30 秒内可见,与原版时效一致。

## 测试

```bash
python3 -m pytest tests/ -q        # 35 项(含数值公式黄金值)
python3 tools/migrate_dat.py --check
```

## 与原版的差异

- 原 Perl CGI 版本保留在上级目录作参照;本目录为独立新实现。
- 认证改为服务端会话(原版每请求明文携带密码 + cookie 存整行状态)。
- 补齐原版缺失的合成素材/毒药/扩音器投放,使全部系统可达。
- 其余修复见 BUGFIXES.md;未移植:图标系统(原版关闭)、个人存档 u_save
  (被管理备份取代)、基本方针(原版未实装)。

原作: (C) 2000 Happy Ice.(BATTLE ROYALE CGI V01.16,含 kelp 扩展)
