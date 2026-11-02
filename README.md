# DNS Tester

A Python-based DNS benchmarking and Internet connectivity testing tool with a clean command-line interface. It evaluates DNS server performance, reliability, domain resolution, latency, and network connectivity, with support for concurrent testing and JSON result export.

The DNS benchmark sends queries directly to the DNS servers specified by the user. It does not modify the operating system's DNS configuration or rely on its configured DNS resolvers for benchmark queries.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Speedtest Installation](#speedtest-installation)
- [Configuration](#configuration)
- [DNS Configuration](#dns-configuration)
- [Domain Configuration](#domain-configuration)
- [Usage](#usage)
- [DNS Benchmarking](#dns-benchmarking)
- [Domain Resolution](#domain-resolution)
- [Internet Ping](#internet-ping)
- [Internet Speed Test](#internet-speed-test)
- [System DNS Isolation](#system-dns-isolation)
- [Concurrency](#concurrency)
- [Command-Line Options](#command-line-options)
- [Direct DNS and Domain Arguments](#direct-dns-and-domain-arguments)
- [JSON Output](#json-output)
- [Project Structure](#project-structure)
- [Security and Privacy](#security-and-privacy)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Author](#author)

---

## Features

- 🚀 Test multiple DNS servers concurrently.
- 📡 Send direct DNS queries using dnspython.
- 🔒 Keep the operating system's DNS configuration unchanged.
- 🚫 Avoid using system-configured DNS resolvers for DNS benchmark queries.
- 🌐 Test user-defined domains.
- 🔁 Perform multiple queries for every DNS server and domain combination.
- 📊 Measure DNS performance:
  - Query success rate
  - Average latency
  - Minimum latency
  - Maximum latency
  - Jitter
- ✅ Evaluate domain resolution reliability.
- 🏆 Automatically rank DNS servers based on benchmark results.
- 📶 Measure Internet connectivity latency using ICMP ping.
- ⚡ Measure download and upload speeds using Speedtest CLI.
- 💾 Export benchmark results to JSON.
- 🎨 Display formatted terminal tables using Rich.
- 🧩 Support command-line arguments for customization.
- 📁 Load DNS servers and domains from external text files.
- 🌍 Support IPv4 and IPv6 DNS server addresses.

## Requirements

- Python 3.10 or newer
- dnspython
- rich
- speedtest-cli or Ookla Speedtest CLI (optional)

The project was developed and tested with Python 3.13.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Arshia-Moghbel/DNS-Tester.git
cd DNS-Tester
```

### 2. Create a virtual environment

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Run the application

```bash
python DNS-Tester.py
```

## Speedtest Installation

DNS Tester supports two Speedtest command-line clients:

- `speedtest` — Ookla Speedtest CLI
- `speedtest-cli` — Python-based Speedtest CLI

The application checks for Ookla's `speedtest` command first, followed by `speedtest-cli`.

Verify installation:

```bash
speedtest --version
```

Or:

```bash
speedtest-cli --version
```

Speedtest is optional. DNS benchmarking and Internet ping testing can be used independently of the speed test.

## Configuration

The default configuration uses two external text files located next to `DNS-Tester.py`:

```text
dns.txt
domains.txt
```

No DNS servers or domains need to be hard-coded into the application.

### DNS Configuration

Create a file named `dns.txt`.

The file supports provider names followed by one or more IPv4 or IPv6 addresses.

Example:

```text
Cloudflare
1.1.1.1
1.0.0.1

Google
8.8.8.8
8.8.4.4

Quad9
9.9.9.9
149.112.112.112
```

The application interprets the entries as:

| Provider | DNS Server |
|---|---|
| Cloudflare | 1.1.1.1 |
| Cloudflare | 1.0.0.1 |
| Google | 8.8.8.8 |
| Google | 8.8.4.4 |
| Quad9 | 9.9.9.9 |
| Quad9 | 149.112.112.112 |

Comments can be included in the configuration file if supported by the parser.

### Domain Configuration

Create a file named `domains.txt`.

Add one domain per line:

```text
apple.com
icloud.com
google.com
github.com
youtube.com
```

You can use any valid domains you want.

For example:

```text
epicgames.com
playstation.com
xbox.com
ubisoft.com
```

The application uses these domains to evaluate DNS resolution performance and reliability.

## Usage

With `dns.txt` and `domains.txt` in the same directory as the application:

```bash
python DNS-Tester.py
```

Example startup information:

```text
DNS Tester
============================================================
DNS servers : 28
Domains     : 5
Tests/domain: 5
Timeout     : 2.00s
Concurrency : 8
System DNS  : NOT changed / NOT used
```

The displayed values depend on the configuration files and command-line arguments.

## DNS Benchmarking

For each DNS server, the application performs multiple DNS queries for every configured domain.

For example:

```text
5 tests × 10 domains = 50 queries per DNS server
```

The benchmark evaluates:

| Metric | Description |
|---|---|
| Success | Percentage of successful DNS queries |
| Avg | Average latency of successful queries |
| Min | Minimum successful query latency |
| Max | Maximum successful query latency |
| Jitter | Average absolute difference between consecutive successful latency measurements |
| Domains OK | Number of domains successfully resolved in all test attempts |

Only successful query measurements should contribute to latency statistics.

## Domain Resolution

DNS Tester provides domain-level resolution results to help compare DNS servers.

Example:

| DNS Server | apple.com | github.com | youtube.com |
|---|---|---|---|
| Cloudflare | ✓ 100% / 40ms | ✓ 100% / 45ms | ✓ 80% / 70ms |
| Google | ✓ 100% / 42ms | ✓ 100% / 48ms | ✓ 100% / 55ms |

These are illustrative values, not actual benchmark results.

Domain resolution statistics help identify DNS servers that may have inconsistent resolution performance for particular domains.

## Internet Ping

The application separately tests Internet connectivity by sending ICMP requests to:

```text
1.1.1.1
```

This test is independent of DNS benchmarking.

Reported metrics can include:

- Average latency
- Minimum latency
- Maximum latency
- Ping standard deviation

Internet ping measures network round-trip time to the target IP address. It does not measure DNS resolution speed.

## Internet Speed Test

DNS Tester can independently measure Internet connection performance.

Supported clients:

```text
speedtest
speedtest-cli
```

Results can include:

- Download speed
- Upload speed
- Speedtest latency
- Test server
- Server location
- ISP

**Important:** Internet speed testing measures the current network connection. It does not measure DNS server performance.

## System DNS Isolation

One of the main design goals of DNS Tester is to benchmark DNS servers directly.

The DNS benchmarking engine uses:

```python
dns.asyncresolver.Resolver(configure=False)
```

and explicitly assigns the DNS server being tested:

```python
resolver.nameservers = [server]
```

This allows DNS queries to be directed to the specified DNS server without relying on the operating system's configured DNS resolvers for benchmark queries.

The application does not modify the system DNS configuration.

This isolation applies specifically to DNS benchmarking. Other components, such as Internet speed testing, may use the system's normal network configuration.

## Concurrency

DNS servers are tested concurrently using Python's `asyncio`.

Example:

```bash
python DNS-Tester.py --concurrency 16
```

Default:

```text
Concurrency: 8
```

Increasing concurrency can reduce total benchmark execution time, but excessively high values may increase network load and affect measurement consistency.

## Command-Line Options

Display help:

```bash
python DNS-Tester.py --help
```

### Number of Tests

```bash
python DNS-Tester.py --tests 10
```

Default:

```text
5
```

### DNS Timeout

```bash
python DNS-Tester.py --timeout 3
```

Default:

```text
2 seconds
```

### Concurrency

```bash
python DNS-Tester.py --concurrency 16
```

Default:

```text
8
```

### Custom DNS File

```bash
python DNS-Tester.py --dns-file my-dns.txt
```

### Custom Domain File

```bash
python DNS-Tester.py --domain-file my-domains.txt
```

### Skip Speed Test

```bash
python DNS-Tester.py --no-speedtest
```

### Custom JSON Output

```bash
python DNS-Tester.py --output results.json
```

## Direct DNS and Domain Arguments

Individual DNS servers can also be supplied through command-line arguments.

Example:

```bash
python DNS-Tester.py \
    --dns "Cloudflare=1.1.1.1" \
    --dns "Google=8.8.8.8"
```

Individual domains can also be supplied:

```bash
python DNS-Tester.py \
    --domain apple.com \
    --domain github.com
```

These options allow custom benchmarks without editing the default configuration files.

## JSON Output

After a benchmark, results are exported to:

```text
DNS-Results.json
```

A custom output path can be specified using:

```bash
python DNS-Tester.py --output results.json
```

The JSON report is intended to contain:

- Timestamp
- Benchmark duration
- Test configuration
- DNS server list
- Domain list
- DNS benchmark results
- Internet ping results
- Internet speed-test results
- System DNS usage and configuration status

Example JSON structure:

```json
{
  "timestamp_utc": "...",
  "duration_seconds": 12.34,
  "tests_per_domain": 5,
  "timeout_seconds": 2.0,
  "concurrency": 8,
  "system_dns_changed": false,
  "system_dns_used_for_dns_tests": false,
  "dns_servers": [],
  "domains": [],
  "dns_results": [],
  "internet_ping": {},
  "internet_speedtest": {}
}
```

The example is illustrative. Actual fields and values depend on the application version and enabled tests.

## Project Structure

```text
DNS-Tester/
│
├── DNS-Tester.py
├── dns.txt
├── domains.txt
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
│
└── .venv/                 # Local virtual environment (not committed)
```

The `.venv` directory should not be committed to Git.

## Security and Privacy

DNS Tester is designed to perform local network diagnostics without modifying the operating system's DNS configuration.

The application:

- Does not change system DNS settings.
- Does not require administrator or root privileges for ordinary DNS benchmarking.
- Does not require user passwords.
- Does not intentionally collect personal information.
- Saves benchmark results locally as JSON.
- Sends DNS queries to the DNS servers specified by the user.
- Sends network test traffic to the configured test destinations and selected Speedtest servers.

**Privacy note:** DNS queries reveal the domains being tested to the selected DNS resolvers. Speedtest providers may also process network information as part of their service.

## Troubleshooting

### Missing Python Dependencies

Install the required dependencies:

```bash
python -m pip install -r requirements.txt
```

### DNS Timeout

Possible causes include:

- DNS server unavailable.
- Network restrictions.
- Firewall rules.
- Incorrect DNS server address.
- High network latency.

Try increasing the timeout:

```bash
python DNS-Tester.py --timeout 5
```

### Speedtest Command Not Found

Verify that one of the supported Speedtest clients is installed and available in your system's `PATH`.

### Invalid DNS or Domain Entries

Check the contents of `dns.txt` and `domains.txt`. Make sure the entries are valid and correctly formatted.

### High Latency or Inconsistent Results

Network congestion, routing, DNS caching, packet loss, and server load can affect benchmark results.

Consider running multiple tests under consistent network conditions.

## Contributing

Contributions, bug reports, and suggestions are welcome.

To contribute:

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Test your implementation.
5. Submit a Pull Request.

For significant changes, open an issue first to discuss the proposed implementation.

## License

This project is licensed under the MIT License.

See the [LICENSE](LICENSE) file for details.

## Author

**Arshia Moghbel**

GitHub: [@Arshia-Moghbel](https://github.com/Arshia-Moghbel)

Built with Python, asyncio, dnspython, and Rich.
