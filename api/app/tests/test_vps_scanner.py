"""Tests for VPS host listener + vhost parsing."""
import tempfile
from pathlib import Path

from app.collectors import vps_scanner as vs
from app.collectors.vps_scanner import apache_hosts_by_port_from_content, nginx_hosts_by_port_from_content


def test_ipv4_hex_decode():
    assert vs._ipv4_from_hex("0100007F") == "127.0.0.1"
    assert vs._ipv4_from_hex("00000000") == "0.0.0.0"


def test_parse_proc_tcp_listen_ports_skips_loopback():
    sample = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345
   1: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12346
   2: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12347
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tcp", delete=False) as f:
        f.write(sample)
        path = f.name
    try:
        ports = vs._parse_listen_ports_from_proc(path)
        assert 80 in ports
        assert 8080 in ports  # 0x1f90
        assert ports.count(80) == 1
    finally:
        Path(path).unlink(missing_ok=True)


def test_nginx_server_blocks_map_listen_ports():
    cfg = """
    server {
        listen 80;
        server_name a.example.com;
    }
    server {
        listen 443 ssl;
        server_name b.example.com www.b.example.com;
    }
    """
    m = nginx_hosts_by_port_from_content(cfg)
    assert m[80] == ["a.example.com"]
    assert m[443][:2] == ["b.example.com", "www.b.example.com"]


def test_apache_virtualhost_block_ports():
    cfg = """
    <VirtualHost *:80>
        ServerName c.example.com
    </VirtualHost>
    <VirtualHost *:443>
        ServerAlias d.example.com
    </VirtualHost>
    """
    m = apache_hosts_by_port_from_content(cfg)
    assert m[80] == ["c.example.com"]
    assert m[443] == ["d.example.com"]


def test_expand_server_names_splits_and_skips_wildcards():
    got = vs._expand_server_names("example.com www.example.com")
    assert got == ["example.com", "www.example.com"]
    assert vs._expand_server_names("*.example.com") == []
