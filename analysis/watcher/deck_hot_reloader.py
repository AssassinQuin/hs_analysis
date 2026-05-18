"""deck_hot_reloader.py — Hot-reload deck_codes.txt mid-game.

Polls the file for changes (by mtime). When a change is detected,
rebuilds the archetype DB and refreshes the Bayesian opponent model.

Usage:
    reloader = DeckHotReloader("deck_codes.txt")
    # In main loop:
    reloader.check_and_reload(bayesian_model)  # non-blocking
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.utils.bayesian_opponent import BayesianOpponentModel

log = logging.getLogger(__name__)


class DeckHotReloader:
    """Polling-based hot-reloader for deck_codes.txt.
    
    Detects file changes via mtime comparison. When a change is found:
    1. Rebuilds archetype DB from the new file content
    2. Optionally refreshes a BayesianOpponentModel instance
    
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
        
        # Track initial mtime
        if self.path.exists():
            self._last_mtime = self.path.stat().st_mtime
            log.info(f"DeckHotReloader: watching {self.path} (mtime={self._last_mtime})")
        else:
            log.warning(f"DeckHotReloader: {self.path} not found")

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
        
        # Rate-limit checks
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
        
        # File changed! Reload.
        log.info(f"DeckHotReloader: {self.path} changed (mtime {self._last_mtime} → {current_mtime})")
        self._last_mtime = current_mtime
        
        return self._do_reload(bayesian_model)

    def _do_reload(
        self,
        bayesian_model: Optional[BayesianOpponentModel] = None,
    ) -> bool:
        """Execute the actual reload: rebuild DB + refresh model."""
        pass  # HSReplay data source removed; reload no longer functional

    def _refresh_model(self, model: BayesianOpponentModel) -> None:
        """Refresh a BayesianOpponentModel's deck data from the updated DB.
        
        Re-loads decks, rebuilds inverted index, and recomputes posteriors
        while preserving the seen-card history for re-application of updates.
        """
        pass  # HSReplay data source removed; refresh no longer functional
