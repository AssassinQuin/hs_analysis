"""pipeline.py — Batch processing of Power.log files into training datasets.

Provides :class:`TrainingPipeline` for processing multiple replay files
through the :class:`TrainingDataExtractor` and writing results to JSONL.

Typical usage::

    pipeline = TrainingPipeline(output_dir="training_data")
    stats = pipeline.process_directory("logs/")
    print(pipeline.get_stats())
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from analysis.training.extractor import TrainingDataExtractor, TrainingSample

log = logging.getLogger(__name__)


class TrainingPipeline:
    """Batch process Power.log files into training datasets.

    Orchestrates log parsing → state/action extraction → encoding →
    JSONL output, with aggregated statistics.
    """

    def __init__(self, output_dir: str = "training_data") -> None:
        """Initialise the pipeline.

        Args:
            output_dir: Directory where JSONL output files are written.
        """
        self.output_dir = output_dir
        self.extractor = TrainingDataExtractor()
        self.stats: Dict[str, int] = {
            "files_processed": 0,
            "games_extracted": 0,
            "samples_total": 0,
            "errors": 0,
        }

    def process_log_file(self, log_path: str) -> int:
        """Process a single Power.log file and write training samples.

        Attempts to parse the log file using the project's replay parser.
        Falls back gracefully if the parser is unavailable or the file
        cannot be parsed.

        Args:
            log_path: Path to a Power.log file.

        Returns:
            Number of training samples extracted (0 on failure).
        """
        path = Path(log_path)
        if not path.exists():
            log.warning("Log file not found: %s", log_path)
            self.stats["errors"] += 1
            return 0

        try:
            game_data = self._parse_log_file(path)
        except Exception as e:
            log.error("Failed to parse %s: %s", log_path, e)
            self.stats["errors"] += 1
            return 0

        if not game_data:
            log.info("No game data extracted from %s", log_path)
            self.stats["files_processed"] += 1
            return 0

        total_samples = 0
        for game_id, game in game_data.items():
            try:
                states = game.get("states", [])
                actions = game.get("actions", [])
                outcome = game.get("outcome", "loss")

                if not states or not actions:
                    continue

                samples = self.extractor.extract_from_replay(states, actions, outcome)
                if samples:
                    # Write to individual game file
                    output_name = f"game_{game_id}.jsonl"
                    output_path = os.path.join(self.output_dir, output_name)
                    self.extractor.to_jsonl(samples, output_path)
                    total_samples += len(samples)
                    self.stats["games_extracted"] += 1

            except Exception as e:
                log.error("Failed to extract game %s from %s: %s", game_id, log_path, e)
                self.stats["errors"] += 1

        self.stats["files_processed"] += 1
        self.stats["samples_total"] += total_samples
        return total_samples

    def process_directory(
        self,
        dir_path: str,
        pattern: str = "Power.log",
    ) -> Dict[str, int]:
        """Process all Power.log files in a directory.

        Walks the directory tree recursively and processes every file
        whose name matches *pattern*.

        Args:
            dir_path: Root directory to search.
            pattern: Filename glob pattern (default ``"Power.log"``).

        Returns:
            A copy of the processing statistics dict.
        """
        root = Path(dir_path)
        if not root.is_dir():
            log.error("Directory not found: %s", dir_path)
            return dict(self.stats)

        # Ensure output directory exists
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # Find matching files
        matched_files: List[Path] = []
        for p in sorted(root.rglob(pattern)):
            if p.is_file():
                matched_files.append(p)

        if not matched_files:
            log.info("No files matching '%s' in %s", pattern, dir_path)
            return dict(self.stats)

        log.info(
            "Processing %d file(s) matching '%s' in %s",
            len(matched_files), pattern, dir_path,
        )

        for fpath in matched_files:
            log.info("Processing: %s", fpath)
            try:
                self.process_log_file(str(fpath))
            except Exception as e:
                log.error("Unexpected error processing %s: %s", fpath, e)
                self.stats["errors"] += 1

        return dict(self.stats)

    def get_stats(self) -> Dict[str, int]:
        """Return current processing statistics.

        Returns:
            A dict with keys: ``files_processed``, ``games_extracted``,
            ``samples_total``, ``errors``.
        """
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Reset all statistics to zero."""
        self.stats = {
            "files_processed": 0,
            "games_extracted": 0,
            "samples_total": 0,
            "errors": 0,
        }

    # ──────────────────────────────────────────────────────────
    # Log parsing (delegates to project parser)
    # ──────────────────────────────────────────────────────────

    def _parse_log_file(self, path: Path) -> Dict[str, Any]:
        """Parse a Power.log file into game data.

        Attempts to use the project's replay parser.  Returns a dict
        mapping game_id → {states, actions, outcome}.

        Returns an empty dict if parsing is unavailable or fails.
        """
        try:
            from analysis.log_parser.power_log_parser import parse_power_log
            return parse_power_log(str(path))
        except ImportError:
            log.debug("power_log_parser not available, trying alternate parser")
            pass

        try:
            from analysis.replay.parser import parse_replay_file
            return parse_replay_file(str(path))
        except ImportError:
            log.debug("replay.parser not available")
            pass

        # No parser available — return empty
        log.debug("No log parser available for %s", path)
        return {}
