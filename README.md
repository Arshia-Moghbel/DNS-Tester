DNS Tester

A Python-based DNS benchmarking and Internet connectivity testing tool with a clean CLI interface, concurrent DNS testing, domain resolution checks, latency analysis, Internet ping, speed testing, and JSON result export.

The DNS benchmark sends queries directly to the DNS servers specified by the user and does not modify or use the operating system’s DNS configuration.

⸻

Features

* 🚀 Test multiple DNS servers concurrently
* 📡 Direct DNS queries using dnspython
* 🔒 Does not modify system DNS settings
* 🚫 Does not use system DNS for DNS benchmarks
* 🌐 Test user-defined domains
* 🔁 Run multiple tests for every DNS/domain combination
* 📊 Calculate:
    * Success rate
    * Average latency
    * Minimum latency
    * Maximum latency
    * Jitter
* ✅ Check whether user-defined domains resolve successfully
* 🏆 Automatically rank DNS servers
* 📶 Measure Internet connection latency
* ⚡ Measure download and upload speed using speedtest-cli or Ookla Speedtest CLI
* 💾 Export complete results to JSON
* 🎨 Rich terminal tables
* 🧩 Command-line arguments for customization
* 📁 Load DNS servers and domains from external text files

⸻

Requirements

* Python 3.10+
* dnspython
* rich
* speedtest-cli or Ookla Speedtest CLI

The project was developed and tested with Python 3.13.

⸻

Installation

1. Clone the repository

git clone https://github.com/Arshia-Moghbel/DNS-Tester.git
cd Dns-Tester

2. Create a virtual environment

macOS / Linux:

python3 -m venv .venv

Activate it:

source .venv/bin/activate

Windows:

python -m venv .venv
.venv\Scripts\activate

3. Install Python dependencies

python -m pip install dnspython rich

⸻

Speedtest Installation

The application supports both:

* speedtest-cli
* Ookla speedtest

speedtest-cli

python -m pip install speedtest-cli

Verify:

speedtest-cli --version

Ookla Speedtest CLI

If Ookla’s Speedtest CLI is installed and available in PATH, the application can use it automatically.

The application checks for:

speedtest

first and then:

speedtest-cli

⸻

Configuration

The default configuration uses two files located next to DNS-Tester.py:

dns.txt
domains.txt

No DNS servers or domains are hard-coded into the application.

⸻

DNS Configuration

dns.txt

The file supports provider names followed by one or more IPv4 or IPv6 addresses.

Example:

Cloudflare
1.1.1.1
1.0.0.1


Google
8.8.8.8
8.8.4.4

The application interprets this as:

Cloudflare → 1.1.1.1
Cloudflare → 1.0.0.1
Google → 8.8.8.8
Google → 8.8.4.4
Quad9 → 9.9.9.9
Quad9 → 149.112.112.112

Comments are supported:

⸻

Domain Configuration

Create:

domains.txt

Put one domain per line:

apple.com
icloud.com
google.com
github.com
youtube.com

You can use any domains you want.

For example, you could test:

epicgames.com
playstation.com
xbox.com
ubisoft.com

⸻

Usage

With dns.txt and domains.txt in the same directory:

python "DNS-Tester.py"

The program will automatically load both files.

Example startup:

DNS Tester
============================================================
DNS servers : 28
Domains     : 5
Tests/domain: 5
Timeout     : 2.00s
Concurrency : 8
System DNS  : NOT changed / NOT used

⸻

DNS Testing

For every DNS server, the application performs multiple DNS queries for every configured Domain.

For example:

5 tests × 10 domains = 50 queries per DNS server

The results include:

Metric    Description
Success    Percentage of successful queries
Avg    Average query latency
Min    Fastest successful query
Max    Slowest query
Jitter    Average change between consecutive latency samples
Domains OK    Domains with 100% successful resolution

⸻

Domain Resolution

The application provides a separate domain-resolution table.

Example:

DNS          apple.com       github.com      youtube.com
Cloudflare   ✓ 100% / 40ms   ✓ 100% / 45ms   ✓ 80% / 70ms
Google       ✓ 100% / 42ms   ✓ 100% / 48ms   ✓ 100% / 55ms

