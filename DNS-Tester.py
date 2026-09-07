#!/usr/bin/env python3

import argparse
import asyncio
import json
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import dns.asyncresolver
except ImportError:
    print("dnspython is not installed.")
    print("Run: python -m pip install dnspython rich")
    raise SystemExit(1)

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("rich is not installed.")
    print("Run: python -m pip install dnspython rich")
    raise SystemExit(1)


console = Console()


# ============================================================
# HELPERS
# ============================================================

def parse_dns_arg(value: str) -> tuple[str, str]:
    """
    Accept:
        1.1.1.1
        Cloudflare=1.1.1.1
    """
    value = value.strip()

    if "=" in value:
        name, ip = value.split("=", 1)
        name = name.strip()
        ip = ip.strip()

        if not ip:
            raise ValueError(f"Invalid DNS entry: {value}")

        return (name or ip), ip

    return value, value

def load_dns_file(path: str) -> list[tuple[str, str]]:
    """
    Load DNS servers from a file where each provider name
    is followed by one or more IP addresses.
    Blank lines are ignored.
    """

    lines = [
        line.strip()
        for line in Path(path)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
        and not line.strip().startswith("#")
    ]

    dns_servers = []
    current_name = None

    ip_pattern = re.compile(
        r"^(?:\d{1,3}\.){3}\d{1,3}$"
    )

    for line in lines:

        if ip_pattern.match(line):

            if current_name is None:
                raise ValueError(
                    f"DNS IP found before a provider name: {line}"
                )

            dns_servers.append(
                (current_name, line)
            )

        else:

            current_name = line

    return dns_servers

def load_lines(path: str) -> list[str]:
    """
    Load non-empty, non-comment lines from a text file.
    """
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

def parse_json_output(output: str) -> dict:
    """
    Parse JSON output even if the CLI prints extra text
    before or after the JSON object.
    """

    output = output.strip()

    if not output:
        raise json.JSONDecodeError(
            "Empty output",
            output,
            0,
        )

    # First try: output is pure JSON.
    try:
        data = json.loads(output)

        if isinstance(data, dict):
            return data

    except json.JSONDecodeError:
        pass

    # Second try: find a valid JSON object anywhere
    # inside the command output.
    decoder = json.JSONDecoder()

    for index, character in enumerate(output):

        if character != "{":
            continue

        try:
            data, _ = decoder.raw_decode(
                output[index:]
            )

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError(
        "Could not find valid JSON object in output",
        output,
        0,
    )


def mean_or_none(values: list[float]):
    if not values:
        return None

    return round(statistics.mean(values), 2)


def calc_jitter(values: list[float]):
    """
    Average absolute difference between consecutive latency samples.
    """
    if len(values) < 2:
        return None

    jitter = statistics.mean(
        abs(b - a)
        for a, b in zip(values, values[1:])
    )

    return round(jitter, 2)


def dns_rank_key(item):
    """
    Ranking priority:

    1. Domain success rate
    2. Overall query success rate
    3. Average latency
    """

    domain_rates = [
        value["success_rate"]
        for value in item["domain_results"].values()
    ]

    domain_success = (
        statistics.mean(domain_rates)
        if domain_rates
        else 0
    )

    query_success = item.get("query_success_rate") or 0

    latency = item.get("average_latency_ms")

    if latency is None:
        latency = float("inf")

    return (
        -domain_success,
        -query_success,
        latency,
    )


# ============================================================
# DIRECT DNS QUERY
# ============================================================

async def query_dns(
    server: str,
    domain: str,
    timeout: float,
) -> dict:
    """
    Query the specified DNS server directly.

    IMPORTANT:
    configure=False means dnspython does NOT read the
    operating system DNS configuration.

    resolver.nameservers = [server] forces the query
    to the specified DNS server.
    """

    resolver = dns.asyncresolver.Resolver(
        configure=False
    )

    resolver.nameservers = [server]
    resolver.timeout = timeout
    resolver.lifetime = timeout

    started = asyncio.get_running_loop().time()

    try:
        answer = await resolver.resolve(
            domain,
            "A",
        )

        elapsed = (
            asyncio.get_running_loop().time() - started
        ) * 1000

        return {
            "success": True,
            "latency_ms": round(elapsed, 2),
            "addresses": [
                str(record)
                for record in answer
            ],
            "error": None,
        }

    except Exception as exc:
        elapsed = (
            asyncio.get_running_loop().time() - started
        ) * 1000

        return {
            "success": False,
            "latency_ms": round(elapsed, 2),
            "addresses": [],
            "error": str(exc),
        }


