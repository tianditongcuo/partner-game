"""今日老婆插件工具函数与持久化。"""
from __future__ import annotations

import os
import json
import time
import base64
import asyncio
import logging
from typing import Any, Dict, Optional

import aiohttp

try:                                    # 包内导入
    from . import balance as _B
except ImportError:                     # docs/tools 顶层导入
    import balance as _B

logger = logging.getLogger("partner_game")

#: 头像缓存：{(qq, size): (时间戳, base64)}。默认 TTL 见 balance.AVATAR_CACHE_SECONDS
_avatar_cache: Dict[Any, Any] = {}

async def fetch_avatar_base64(qq: str, size: int = 640, timeout_sec: int = 10) -> Optional[str]:
    """下载指定 QQ 的头像并返回 base64。失败返回 None。

    带 TTL 缓存：同一个人同一尺寸在 AVATAR_CACHE_SECONDS 内不会重复下载。
    """
    key = (str(qq), int(size))
    ttl = max(0, int(getattr(_B, "AVATAR_CACHE_SECONDS", 0) or 0))
    hit = _avatar_cache.get(key)
    if hit and ttl and time.time() - hit[0] < ttl:
        return hit[1]

    urls = [
        f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s={size}",
        f"https://q.qlogo.cn/g?b=qq&nk={qq}&s={size}",
    ]
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            encoded = base64.b64encode(data).decode("utf-8")
                            if ttl:
                                _avatar_cache[key] = (time.time(), encoded)
                            return encoded
                except Exception as e:
                    logger.debug(f"头像下载失败 {url}: {e}")
                    continue
    except Exception as e:
        logger.warning(f"头像下载会话错误: {e}")
    return None

def today_str(tz_offset_hours: int = 8) -> str:
    """根据时区偏移返回 YYYY-MM-DD。"""
    offset = max(-12, min(14, int(tz_offset_hours)))
    ts = time.time() + offset * 3600
    return time.strftime("%Y-%m-%d", time.gmtime(ts))

def format_user_display(uid: str, nick: str, card: str) -> str:
    nick = nick or "未知昵称"
    if card and card != nick:
        return f"{nick}{{{card}}}({uid})"
    return f"{nick}({uid})"

class PersistStore:
    """持久化数据存储。"""

    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()
        self.data: Dict[str, Any] = {"marriages": {}, "users": {}, "daily_usage": {}, "last_date": ""}
        self._save_task: Optional[asyncio.Task] = None
        self._load_sync()

    def _load_sync(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    # 兼容老数据
                    marriages = d.get("marriages", {})
                    if not marriages and "daily" in d:
                        marriages = d.get("daily", {})
                    self.data = {
                        "marriages": marriages,
                        "users": d.get("users", {}),
                        "daily_usage": d.get("daily_usage", {}),
                        "last_date": d.get("last_date", "")
                    }
        except Exception as e:
            logger.error(f"加载持久化失败: {e}")
            self.data = {"marriages": {}, "users": {}, "daily_usage": {}, "last_date": ""}

    async def save(self) -> None:
        """非阻塞触发保存，使用防抖机制。"""
        if self._save_task and not self._save_task.done():
            return
            
        async def _delayed_save():
            await asyncio.sleep(2.0)  # 防抖 2 秒
            await self.force_save()
            
        self._save_task = asyncio.create_task(_delayed_save())

    async def force_save(self) -> None:
        """强制立即保存并落盘。"""
        async with self.lock:
            def _write():
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False)
                os.replace(tmp, self.path)
            try:
                await asyncio.to_thread(_write)
            except Exception as e:
                logger.error(f"保存持久化失败: {e}")

    def purge_old(self, today: str) -> bool:
        """跨周期标记。返回是否跨周期（供发放好感等副作用使用）。

        注意：这里**不再清空 daily_usage**。
        每个行动的次数由 _check_daily_limit 按各自的周期时长单独判断并清零，
        否则「打劫 168 小时一轮」会被这里的每日清空破坏。
        """
        last_date = self.data.get("last_date", "")
        if last_date != today:
            self.data["last_date"] = today
            return True
        return False
