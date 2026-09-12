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
    import dns.exception
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
    Blank lines and comments are ignored.
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
        for line in Path(path)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
        and not line.strip().startswith("#")
    ]


def parse_json_output(text):
    """
    Safely extract JSON from CLI output.

    Some CLI versions may print additional text before or
    after the JSON object.
    """

    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()

    for index, char in enumerate(text):

        if char != "{":
            continue

        try:
            data, _ = decoder.raw_decode(
                text[index:]
            )
            return data

        except json.JSONDecodeError:
            continue

    return None


def mean_or_none(values: list[float]):
    if not values:
        return None

    return round(
        statistics.mean(values),
        2,
    )


def calc_jitter(values: list[float]):
    """
    Average absolute difference between consecutive
    successful latency samples.

    Failed and timeout queries must never be included.
    """

    if len(values) < 2:
        return None

    jitter = statistics.mean(
        abs(b - a)
        for a, b in zip(values, values[1:])
    )

    return round(
        jitter,
        2,
    )


def dns_rank_key(item):
    """
    Ranking priority:

    1. Domain success rate
    2. Overall query success rate
    3. Average latency of successful queries
    4. Lower jitter

    Failed/timeout queries are never included in latency
    or jitter calculations.
    """

    domain_results = item.get(
        "domain_results",
        {},
    )

    domain_rates = [
        value["success_rate"]
        for value in domain_results.values()
    ]

    domain_success = (
        statistics.mean(domain_rates)
        if domain_rates
        else 0
    )

    query_success = (
        item.get("query_success_rate")
        or 0
    )

    latency = item.get(
        "average_latency_ms"
    )

    if latency is None:
        latency = float("inf")

    jitter = item.get(
        "jitter_ms"
    )

    if jitter is None:
        jitter = float("inf")

    return (
        -domain_success,
        -query_success,
        latency,
        jitter,
    )


# ============================================================
# DIRECT DNS QUERY
# ============================================================

async def query_dns(server, domain, timeout):
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = [server]
    resolver.timeout = timeout
    resolver.lifetime = timeout

    start = time.perf_counter()

    try:
        answer = await resolver.resolve(domain, "A")
        elapsed = (time.perf_counter() - start) * 1000

        addresses = [str(r) for r in answer]

        return {
            "success": True,
            "latency_ms": elapsed,
            "addresses": addresses,
            "error": None,
            "timed_out": False,
        }

    except dns.exception.Timeout as e:
        elapsed = (time.perf_counter() - start) * 1000

        return {
            "success": False,
            "latency_ms": elapsed,
            "addresses": [],
            "error": f"Timeout: {e}",
            "timed_out": True,
        }

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000

        return {
            "success": False,
            "latency_ms": elapsed,
            "addresses": [],
            "error": str(e),
            "timed_out": False,
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

        successful_query_latencies = []

        all_query_successes = 0
        all_query_failures = 0
        timeout_count = 0

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

                if result["success"]:

                    all_query_successes += 1

                    latency = result.get(
                        "latency_ms"
                    )

                    if latency is not None:

                        successful_query_latencies.append(
                            latency
                        )

                        successful_latencies.append(
                            latency
                        )

                    last_addresses = result[
                        "addresses"
                    ]

                else:

                    all_query_failures += 1

                    if result.get("timed_out", False):

                        timeout_count += 1

                    if result["error"]:

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

                "jitter_ms": calc_jitter(
                    successful_latencies
                ),

                "addresses": last_addresses,

                "errors": errors[:3],
            }

        total_queries = (
            len(domains)
            * tests
        )


        return {

            "name": name,

            "server": server,

            "query_success_rate": (
                round(
                    all_query_successes
                    / total_queries
                    * 100,
                    1,
                )
                if total_queries
                else 0
            ),

            "timeout_rate": (
                round(
                    timeout_count
                    / total_queries
                    * 100,
                    1,
                )
                if total_queries
                else 0
            ),

            "successful_queries":
                all_query_successes,

            "failed_queries":
                all_query_failures,

            "total_queries":
                total_queries,

            "average_latency_ms":
                mean_or_none(
                    successful_query_latencies
                ),

            "min_latency_ms": (
                round(
                    min(
                        successful_query_latencies
                    ),
                    2,
                )
                if successful_query_latencies
                else None
            ),

            "max_latency_ms": (
                round(
                    max(
                        successful_query_latencies
                    ),
                    2,
                )
                if successful_query_latencies
                else None
            ),

            "jitter_ms": calc_jitter(
                successful_query_latencies
            ),

            "domain_results":
                domain_results,
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

        for name, server
        in dns_servers
    ]

    return await asyncio.gather(
        *tasks
    )