# ============================================================
# TEST ONE DNS SERVER
# ============================================================

async def test_dns_server(
    name,
    server,
    domains,
    tests,
    timeout,
    semaphore,
):
    async with semaphore:

        all_query_latencies = []
        all_query_successes = 0

        domain_results = {}

        for domain in domains:

            successful_latencies = []
            last_addresses = []
            errors = []

            for _ in range(tests):

                result = await query_dns(
                    server,
                    domain,
                    timeout,
                )

                all_query_latencies.append(
                    result["latency_ms"]
                )

                if result["success"]:

                    all_query_successes += 1

                    successful_latencies.append(
                        result["latency_ms"]
                    )

                    last_addresses = result[
                        "addresses"
                    ]

                elif result["error"]:

                    errors.append(
                        result["error"]
                    )

            domain_results[domain] = {
                "success_rate": round(
                    len(successful_latencies)
                    / tests
                    * 100,
                    1,
                ),
                "average_latency_ms": mean_or_none(
                    successful_latencies
                ),
                "min_latency_ms": (
                    round(
                        min(successful_latencies),
                        2,
                    )
                    if successful_latencies
                    else None
                ),
                "max_latency_ms": (
                    round(
                        max(successful_latencies),
                        2,
                    )
                    if successful_latencies
                    else None
                ),
                "addresses": last_addresses,
                "errors": errors[:3],
            }

        total_queries = len(domains) * tests

        return {
            "name": name,
            "server": server,

            "query_success_rate": round(
                all_query_successes
                / total_queries
                * 100,
                1,
            )
            if total_queries
            else 0,

            "average_latency_ms": mean_or_none(
                all_query_latencies
            ),

            "min_latency_ms": (
                round(
                    min(all_query_latencies),
                    2,
                )
                if all_query_latencies
                else None
            ),

            "max_latency_ms": (
                round(
                    max(all_query_latencies),
                    2,
                )
                if all_query_latencies
                else None
            ),

            "jitter_ms": calc_jitter(
                all_query_latencies
            ),

            "domain_results": domain_results,
        }


# ============================================================
# RUN ALL DNS TESTS
# ============================================================

async def run_dns_tests(
    dns_servers,
    domains,
    tests,
    timeout,
    concurrency,
):
    semaphore = asyncio.Semaphore(
        concurrency
    )

    tasks = [
        test_dns_server(
            name,
            server,
            domains,
            tests,
            timeout,
            semaphore,
        )
        for name, server in dns_servers
    ]

    return await asyncio.gather(*tasks)


# ============================================================
# INTERNET PING
# ============================================================

def ping_internet():
    """
    Ping 1.1.1.1 to measure the current Internet
    connection latency.

    This is NOT a DNS test.
    """

    target = "1.1.1.1"

    command = [
        "ping",
        "-c",
        "5",
    ]

    system = platform.system().lower()

    if system == "windows":

        command = [
            "ping",
            "-n",
            "5",
            "-w",
            "5000",
            target,
        ]

    else:

        # macOS / Linux
        command = [
            "ping",
            "-c",
            "5",
            target,
        ]

    try:

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )

        output = (
            completed.stdout
            + completed.stderr
        )

        # macOS / Linux:
        #
        # round-trip min/avg/max/stddev = 12.345/...
        #
        # Linux can also use:
        #
        # rtt min/avg/max/mdev = ...

        match = re.search(
            r"(?:round-trip|rtt).*?=\s*"
            r"([\d.]+)\s*/\s*"
            r"([\d.]+)\s*/\s*"
            r"([\d.]+)\s*/\s*"
            r"([\d.]+)",
            output,
            re.IGNORECASE,
        )

        if match:

            minimum, average, maximum, stddev = map(
                float,
                match.groups(),
            )

            return {
                "target": target,
                "success": completed.returncode == 0,
                "min_ms": minimum,
                "avg_ms": average,
                "max_ms": maximum,
                "stddev_ms": stddev,
            }

        return {
            "target": target,
            "success": False,
            "error": "Could not parse ping result.",
        }

    except Exception as exc:

        return {
            "target": target,
            "success": False,
            "error": str(exc),
        }