This allows you to compare not only DNS latency but also whether specific domains can actually be resolved successfully through each DNS server.

⸻

Internet Ping

The application separately tests Internet connectivity by sending ICMP requests to:

1.1.1.1

This test is not a DNS benchmark.

It reports:

* Average latency
* Minimum latency
* Maximum latency
* Ping standard deviation

⸻

Internet Speed Test

The application can also run an Internet speed test independently from the DNS benchmark.

Supported clients:

speedtest
speedtest-cli

The result can include:

* Download speed
* Upload speed
* Speedtest latency
* Test server
* Server location
* ISP

Important: the Internet speed test measures the current Internet connection and is not a measurement of DNS performance.

⸻

System DNS Isolation

One of the main design goals of this project is to test DNS servers directly.

The application uses:

dns.asyncresolver.Resolver(configure=False)

and explicitly assigns the tested server:

resolver.nameservers = [server]

Therefore, the DNS benchmark does not read the operating system’s configured DNS servers.

The application also does not change the system DNS configuration.

⸻

Concurrency

DNS servers are tested concurrently using Python’s asyncio.

Example:

python "DNS-Tester.py" --concurrency 16

Default:

Concurrency: 8

Increasing concurrency can reduce total benchmark time, but very high values may increase network load.

⸻

Command-Line Options

Display help:

python "DNS-Tester.py" --help

Number of tests

python "DNS-Tester.py" --tests 10

Default:

5

DNS timeout

python "DNS-Tester.py" --timeout 3

Default:

2 seconds

Concurrency

python "DNS-Tester.py" --concurrency 16

Default:

8

Custom DNS file

python "DNS-Tester.py" --dns-file my-dns.txt

Custom domain file

python "DNS-Tester.py" --domain-file my-domains.txt

Skip speed test

python "DNS-Tester.py" --no-speedtest

Custom JSON output

python "DNS-Tester.py" --output results.json

⸻

Direct DNS Arguments

Individual DNS servers can also be supplied through the CLI.

Example:

python "DNS-Tester.py" \
    --dns "Cloudflare=1.1.1.1" \
    --dns "Google=8.8.8.8"

Individual domains can also be supplied:

python "DNS-Tester.py" \
    --domain apple.com \
    --domain github.com

⸻

JSON Output

After every benchmark, the application saves the results to:

DNS-Results.json

The JSON file contains:

* Timestamp
* Benchmark duration
* Test configuration
* DNS server list
* Domain list
* DNS benchmark results
* Internet ping results
* Internet speed-test results

Example structure:

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

⸻

Project Structure

DNS-Tester/
│
├── DNS-Tester.py
├── dns.txt
├── domains.txt
├── Requirements.txt
├── README.md
├── LICENSE
├── .gitignore
│
└── .venv/

The .venv directory should not be committed to Git.

⸻

Requirements File

Install the required dependencies with:

python -m pip install -r Requirements.txt

⸻

Important Notes

DNS latency is not Internet latency

A DNS server with a low DNS-query latency does not necessarily provide the fastest Internet connection.

DNS testing measures the time required to resolve DNS records.

Internet speed is measured separately.

DNS caching can affect results

Repeated queries may be affected by DNS caching at different layers.

For more representative results, use multiple domains and multiple repetitions.

Network conditions matter

Results can change depending on:

* ISP
* Network congestion
* Routing
* Packet loss
* Geographic location
* DNS server load
* Domain/CDN configuration

Therefore, a DNS benchmark should be interpreted as a measurement of performance from the current network location at the time of testing.

⸻

Security & Privacy

This application:

* Does not change system DNS settings
* Does not require administrator/root privileges for DNS benchmarking
* Does not store passwords
* Does not collect personal information
* Saves benchmark results locally as JSON

The configured domains and DNS servers are used only for testing.

⸻

License

This project is available under the MIT License.

See LICENSE for details.

⸻

Author

Arshia Moghbel

Built with Python, asyncio, dnspython and Rich.
