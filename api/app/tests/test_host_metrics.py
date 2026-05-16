from app.collectors import host_metrics


def test_meminfo_calculates_used_and_percent(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal:       2048000 kB\n"
        "MemAvailable:   512000 kB\n",
        encoding="utf-8",
    )

    metrics = host_metrics._meminfo(proc)

    assert metrics["memory_total_mb"] == 2000
    assert metrics["memory_available_mb"] == 500
    assert metrics["memory_used_mb"] == 1500
    assert metrics["memory_percent"] == 75


def test_collect_vps_metrics_prefers_host_mounts(tmp_path, monkeypatch):
    proc = tmp_path / "host-proc"
    etc = tmp_path / "host-etc"
    root = tmp_path / "host-root"
    proc.mkdir()
    etc.mkdir()
    root.mkdir()
    (etc / "os-release").write_text('PRETTY_NAME="Test Linux"\n', encoding="utf-8")
    (proc / "stat").write_text(
        "cpu  100 0 100 800 0 0 0 0 0 0\n"
        "cpu0 50 0 50 400 0 0 0 0 0 0\n"
        "cpu1 50 0 50 400 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    (proc / "loadavg").write_text("0.10 0.20 0.30 1/100 1\n", encoding="utf-8")
    (proc / "meminfo").write_text(
        "MemTotal:       1024000 kB\n"
        "MemAvailable:   768000 kB\n",
        encoding="utf-8",
    )
    (proc / "uptime").write_text("1234.56 100.00\n", encoding="utf-8")
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text("6.1.0-test\n", encoding="utf-8")

    monkeypatch.setattr(host_metrics, "HOST_PROC_ROOT", proc)
    monkeypatch.setattr(host_metrics, "HOST_ETC_ROOT", etc)
    monkeypatch.setattr(host_metrics, "HOST_ROOT", root)
    monkeypatch.setattr(host_metrics, "HOST_DISK_PATH", root)
    monkeypatch.setattr(host_metrics, "CPU_SAMPLE_SECONDS", 0.01)
    monkeypatch.setattr(host_metrics, "_cpu_percent", lambda _: 12.5)

    metrics = host_metrics.collect_vps_metrics(lambda: None)

    assert metrics["collection_source"] == "host-mount"
    assert metrics["os_name"] == "Test Linux"
    assert metrics["kernel"] == "6.1.0-test"
    assert metrics["cpu_count"] == 2
    assert metrics["cpu_percent"] == 12.5
    assert metrics["load_1m"] == 0.1
    assert metrics["memory_percent"] == 25
    assert metrics["uptime_seconds"] == 1234.56