# ============================================================
# INTERNET SPEED TEST
# ============================================================

def speedtest_internet():
    """
    Run an Internet speed test using an installed Speedtest CLI.

    The DNS benchmark itself does NOT use the system DNS.
    This Internet speed test is a separate measurement of the
    current Internet connection.

    Supported executables:
        - speedtest      (Ookla Speedtest CLI)
        - speedtest-cli  (Python speedtest-cli)
    """

    executable = None

    # Try Ookla first, then speedtest-cli.
    for command_name in ("speedtest", "speedtest-cli"):

        found = shutil.which(command_name)

        if found:
            executable = found
            break

    if not executable:

        return {
            "available": False,
            "success": False,
            "error": (
                "No Speedtest CLI found. "
                "Install either Ookla Speedtest CLI "
                "or speedtest-cli."
            ),
        }

    try:

        # ====================================================
        # OOKLA SPEEDTEST CLI
        # ====================================================

        if (
            executable.endswith("/speedtest")
            or executable == "speedtest"
        ):

            completed = subprocess.run(
                [
                    executable,
                    "--accept-license",
                    "--accept-gdpr",
                    "--format=json",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )

            if completed.returncode != 0:

                error_message = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or "speedtest failed"
                )

                return {
                    "available": True,
                    "success": False,
                    "executable": executable,
                    "error": error_message,
                }

            # Ookla may print additional text around
            # the JSON output, so use the robust parser.
            data = parse_json_output(
                completed.stdout
            )

            download_data = data.get(
                "download",
                {},
            )

            upload_data = data.get(
                "upload",
                {},
            )

            ping_data = data.get(
                "ping",
                {},
            )

            server_data = data.get(
                "server",
                {},
            )

            download_bps = download_data.get(
                "bandwidth"
            )

            upload_bps = upload_data.get(
                "bandwidth"
            )

            return {
                "available": True,
                "success": True,
                "executable": executable,

                "download_mbps": (
                    round(
                        download_bps
                        * 8
                        / 1_000_000,
                        2,
                    )
                    if download_bps is not None
                    else None
                ),

                "upload_mbps": (
                    round(
                        upload_bps
                        * 8
                        / 1_000_000,
                        2,
                    )
                    if upload_bps is not None
                    else None
                ),

                "ping_ms": ping_data.get(
                    "latency"
                ),

                "server": server_data.get(
                    "name"
                ),

                "server_location": server_data.get(
                    "location"
                ),

                "isp": data.get(
                    "isp"
                ),
            }

        # ====================================================
        # SPEEDTEST-CLI
        # ====================================================

        completed = subprocess.run(
            [
                executable,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        if completed.returncode != 0:

            return {
                "available": True,
                "success": False,
                "executable": executable,
                "error": (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or "speedtest-cli failed"
                ),
            }

        data = parse_json_output(
            completed.stdout
        )

        # speedtest-cli returns download/upload
        # directly in bits per second.

        download_bps = data.get(
            "download"
        )

        upload_bps = data.get(
            "upload"
        )

        server_data = data.get(
            "server",
            {},
        )

        client_data = data.get(
            "client",
            {},
        )

        return {
            "available": True,
            "success": True,
            "executable": executable,

            "download_mbps": (
                round(
                    download_bps
                    / 1_000_000,
                    2,
                )
                if download_bps is not None
                else None
            ),

            "upload_mbps": (
                round(
                    upload_bps
                    / 1_000_000,
                    2,
                )
                if upload_bps is not None
                else None
            ),

            "ping_ms": data.get(
                "ping"
            ),

            "server": server_data.get(
                "sponsor"
            ),

            "server_location": server_data.get(
                "name"
            ),

            "isp": client_data.get(
                "isp"
            ),
        }

    # ========================================================
    # ERROR HANDLING
    # ========================================================

    except json.JSONDecodeError:

        return {
            "available": True,
            "success": False,
            "executable": executable,
            "error": (
                "Could not parse Speedtest "
                "JSON output."
            ),
        }

    except FileNotFoundError:

        return {
            "available": False,
            "success": False,
            "executable": executable,
            "error": (
                "Speedtest executable "
                "was not found."
            ),
        }

    except subprocess.TimeoutExpired:

        return {
            "available": True,
            "success": False,
            "executable": executable,
            "error": (
                "Speedtest timed out "
                "after 180 seconds."
            ),
        }

    except Exception as exc:

        return {
            "available": True,
            "success": False,
            "executable": executable,
            "error": str(exc),
        }

# ============================================================
# RICH TABLES
# ============================================================

def print_dns_table(results):

    table = Table(
        title="DNS Performance"
    )

    columns = [
        "#",
        "DNS",
        "Server",
        "Success",
        "Avg",
        "Min",
        "Max",
        "Jitter",
        "Domains OK",
    ]

    for column in columns:

        table.add_column(
            column,
            justify=(
                "right"
                if column == "#"
                else "left"
            ),
        )

    sorted_results = sorted(
        results,
        key=dns_rank_key,
    )

    for index, item in enumerate(
        sorted_results,
        1,
    ):

        domain_results = item[
            "domain_results"
        ]

        domains_ok = sum(
            result["success_rate"] >= 100
            for result in domain_results.values()
        )

        avg = item[
            "average_latency_ms"
        ]

        minimum = item[
            "min_latency_ms"
        ]

        maximum = item[
            "max_latency_ms"
        ]

        jitter = item[
            "jitter_ms"
        ]

        table.add_row(
            str(index),

            item["name"],

            item["server"],

            f'{item["query_success_rate"]:.1f}%',

            (
                f"{avg:.2f} ms"
                if avg is not None
                else "-"
            ),

            (
                f"{minimum:.2f} ms"
                if minimum is not None
                else "-"
            ),

            (
                f"{maximum:.2f} ms"
                if maximum is not None
                else "-"
            ),

            (
                f"{jitter:.2f} ms"
                if jitter is not None
                else "-"
            ),

            f"{domains_ok}/{len(domain_results)}",
        )

    console.print(table)


def print_domain_table(
    results,
    domains,
):

    table = Table(
        title="Domain Resolution"
    )

    table.add_column(
        "DNS"
    )

    for domain in domains:

        table.add_column(
            domain
        )

    for item in sorted(
        results,
        key=dns_rank_key,
    ):

        cells = [
            item["name"]
        ]

        for domain in domains:

            result = item[
                "domain_results"
            ][domain]

            success_rate = result[
                "success_rate"
            ]

            latency = result[
                "average_latency_ms"
            ]

            if success_rate > 0:

                if latency is not None:

                    cells.append(
                        f"✓ {success_rate:.0f}% / "
                        f"{latency:.1f}ms"
                    )

                else:

                    cells.append(
                        f"✓ {success_rate:.0f}%"
                    )

            else:

                cells.append(
                    "✗ 0%"
                )

        table.add_row(
            *cells
        )

    console.print(table)


def print_internet_results(
    ping_result,
    speed_result,
):

    table = Table(
        title="Internet Connection"
    )

    table.add_column(
        "Test"
    )

    table.add_column(
        "Result"
    )

    # ------------------------
    # Ping
    # ------------------------

    if ping_result.get(
        "success"
    ):

        table.add_row(
            "Ping",
            (
                f'{ping_result["avg_ms"]:.2f} ms avg'
            ),
        )

        table.add_row(
            "Ping Range",
            (
                f'{ping_result["min_ms"]:.2f} / '
                f'{ping_result["max_ms"]:.2f} ms'
            ),
        )

        table.add_row(
            "Ping Jitter",
            (
                f'{ping_result["stddev_ms"]:.2f} ms'
            ),
        )

    else:

        table.add_row(
            "Ping",
            (
                "Failed: "
                + ping_result.get(
                    "error",
                    "unknown error",
                )
            ),
        )

    # ------------------------
    # Speedtest
    # ------------------------

    if speed_result.get(
        "success"
    ):

        download = speed_result.get(
            "download_mbps"
        )

        upload = speed_result.get(
            "upload_mbps"
        )

        if download is not None:

            table.add_row(
                "Download",
                f"{download:.2f} Mbps",
            )

        if upload is not None:

            table.add_row(
                "Upload",
                f"{upload:.2f} Mbps",
            )

        ping = speed_result.get(
            "ping_ms"
        )

        if ping is not None:

            table.add_row(
                "Speedtest Ping",
                f"{ping:.2f} ms",
            )

        if speed_result.get(
            "server"
        ):

            table.add_row(
                "Speedtest Server",
                str(
                    speed_result["server"]
                ),
            )

        if speed_result.get(
            "server_location"
        ):

            table.add_row(
                "Server Location",
                str(
                    speed_result[
                        "server_location"
                    ]
                ),
            )

        if speed_result.get(
            "isp"
        ):

            table.add_row(
                "ISP",
                str(
                    speed_result["isp"]
                ),
            )

    else:

        table.add_row(
            "Speedtest",
            speed_result.get(
                "error",
                "Unavailable",
            ),
        )

    console.print(table)


# ============================================================
# ARGUMENT PARSER
# ============================================================

def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Test DNS servers directly without "
            "changing or using the system DNS configuration."
        )
    )

    parser.add_argument(
        "--dns",
        action="append",
        help=(
            'DNS server in the form "Name=IP". '
            "Can be repeated."
        ),
    )

    parser.add_argument(
        "--dns-file",
        help=(
            "Text file containing DNS servers, "
            "one per line."
        ),
    )

    parser.add_argument(
        "--domain",
        action="append",
        help=(
            "Domain to test. "
            "Can be repeated."
        ),
    )

    parser.add_argument(
        "--domain-file",
        help=(
            "Text file containing domains, "
            "one per line."
        ),
    )

    parser.add_argument(
        "--tests",
        type=int,
        default=5,
        help=(
            "Number of repetitions per domain. "
            "Default: 5"
        ),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help=(
            "DNS timeout in seconds. "
            "Default: 2"
        ),
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help=(
            "Maximum number of DNS servers tested "
            "concurrently. Default: 8"
        ),
    )

    parser.add_argument(
        "--output",
        default="DNS-Results.json",
        help=(
            "JSON output filename. "
            "Default: DNS-Results.json"
        ),
    )

    parser.add_argument(
        "--no-speedtest",
        action="store_true",
        help=(
            "Skip download/upload speed test."
        ),
    )

    return parser


