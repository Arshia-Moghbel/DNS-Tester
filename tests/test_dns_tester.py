import importlib.util
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "DNS-Tester.py"


def load_module():
    """Load the CLI module without requiring its optional UI dependencies."""
    dns_module = types.ModuleType("dns")
    asyncresolver_module = types.ModuleType("dns.asyncresolver")
    exception_module = types.ModuleType("dns.exception")
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    table_module = types.ModuleType("rich.table")

    class Resolver:
        pass

    class Timeout(Exception):
        pass

    class Console:
        def print(self, *args, **kwargs):
            pass

    class Table:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            pass

    asyncresolver_module.Resolver = Resolver
    exception_module.Timeout = Timeout
    dns_module.asyncresolver = asyncresolver_module
    dns_module.exception = exception_module
    console_module.Console = Console
    table_module.Table = Table

    modules = {
        "dns": dns_module,
        "dns.asyncresolver": asyncresolver_module,
        "dns.exception": exception_module,
        "rich": rich_module,
        "rich.console": console_module,
        "rich.table": table_module,
    }

    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("dns_tester", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


dns_tester = load_module()


class DnsConfigurationTests(unittest.TestCase):
    def test_parse_dns_arg_accepts_ipv6_and_rejects_invalid_address(self):
        self.assertEqual(
            dns_tester.parse_dns_arg("Cloudflare=2606:4700:4700::1111"),
            ("Cloudflare", "2606:4700:4700::1111"),
        )

        with self.assertRaisesRegex(ValueError, "Invalid DNS server address"):
            dns_tester.parse_dns_arg("Cloudflare=999.999.999.999")

    def test_load_dns_file_normalizes_addresses(self):
        path = self._write_config("Provider\n2001:0db8::1\n")
        self.assertEqual(
            dns_tester.load_dns_file(path),
            [("Provider", "2001:db8::1")],
        )

    def _write_config(self, contents):
        path = ROOT / "tests" / "temporary-dns.txt"
        self.addCleanup(path.unlink, missing_ok=True)
        path.write_text(contents, encoding="utf-8")
        return str(path)


class ExternalCliTests(unittest.TestCase):
    def test_windows_ping_summary_is_parsed(self):
        completed = subprocess.CompletedProcess(
            ["ping"],
            0,
            stdout="Minimum = 12ms, Maximum = 35ms, Average = 20ms",
            stderr="",
        )

        with patch.object(dns_tester.platform, "system", return_value="Windows"), patch.object(
            dns_tester.subprocess, "run", return_value=completed
        ):
            result = dns_tester.ping_internet()

        self.assertTrue(result["success"])
        self.assertEqual(result["avg_ms"], 20.0)
        self.assertIsNone(result["stddev_ms"])

    def test_ookla_json_is_converted_from_bytes_per_second(self):
        ookla_result = {
            "download": {"bandwidth": 12_500_000},
            "upload": {"bandwidth": 2_500_000},
            "ping": {"latency": 11.5},
            "server": {"name": "Example", "location": "Tehran"},
            "isp": "Example ISP",
            "interface": {"externalIp": "203.0.113.1"},
        }
        completed = subprocess.CompletedProcess(
            ["speedtest"], 0, stdout=json.dumps(ookla_result), stderr=""
        )

        with patch.object(dns_tester.shutil, "which", side_effect=lambda name: "/usr/bin/speedtest" if name == "speedtest" else None), patch.object(
            dns_tester.subprocess, "run", return_value=completed
        ):
            result = dns_tester.speedtest_internet()

        self.assertTrue(result["success"])
        self.assertEqual(result["download_mbps"], 100.0)
        self.assertEqual(result["upload_mbps"], 20.0)
        self.assertEqual(result["ping_ms"], 11.5)
        self.assertEqual(result["server_location"], "Tehran")


if __name__ == "__main__":
    unittest.main()
