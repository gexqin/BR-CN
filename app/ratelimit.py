"""简单内存限速:登录失败锁定 + 注册固定窗口计数。

仅适用于单进程 uvicorn(本项目部署形态);多进程/多实例需换共享存储。
目的:阻断在线爆破(密码上限 8 半角的弱口令空间)与脚本批量占名额。
"""
import time

# key -> [连续失败次数, 锁定截止时间戳]
_attempts = {}
# key -> [窗口起点, 窗口内计数]
_counts = {}


def is_locked(key) -> bool:
    rec = _attempts.get(key)
    return bool(rec and rec[1] > time.time())


def record_fail(key, max_fails=5, lock_secs=600):
    """记一次失败;连续 max_fails 次后锁定 lock_secs 秒。"""
    rec = _attempts.setdefault(key, [0, 0.0])
    rec[0] += 1
    if rec[0] >= max_fails:
        rec[1] = time.time() + lock_secs
        rec[0] = 0


def clear(key):
    _attempts.pop(key, None)


def allow(key, limit, window_secs) -> bool:
    """固定窗口计数:window_secs 内超过 limit 次返回 False。"""
    now = time.time()
    rec = _counts.get(key)
    if not rec or now - rec[0] >= window_secs:
        _counts[key] = [now, 1]
        return True
    rec[1] += 1
    return rec[1] <= limit