# ============================================================
# INTERNET PING
# ============================================================

def ping_internet():
    """
    Ping 1.1.1.1 to measure current Internet
    connection latency.

    This is NOT a DNS test.
    """

    target = "1.1.1.1"

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

                "success":
                    completed.returncode == 0,

                "min_ms": minimum,

                "avg_ms": average,

                "max_ms": maximum,

                "stddev_ms": stddev,
            }

        return {

            "target": target,

            "success": False,

            "error":
                "Could not parse ping result.",
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
    Run an Internet speed test using speedtest-cli.

    The Python speedtest-cli package normally exposes
    the executable as `speedtest-cli`.

    JSON is attempted first.

    If JSON cannot be parsed, --simple is used as
    a fallback.

    Duplicate DNS entries are not affected by this function.
    """

    executable = None

    # IMPORTANT:
    # Prefer speedtest-cli because the installed program
    # in this project uses the speedtest-cli argument syntax.

    for command_name in (
        "speedtest-cli",
        "speedtest",
    ):

        found = shutil.which(
            command_name
        )

        if found:

            executable = found

            break

    if not executable:

        return {

            "available": False,

            "success": False,

            "error": (
                "No speedtest-cli executable found. "
                "Install it with: "
                "python -m pip install speedtest-cli"
            ),
        }

    def run_command(arguments):

        return subprocess.run(

            [
                executable,
                *arguments,
            ],

            capture_output=True,

            text=True,

            timeout=180,
        )

    def parse_speedtest_cli_json(data):

        if not isinstance(
            data,
            dict,
        ):
            return None

        download_bps = data.get(
            "download"
        )

        upload_bps = data.get(
            "upload"
        )

        if not isinstance(
            download_bps,
            (int, float),
        ):
            return None

        if not isinstance(
            upload_bps,
            (int, float),
        ):
            return None

        server_data = (
            data.get("server")
            or {}
        )

        client_data = (
            data.get("client")
            or {}
        )

        return {

            "available": True,

            "success": True,

            "executable":
                executable,

            "download_mbps":
                round(
                    download_bps
                    / 1_000_000,
                    2,
                ),

            "upload_mbps":
                round(
                    upload_bps
                    / 1_000_000,
                    2,
                ),

            "ping_ms":
                data.get("ping"),

            "server":
                (
                    server_data.get(
                        "sponsor"
                    )
                    or server_data.get(
                        "name"
                    )
                ),

            "server_location":
                server_data.get(
                    "name"
                ),

            "isp":
                client_data.get(
                    "isp"
                ),

            "public_ip":
                client_data.get(
                    "ip"
                ),

            "method":
                "json",
        }

    try:

        # ====================================================
        # FIRST ATTEMPT: JSON
        # ====================================================

        completed = run_command(
            ["--json"]
        )

        stdout = (
            completed.stdout
            or ""
        )

        stderr = (
            completed.stderr
            or ""
        )

        data = parse_json_output(
            stdout
        )

        if data is None:

            data = parse_json_output(
                stderr
            )

        if data is not None:

            parsed = (
                parse_speedtest_cli_json(
                    data
                )
            )

            if parsed is not None:

                return parsed

        # ====================================================
        # SECOND ATTEMPT: SIMPLE
        # ====================================================

        simple = run_command(
            ["--simple"]
        )

        simple_stdout = (
            simple.stdout
            or ""
        )

        simple_stderr = (
            simple.stderr
            or ""
        )

        ping_ms = None

        download_mbps = None

        upload_mbps = None

        for line in simple_stdout.splitlines():

            line = line.strip()

            # Ping

            match = re.match(
                r"^Ping:\s*([\d.]+)\s*ms$",
                line,
                re.IGNORECASE,
            )

            if match:

                ping_ms = float(
                    match.group(1)
                )

                continue

            # Download

            match = re.match(
                r"^Download:\s*([\d.]+)\s*Mbit/s$",
                line,
                re.IGNORECASE,
            )

            if match:

                download_mbps = float(
                    match.group(1)
                )

                continue

            # Upload

            match = re.match(
                r"^Upload:\s*([\d.]+)\s*Mbit/s$",
                line,
                re.IGNORECASE,
            )

            if match:

                upload_mbps = float(
                    match.group(1)
                )

        if (

            simple.returncode == 0

            and download_mbps is not None

            and upload_mbps is not None

        ):

            return {

                "available": True,

                "success": True,

                "executable":
                    executable,

                "download_mbps":
                    round(
                        download_mbps,
                        2,
                    ),

                "upload_mbps":
                    round(
                        upload_mbps,
                        2,
                    ),

                "ping_ms":
                    ping_ms,

                "server":
                    None,

                "server_location":
                    None,

                "isp":
                    None,

                "public_ip":
                    None,

                "method":
                    "simple",
            }

        diagnostic = (

            simple_stderr.strip()

            or simple_stdout.strip()

            or stderr.strip()

            or stdout.strip()

            or (
                "speedtest-cli returned "
                "no usable result"
            )
        )

        return {

            "available": True,

            "success": False,

            "executable":
                executable,

            "error":
                "Could not obtain a valid speedtest result.",

            "raw_output":
                diagnostic[:1000],

            "return_code":
                simple.returncode,
        }

    except FileNotFoundError:

        return {

            "available": False,

            "success": False,

            "executable":
                executable,

            "error":
                "Speedtest executable was not found.",
        }

    except subprocess.TimeoutExpired:

        return {

            "available": True,

            "success": False,

            "executable":
                executable,

            "error":
                "Speedtest timed out after 180 seconds.",
        }

    except Exception as exc:

        return {

            "available": True,

            "success": False,

            "executable":
                executable,

            "error":
                str(exc),
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

        "Timeout",

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

            for result
            in domain_results.values()
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

            (
                f'{item["query_success_rate"]:.1f}%'
            ),

            (
                f'{item["timeout_rate"]:.1f}%'
            ),

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

    console.print(
        table
    )


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

    console.print(
        table
    )


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

    # ========================================================
    # PING
    # ========================================================

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

    # ========================================================
    # SPEEDTEST
    # ========================================================

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
                    speed_result[
                        "server"
                    ]
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
                    speed_result[
                        "isp"
                    ]
                ),
            )

        if speed_result.get(
            "public_ip"
        ):

            table.add_row(

                "Public IP",

                str(
                    speed_result[
                        "public_ip"
                    ]
                ),
            )

    else:

        table.add_row(

            "Speedtest",

            speed_result.get(

                "error",

                "Unknown error",
            ),
        )

        raw_output = speed_result.get(
            "raw_output"
        )

        if raw_output:

            debug_output = " ".join(
                raw_output.split()
            )

            table.add_row(

                "Speedtest Debug",

                debug_output[:300],
            )

    console.print(
        table
    )


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

            "Text file containing DNS servers."
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

            "Text file containing domains."
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
        
    overall_start = time.perf_counter()
    start_datetime = datetime.now().astimezone()

    print()
    print(f"Started : {start_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    parser = build_parser()

    args = parser.parse_args()

    # ========================================================
    # VALIDATE ARGUMENTS
    # ========================================================

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

    # ========================================================
    # LOAD DNS SERVERS
    # ========================================================

    dns_servers = []

    script_dir = (
        Path(__file__)
        .resolve()
        .parent
    )

    default_dns_file = (
        script_dir
        / "DNS.txt"
    )

    default_domains_file = (
        script_dir
        / "Domains.txt"
    )

    if args.dns:

        for entry in args.dns:

            try:

                name, address = (
                    parse_dns_arg(
                        entry
                    )
                )

                dns_servers.append(
                    (
                        name,
                        address,
                    )
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

        except (
            OSError,
            ValueError,
        ) as exc:

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
                    str(
                        default_dns_file
                    )
                )
            )

        except (
            OSError,
            ValueError,
        ) as exc:

            parser.error(

                f"Could not read DNS file: {exc}"
            )

    # ========================================================
    # LOAD DOMAINS
    # ========================================================

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
                    str(
                        default_domains_file
                    )
                )
            )

        except OSError as exc:

            parser.error(

                f"Could not read domain file: {exc}"
            )

    # ========================================================
    # DNS DUPLICATES
    # ========================================================
    #
    # IMPORTANT:
    # DNS duplicates are intentionally preserved.
    #
    # The original implementation deduplicated DNS entries.
    # That behavior is removed so duplicate entries in DNS.txt
    # remain separate test rows.
    #
    # ========================================================

    unique_dns = [

        (
            name.strip(),
            address.strip(),
        )

        for name, address
        in dns_servers

        if name.strip()
        and address.strip()
    ]

    # ========================================================
    # DEDUPLICATE DOMAINS
    # ========================================================

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

            and domain
            not in seen_domains

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

        f"DNS servers : "
        f"{len(unique_dns)}"
    )

    console.print(

        f"Domains     : "
        f"{len(unique_domains)}"
    )

    console.print(

        f"Tests/domain: "
        f"{args.tests}"
    )

    console.print(

        f"Timeout     : "
        f"{args.timeout:.2f}s"
    )

    console.print(

        f"Concurrency : "
        f"{args.concurrency}"
    )

    console.print(

        "System DNS  : "
        "NOT changed / NOT used"
    )

    console.print()

    # ========================================================
    # INTERNET TEST
    # ========================================================

    console.print(

        "[bold]Testing Internet connection...[/bold]"
    )

    internet_ping = (
        ping_internet()
    )

    if args.no_speedtest:

        speedtest_result = {

            "available": False,

            "success": False,

            "error":
                "Skipped by --no-speedtest",
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

    dns_start = time.perf_counter()

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

    dns_elapsed = (
        time.perf_counter()
        - dns_start
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

    end_datetime = datetime.now().astimezone()

    total_elapsed = (

        time.perf_counter()

        - overall_start

    )

    output = {

        "timestamp_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "run": {

            "started_local":
                start_datetime.isoformat(),

            "finished_local":
                end_datetime.isoformat(),

            "dns_testing_seconds":
                round(
                    dns_elapsed,
                    2,
                ),

            "total_seconds":
                round(
                    total_elapsed,
                    2,
                ),
        },

        "duration_seconds":
            round(
                total_elapsed,
                2,
            ),

        "settings": {

            "dns_servers_tested":
                len(unique_dns),

            "domains_tested":
                len(unique_domains),

            "tests_per_domain":
                args.tests,

            "timeout_seconds":
                args.timeout,

            "concurrency":
                args.concurrency,
        },

        "system_dns_changed":
            False,

        "system_dns_used_for_dns_tests":
            False,

        "dns_results": [

            {

                "rank":
                    index,

                "dns":
                    item["name"],

                "server":
                    item["server"],

                "success_rate":
                    item[
                        "query_success_rate"
                    ],

                "timeout_rate":
                    item[
                        "timeout_rate"
                    ],

                "successful_queries":
                    item[
                        "successful_queries"
                    ],

                "failed_queries":
                    item[
                        "failed_queries"
                    ],

                "total_queries":
                    item[
                        "total_queries"
                    ],

                "average_latency_ms":
                    item[
                        "average_latency_ms"
                    ],

                "min_latency_ms":
                    item[
                        "min_latency_ms"
                    ],

                "max_latency_ms":
                    item[
                        "max_latency_ms"
                    ],

                "jitter_ms":
                    item[
                        "jitter_ms"
                    ],

                "domains_ok":
                    sum(

                        result[
                            "success_rate"
                        ] >= 100

                        for result
                        in item[
                            "domain_results"
                        ].values()
                    ),

                "domains_total":
                    len(
                        item[
                            "domain_results"
                        ]
                    ),

                "domain_results":
                    item[
                        "domain_results"
                    ],
            }

            for index, item
            in enumerate(
                results,
                1,
            )
        ],

        "internet": {

            "ping":
                internet_ping,

            "speedtest":
                speedtest_result,
        },
    }

    # ========================================================
    # SAVE JSON
    # ========================================================

    try:

        output_path = (
            Path(
                args.output
            )
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

            "[bold]JSON saved to:[/bold] "
            f"{output_path}"
        )

    except OSError as exc:

        console.print(

            "\nWarning: "
            "could not save JSON file: "
            f"{exc}"
        )


    end_datetime = datetime.now().astimezone()
    total_elapsed = time.perf_counter() - overall_start

    print()
    print("=" * 70)
    print("Run Summary")
    print("=" * 70)
    print(
        f"Started      : "
        f"{start_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    print(
        f"Finished     : "
        f"{end_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    print(f"DNS testing  : {dns_elapsed:.2f} seconds")
    print(f"Total time   : {total_elapsed:.2f} seconds")
    print("=" * 70)


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