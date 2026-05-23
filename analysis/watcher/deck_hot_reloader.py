"""deck_hot_reloader.py — Hot-reload deck_codes.txt mid-game.

Polls the file for changes (by mtime). When a change is detected:
1. Formats deck_codes.txt (normalize ### name → # name: X | arch: Y, add annotations)
2. Rebuilds the archetype DB and refreshes the Bayesian opponent model.

Usage:
    reloader = DeckHotReloader("deck_codes.txt")
    # In main loop:
    reloader.check_and_reload(bayesian_model)  # non-blocking
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.utils.bayesian_opponent import BayesianOpponentModel

log = logging.getLogger(__name__)


class DeckHotReloader:
    """Polling-based hot-reloader for deck_codes.txt.

    Detects file changes via mtime comparison. When a change is found:
    1. Formats deck_codes.txt (normalize + enrich with class/retention annotations)
    2. Rebuilds archetype DB from the new file content
    3. Optionally refreshes a BayesianOpponentModel instance

    Thread safety: NOT thread-safe. Call from the main loop only.
    """

    def __init__(
        self,
        deck_codes_path: str | Path,
        *,
        poll_interval: float = 2.0,
        on_reload: Optional[Callable[[int], None]] = None,
    ):
        """
        Args:
            deck_codes_path: Path to deck_codes.txt
            poll_interval: Minimum seconds between checks (default 2s)
            on_reload: Optional callback(decks_stored) after successful reload
        """
        self.path = Path(deck_codes_path)
        self.poll_interval = poll_interval
        self.on_reload = on_reload

        self._last_mtime: float = 0.0
        self._last_check: float = 0.0

        if self.path.exists():
            # _last_mtime 设为 0，使首次 check_and_reload() 必然触发格式化
            # 不在 __init__ 中直接调用 _do_reload()，避免阻塞初始化
            log.info(f"DeckHotReloader: watching {self.path} (will format on first check)")
        else:
            log.warning(f"DeckHotReloader: {self.path} not found")

    def needs_reload(self) -> bool:
        """检查 deck_codes.txt 是否有变更（比 _last_mtime 更新）。

        用于 load_existing_log 等场景：只检查不触发重载。
        """
        if not self.path.exists():
            return False
        try:
            return self.path.stat().st_mtime > self._last_mtime
        except OSError:
            return False

    def check_and_reload(
        self,
        bayesian_model: Optional[BayesianOpponentModel] = None,
    ) -> bool:
        """Check if deck_codes.txt changed and reload if needed.

        Non-blocking: returns immediately if within poll_interval.

        Args:
            bayesian_model: Optional BayesianOpponentModel to refresh.
                           If provided, reloads its deck data from the updated DB.

        Returns:
            True if a reload was performed, False otherwise
        """
        import time
        now = time.time()

        if (now - self._last_check) < self.poll_interval:
            return False
        self._last_check = now

        if not self.path.exists():
            return False

        try:
            current_mtime = self.path.stat().st_mtime
        except OSError:
            return False

        if current_mtime <= self._last_mtime:
            return False

        log.info(f"DeckHotReloader: {self.path} changed (mtime {self._last_mtime} → {current_mtime})")
        self._last_mtime = current_mtime

        return self._do_reload(bayesian_model)

    def _do_reload(
        self,
        bayesian_model: Optional[BayesianOpponentModel] = None,
    ) -> bool:
        """Execute the actual reload: format + rebuild DB + refresh model.

        流程:
          1. 解析 deck_codes.txt（支持 ### name 和 # name: X | arch: Y 两种格式）
          2. 解码所有卡组代码，计算留存度
          3. 格式化写回 deck_codes.txt（统一为 # name: X | arch: Y 格式 + 注释）
          4. 更新 deck_library.json
          5. 刷新 BayesianOpponentModel（重建 DB + 重放证据）
        """
        try:
            scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from expand_deck_codes import (
                parse_deck_codes, decode_deck, format_enriched_txt,
                decks_to_library, DECK_LIBRARY_PATH,
            )
        except ImportError as e:
            log.error("DeckHotReloader: cannot import expand_deck_codes: %s", e)
            return False

        raw_decks = parse_deck_codes(self.path)
        if not raw_decks:
            log.warning("DeckHotReloader: no deck codes found after change")
            return False

        decoded = []
        for name, arch, code in raw_decks:
            entry = decode_deck(name, arch, code)
            if entry:
                decoded.append(entry)

        if not decoded:
            log.warning("DeckHotReloader: all deck decodes failed")
            return False

        enriched = format_enriched_txt(decoded)
        self.path.write_text(enriched, encoding="utf-8")
        self._last_mtime = self.path.stat().st_mtime

        library = decks_to_library(decoded)
        DECK_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        DECK_LIBRARY_PATH.write_text(
            json.dumps(library, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("DeckHotReloader: formatted %d decks, updated deck_library.json", len(decoded))

        if bayesian_model is not None:
            self._refresh_model(bayesian_model)

        if self.on_reload:
            self.on_reload(len(decoded))

        return True

    def _refresh_model(self, model: BayesianOpponentModel) -> None:
        """Refresh a BayesianOpponentModel's deck data from the updated DB.

        保留已观测卡牌证据，重建卡组列表和后验分布:
          1. 保存 _seen_deck_cards / _seen_cards_counter 等追踪状态
          2. 重新加载卡组（_load_decks 内部会调用 build_archetype_db_from_deck_codes）
          3. 重建倒排索引
          4. 从先验开始，用历史证据重放 _raw_update 重建后验
          5. 恢复追踪状态，重新检查锁定
        """
        old_seen_deck_cards = dict(model._seen_deck_cards)
        old_seen_cards_counter = dict(model._seen_cards_counter)
        old_known_hand_cards = list(model._known_hand_cards)
        old_hand_hold_since = dict(model._hand_hold_since)
        old_seen_cards = list(model._seen_cards)

        model._load_decks(model.player_class)

        model.card_to_decks = defaultdict(set)
        for deck in model.decks:
            aid = deck["archetype_id"]
            for dbf in deck["cards"]:
                model.card_to_decks[dbf].add(aid)

        model.posteriors = model.build_prior(model.player_class)
        model.locked = None

        model._seen_deck_cards = Counter(old_seen_deck_cards)
        for dbf_id, count in old_seen_deck_cards.items():
            for _ in range(count):
                model._raw_update(dbf_id)

        model._seen_cards = old_seen_cards
        model._seen_cards_counter = Counter(old_seen_cards_counter)
        model._known_hand_cards = old_known_hand_cards
        model._hand_hold_since = old_hand_hold_since
        model.locked = model.get_lock()

        log.info("DeckHotReloader: refreshed Bayesian model (%d decks, locked=%s)",
                 len(model.decks), model.locked is not None)
