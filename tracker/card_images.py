# -*- coding: utf-8 -*-
"""card_images.py — 卡牌图像管理器

下载、缓存和提供中文卡牌图像，用于叠加 UI 展示。

图像来源:
- 全卡渲染: https://art.hearthstonejson.com/v1/render/latest/zhCN/512x/{card_id}.png
- 小卡贴: https://art.hearthstonejson.com/v1/tiles/{card_id}.png
- 备用: https://hearthstone.nosdn.127.net/hearthstone/{card_id}.png

缓存位置: card_data/images/
- full/   — 完整卡牌图像 (512x)
- tile/   — 小贴片图像
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# 图像 URL 模板
_FULL_URL = "https://art.hearthstonejson.com/v1/render/latest/zhCN/512x/{card_id}.png"
_TILE_URL = "https://art.hearthstonejson.com/v1/tiles/{card_id}.png"
_FALLBACK_URL = "https://hearthstone.nosdn.127.net/hearthstone/{card_id}.png"

# 缓存目录
try:
    from analysis.config import PROJECT_ROOT
    _CACHE_BASE = PROJECT_ROOT / "card_data" / "images"
except ImportError:
    _CACHE_BASE = Path(__file__).resolve().parent.parent / "card_data" / "images"

_FULL_DIR = _CACHE_BASE / "full"
_TILE_DIR = _CACHE_BASE / "tile"


class CardImageManager:
    """卡牌图像管理器。

    负责下载、缓存和提供卡牌图像。使用内存缓存 + 磁盘缓存。

    用法::

        manager = CardImageManager()
        # 获取完整卡牌图像
        pixmap = manager.get_full_image("EX1_001")
        # 获取小贴片图像
        tile = manager.get_tile_image("EX1_001")
    """

    def __init__(self):
        self._memory_cache: Dict[str, object] = {}  # card_id → QPixmap
        self._tile_cache: Dict[str, object] = {}
        self._download_lock = threading.Lock()
        self._downloading = set()  # 正在下载的 card_id

        # 确保缓存目录存在
        _FULL_DIR.mkdir(parents=True, exist_ok=True)
        _TILE_DIR.mkdir(parents=True, exist_ok=True)

        # 延迟导入 QPixmap（需要 PyQt5）
        self._QPixmap = None
        self._QPainter = None

    def _ensure_qt(self):
        """延迟导入 Qt 类。"""
        if self._QPixmap is None:
            try:
                from PyQt5.QtGui import QPixmap, QPainter
                from PyQt5.QtCore import Qt
                self._QPixmap = QPixmap
                self._QPainter = QPainter
                self._Qt = Qt
            except ImportError:
                logger.warning("PyQt5 不可用，卡牌图像功能受限")

    def get_full_image(self, card_id: str):
        """获取完整卡牌图像 (QPixmap)。

        优先从内存缓存 → 磁盘缓存 → 下载。

        Args:
            card_id: 炉石卡牌 ID (如 "EX1_001")

        Returns:
            QPixmap 或 None
        """
        if not card_id:
            return self._create_placeholder(200, 290)

        self._ensure_qt()
        if self._QPixmap is None:
            return None

        # 内存缓存
        if card_id in self._memory_cache:
            return self._memory_cache[card_id]

        # 磁盘缓存
        cache_path = _FULL_DIR / f"{card_id}.png"
        if cache_path.exists():
            pixmap = self._QPixmap(str(cache_path))
            if not pixmap.isNull():
                self._memory_cache[card_id] = pixmap
                return pixmap

        # 异步下载
        self._download_async(card_id, "full")

        # 返回占位符
        return self._create_placeholder(200, 290)

    def get_tile_image(self, card_id: str):
        """获取小贴片图像 (QPixmap)。

        Args:
            card_id: 炉石卡牌 ID

        Returns:
            QPixmap 或 None
        """
        if not card_id:
            return self._create_placeholder(100, 30)

        self._ensure_qt()
        if self._QPixmap is None:
            return None

        # 内存缓存
        if card_id in self._tile_cache:
            return self._tile_cache[card_id]

        # 磁盘缓存
        cache_path = _TILE_DIR / f"{card_id}.png"
        if cache_path.exists():
            pixmap = self._QPixmap(str(cache_path))
            if not pixmap.isNull():
                self._tile_cache[card_id] = pixmap
                return pixmap

        # 异步下载
        self._download_async(card_id, "tile")

        return self._create_placeholder(100, 30)

    def _create_placeholder(self, width: int, height: int):
        """创建占位符图像。"""
        self._ensure_qt()
        if self._QPixmap is None:
            return None

        pixmap = self._QPixmap(width, height)
        pixmap.fill(self._Qt.gray)
        return pixmap

    def _download_async(self, card_id: str, image_type: str):
        """在后台线程下载卡牌图像。"""
        with self._download_lock:
            if card_id in self._downloading:
                return
            self._downloading.add(card_id)

        thread = threading.Thread(
            target=self._do_download,
            args=(card_id, image_type),
            daemon=True,
        )
        thread.start()

    def _do_download(self, card_id: str, image_type: str):
        """执行下载操作。"""
        try:
            if image_type == "full":
                url = _FULL_URL.format(card_id=card_id)
                cache_path = _FULL_DIR / f"{card_id}.png"
            else:
                url = _TILE_URL.format(card_id=card_id)
                cache_path = _TILE_DIR / f"{card_id}.png"

            # 尝试主 URL
            success = self._download_file(url, cache_path)

            # 失败时尝试备用 URL
            if not success and image_type == "full":
                fallback_url = _FALLBACK_URL.format(card_id=card_id)
                success = self._download_file(fallback_url, cache_path)

            if success:
                logger.debug("下载卡牌图像成功: %s", card_id)
                # 清除内存缓存，下次访问时会从磁盘加载
                self._memory_cache.pop(card_id, None)
                self._tile_cache.pop(card_id, None)
        except Exception as e:
            logger.debug("下载卡牌图像失败 %s: %s", card_id, e)
        finally:
            with self._download_lock:
                self._downloading.discard(card_id)

    @staticmethod
    def _download_file(url: str, save_path: Path) -> bool:
        """下载文件到指定路径。

        Returns:
            True 如果成功
        """
        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "HSAnalysis/1.0 (card image cache)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) < 100:
                    return False  # 太小，可能不是有效图像

                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(data)
                return True

        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return False

    def preload_cards(self, card_ids: list[str]):
        """预加载一批卡牌图像。

        在后台线程中下载所有未缓存的图像。

        Args:
            card_ids: 卡牌 ID 列表
        """
        for card_id in card_ids:
            if not card_id:
                continue
            # 检查磁盘缓存
            full_path = _FULL_DIR / f"{card_id}.png"
            tile_path = _TILE_DIR / f"{card_id}.png"
            if not full_path.exists():
                self._download_async(card_id, "full")
            if not tile_path.exists():
                self._download_async(card_id, "tile")

    def clear_memory_cache(self):
        """清除内存缓存。"""
        self._memory_cache.clear()
        self._tile_cache.clear()

    def get_cache_stats(self) -> dict:
        """获取缓存统计信息。"""
        full_count = len(list(_FULL_DIR.glob("*.png"))) if _FULL_DIR.exists() else 0
        tile_count = len(list(_TILE_DIR.glob("*.png"))) if _TILE_DIR.exists() else 0
        return {
            "full_images_cached": full_count,
            "tile_images_cached": tile_count,
            "memory_cache_size": len(self._memory_cache) + len(self._tile_cache),
        }