# ============================================================
# MAIN
# ============================================================

def main():

    parser = build_parser()

    args = parser.parse_args()

    # ------------------------
    # Validate arguments
    # ------------------------

    if args.tests < 1:

        parser.error(
            "--tests must be >= 1"
        )

    if args.timeout <= 0:

        parser.error(
            "--timeout must be > 0"
        )

    if args.concurrency < 1:

        parser.error(
            "--concurrency must be >= 1"
        )

    # ------------------------
    # Load DNS servers
    # ------------------------

    dns_servers = []
    script_dir = Path(__file__).resolve().parent

    default_dns_file = (
        script_dir / "DNS.txt"
        )

    default_domains_file = (
        script_dir / "Domains.txt"
        )

    if args.dns:

        for entry in args.dns:

            try:

                name, address = parse_dns_arg(
                    entry
                )

                dns_servers.append(
                    (name, address)
                )

            except ValueError as exc:

                parser.error(
                    str(exc)
                )

    if args.dns_file:

        try:

            dns_servers.extend(
                load_dns_file(
                    args.dns_file
                )
            )

        except (OSError, ValueError) as exc:

            parser.error(
                f"Could not read DNS file: {exc}"
            )

    if not dns_servers:

        if not default_dns_file.exists():

            parser.error(
                "No DNS servers were provided. "
                f"Create '{default_dns_file}' "
                "and put your DNS servers in it."
            )

        try:

            dns_servers.extend(
                load_dns_file(
                    str(default_dns_file)
                )
            )

        except (OSError, ValueError) as exc:

            parser.error(
                f"Could not read DNS file: {exc}"
            )

    # ------------------------
    # Load domains
    # ------------------------

    domains = []

    if args.domain:

        domains.extend(
            args.domain
        )

    if args.domain_file:

        try:

            domains.extend(
                load_lines(
                    args.domain_file
                )
            )

        except OSError as exc:

            parser.error(
                f"Could not read domain file: {exc}"
            )

    if not domains:

        if not default_domains_file.exists():

            parser.error(
                "No domains were provided. "
                f"Create '{default_domains_file}' "
                "and put your domains in it."
            )

        try:

            domains.extend(
                load_lines(
                    str(default_domains_file)
                )
            )

        except OSError as exc:

            parser.error(
                f"Could not read domain file: {exc}"
            )

    # ------------------------
    # Deduplicate DNS servers
    # ------------------------

    unique_dns = []

    seen_dns = set()

    for name, address in dns_servers:

        name = name.strip()

        address = address.strip()

        key = (
            name.lower(),
            address,
        )

        if key not in seen_dns:

            seen_dns.add(key)

            unique_dns.append(
                (name, address)
            )

    # ------------------------
    # Deduplicate domains
    # ------------------------

    unique_domains = []

    seen_domains = set()

    for domain in domains:

        domain = (
            domain
            .strip()
            .rstrip(".")
            .lower()
        )

        if (
            domain
            and domain not in seen_domains
        ):

            seen_domains.add(
                domain
            )

            unique_domains.append(
                domain
            )

    if not unique_domains:

        parser.error(
            "No valid domains were provided."
        )

    if not unique_dns:

        parser.error(
            "No valid DNS servers were provided."
        )

    # ========================================================
    # START
    # ========================================================

    console.print()

    console.print(
        "[bold]DNS Tester[/bold]"
    )

    console.print(
        "=" * 60
    )

    console.print(
        f"DNS servers : {len(unique_dns)}"
    )

    console.print(
        f"Domains     : {len(unique_domains)}"
    )

    console.print(
        f"Tests/domain: {args.tests}"
    )

    console.print(
        f"Timeout     : {args.timeout:.2f}s"
    )

    console.print(
        f"Concurrency : {args.concurrency}"
    )

    console.print(
        "System DNS  : NOT changed / NOT used"
    )

    console.print()

    # ========================================================
    # INTERNET TEST
    # ========================================================

    console.print(
        "[bold]Testing Internet connection...[/bold]"
    )

    internet_ping = ping_internet()

    if args.no_speedtest:

        speedtest_result = {
            "available": False,
            "success": False,
            "error": (
                "Skipped by --no-speedtest"
            ),
        }

    else:

        console.print(
            "Running speed test..."
        )

        speedtest_result = (
            speedtest_internet()
        )

    # ========================================================
    # DNS TEST
    # ========================================================

    console.print(
        "Testing DNS servers..."
    )

    start_time = time.perf_counter()

    try:

        results = asyncio.run(
            run_dns_tests(
                unique_dns,
                unique_domains,
                args.tests,
                args.timeout,
                args.concurrency,
            )
        )

    except KeyboardInterrupt:

        console.print(
            "\nStopped by user."
        )

        return

    elapsed = (
        time.perf_counter()
        - start_time
    )

    results.sort(
        key=dns_rank_key
    )

    # ========================================================
    # RESULTS
    # ========================================================

    console.print()

    print_dns_table(
        results
    )

    console.print()

    print_domain_table(
        results,
        unique_domains,
    )

    console.print()

    print_internet_results(
        internet_ping,
        speedtest_result,
    )

    # ========================================================
    # JSON OUTPUT
    # ========================================================

    output = {
        "timestamp_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),

        "duration_seconds": round(
            elapsed,
            2,
        ),

        "tests_per_domain": (
            args.tests
        ),

        "timeout_seconds": (
            args.timeout
        ),

        "concurrency": (
            args.concurrency
        ),

        "system_dns_changed": False,

        "system_dns_used_for_dns_tests": False,

        "dns_servers": [
            {
                "name": name,
                "server": server,
            }
            for name, server
            in unique_dns
        ],

        "domains": unique_domains,

        "dns_results": results,

        "internet_ping": (
            internet_ping
        ),

        "internet_speedtest": (
            speedtest_result
        ),
    }

    # ========================================================
    # SAVE JSON
    # ========================================================

    try:

        output_path = (
            Path(args.output)
            .expanduser()
        )

        output_path.write_text(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        console.print()

        console.print(
            f"[bold]JSON saved to:[/bold] "
            f"{output_path}"
        )

    except OSError as exc:

        console.print(
            f"\nWarning: could not save JSON file: {exc}"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\nStopped by user."
        )

    except Exception as exc:

        print(
            f"\nUnexpected error: {exc}",
            file=sys.stderr,
        )

        raise