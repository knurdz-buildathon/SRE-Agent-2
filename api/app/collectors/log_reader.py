import logging
import os
from typing import Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("sre")

Parser = Callable[[str], Optional[Dict]]

DEFAULT_LOG_EXTENSIONS = (".log", ".txt", ".json", ".jsonl", ".access")


def _iter_log_files(log_dir: str, extensions: Iterable[str] = DEFAULT_LOG_EXTENSIONS) -> List[str]:
    if not log_dir or not os.path.isdir(log_dir):
        return []

    allowed = tuple(ext.lower() for ext in extensions)
    files: List[str] = []
    try:
        for root, _, names in os.walk(log_dir):
            for name in names:
                if name.startswith("."):
                    continue
                if allowed and not name.lower().endswith(allowed):
                    continue
                files.append(os.path.join(root, name))
    except Exception as e:
        logger.error("Error scanning log directory %s: %s", log_dir, e)
    return sorted(files)


def read_new_log_entries(
    log_dir: str,
    parser: Parser,
    offsets: Dict[str, int],
    *,
    source: str,
    extensions: Iterable[str] = DEFAULT_LOG_EXTENSIONS,
    max_bytes_per_file: int = 2_000_000,
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Read only new bytes from log files and parse complete lines.

    If a file shrinks, it is treated as rotated/truncated and starts over. If a
    file grows by more than ``max_bytes_per_file`` between cycles, only the tail
    is parsed so the agent cannot get stuck on very large historical logs.
    """
    entries: List[Dict] = []
    new_offsets: Dict[str, int] = {}

    for path in _iter_log_files(log_dir, extensions):
        try:
            size = os.path.getsize(path)
        except Exception:
            continue

        start = int(offsets.get(path, 0) or 0)
        if start < 0 or start > size:
            start = 0

        skip_partial = False
        if size - start > max_bytes_per_file:
            start = max(0, size - max_bytes_per_file)
            skip_partial = start > 0

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start)
                if skip_partial:
                    f.readline()
                while True:
                    line = f.readline()
                    if not line:
                        break
                    parsed = parser(line)
                    if parsed:
                        parsed.setdefault("source", source)
                        parsed.setdefault("source_file", os.path.basename(path))
                        entries.append(parsed)
                new_offsets[path] = f.tell()
        except Exception as e:
            logger.error("Error reading log file %s: %s", path, e)

    return entries, new_offsets
