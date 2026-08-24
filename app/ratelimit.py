"""简单内存限速:登录失败锁定 + 注册固定窗口计数。

仅适用于单进程 uvicorn(本项目部署形态);多进程/多实例需换共享存储。
目的:阻断在线爆破(密码上限 8 半角的弱口令空间)与脚本批量占名额。

[安全] 键空间攻击者可控(随机用户名/IP):两个字典设 MAX_KEYS 上限,
超限时先清已失效记录,仍超限则整体清空(攻击灌键场景下牺牲旧键保内存,
代价仅是既有锁定/计数重置,可接受)。
"""
import time

# 键数上限(约 1 万键 × 数十字节,内存上限约 1MB 量级)
MAX_KEYS = 10_000

# key -> [连续失败次数, 锁定截止时间戳]
_attempts = {}
# key -> [窗口起点, 窗口内计数]
_counts = {}


def _prune(store, stale):
    """超限时先清失效记录;仍超限(灌键攻击)整体清空。插入路径统一调用。"""
    if len(store) < MAX_KEYS:
        return
    for k in [k for k, rec in store.items() if stale(rec)]:
        del store[k]
    if len(store) >= MAX_KEYS:
        store.clear()


def _attempts_stale(rec, now=None):
    now = now or time.time()
    return rec[1] <= now          # 锁定已过期(未锁定=0 也算失效)


def _counts_stale(rec, now=None):
    now = now or time.time()
    return now - rec[0] >= 3600   # 窗口起点早于 1 小时前(最大注册窗口)


def is_locked(key) -> bool:
    rec = _attempts.get(key)
    return bool(rec and rec[1] > time.time())


def record_fail(key, max_fails=5, lock_secs=600):
    """记一次失败;连续 max_fails 次后锁定 lock_secs 秒。"""
    _prune(_attempts, _attempts_stale)
    rec = _attempts.setdefault(key, [0, 0.0])
    rec[0] += 1
    if rec[0] >= max_fails:
        rec[1] = time.time() + lock_secs
        rec[0] = 0


def clear(key):
    _attempts.pop(key, None)


def allow(key, limit, window_secs) -> bool:
    """固定窗口计数:window_secs 内超过 limit 次返回 False。"""
    _prune(_counts, _counts_stale)
    now = time.time()
    rec = _counts.get(key)
    if not rec or now - rec[0] >= window_secs:
        _counts[key] = [now, 1]
        return True
    rec[1] += 1
    return rec[1] <= limit
