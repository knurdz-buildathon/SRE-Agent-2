"""Tests for incremental log file reading."""
import tempfile
from pathlib import Path

from app.collectors.log_reader import read_new_log_entries
from app.collectors.user_log_parser import parse_user_log_line


def test_reads_only_new_lines():
    with tempfile.TemporaryDirectory(dir="C:/tmp") as tmp:
        tmp_path = Path(tmp)
        log_file = tmp_path / "app.log"
        log_file.write_text("method=GET path=/first status=500\n", encoding="utf-8")

        entries, offsets = read_new_log_entries(
            str(tmp_path),
            parse_user_log_line,
            {},
            source="user_log",
        )
        assert [e["path"] for e in entries] == ["/first"]

        with log_file.open("a", encoding="utf-8") as f:
            f.write("method=GET path=/second status=404\n")

        entries, offsets = read_new_log_entries(
            str(tmp_path),
            parse_user_log_line,
            offsets,
            source="user_log",
        )
        assert [e["path"] for e in entries] == ["/second"]
