import argparse
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import csv
import sys


@dataclass
class DomainCheckResult:
    domain: str
    url_checked: str
    has_llms_txt: bool
    http_status: Optional[int]
    error: Optional[str]


def normalize_domain(domain: str) -> str:
    """
    Normalize a domain or URL string to a base URL with scheme.
    - If it already has http/https, keep it.
    - Otherwise, assume https.
    """
    domain = domain.strip()
    if not domain:
        return ""

    if domain.startswith(("http://", "https://")):
        return domain.rstrip("/")

    # Prepend https scheme by default
    return f"https://{domain.rstrip('/')}"


def build_llms_url(base_url: str) -> str:
    """
    Given a base URL, construct the llms.txt URL.
    """
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    path = f"{path}/llms.txt" if path else "/llms.txt"
    return urlunparse(parsed._replace(path=path))


def check_single_domain(domain: str, timeout: float = 5.0) -> DomainCheckResult:
    """
    Check if a single domain exposes /llms.txt.
    Tries HTTPS first (if no scheme given).
    """
    base_url = normalize_domain(domain)
    if not base_url:
        return DomainCheckResult(
            domain=domain,
            url_checked="",
            has_llms_txt=False,
            http_status=None,
            error="empty_domain",
        )

    llms_url = build_llms_url(base_url)

    req = Request(llms_url, method="GET", headers={"User-Agent": "llms-checker/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            # Treat any 2xx as "exists"
            has_llms = 200 <= status < 300
            return DomainCheckResult(
                domain=domain,
                url_checked=llms_url,
                has_llms_txt=has_llms,
                http_status=status,
                error=None,
            )
    except HTTPError as e:
        # HTTPError is also a response; we can inspect the status code.
        status = e.code
        has_llms = 200 <= status < 300
        return DomainCheckResult(
            domain=domain,
            url_checked=llms_url,
            has_llms_txt=has_llms,
            http_status=status,
            error=str(e) if not has_llms else None,
        )
    except URLError as e:
        return DomainCheckResult(
            domain=domain,
            url_checked=llms_url,
            has_llms_txt=False,
            http_status=None,
            error=str(e.reason),
        )
    except Exception as e:  # Catch-all to avoid script crash on weird cases
        return DomainCheckResult(
            domain=domain,
            url_checked=llms_url,
            has_llms_txt=False,
            http_status=None,
            error=str(e),
        )


def load_domains(path: str) -> List[str]:
    """
    Load domains from a text file.
    - Ignores empty lines and lines starting with '#'.
    """
    domains: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            domains.append(raw)
    return domains


def load_domains_from_csv(path: str, domain_column: str = "domain") -> List[str]:
    """
    Load domains from a CSV file.
    - Expects a header row containing the given domain_column name.
    - Ignores rows where the domain cell is empty.
    """
    domains: List[str] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if domain_column not in (reader.fieldnames or []):
            raise ValueError(
                f"CSV file does not contain a '{domain_column}' column. "
                f"Available columns: {', '.join(reader.fieldnames or [])}"
            )
        for row in reader:
            raw = (row.get(domain_column) or "").strip()
            if not raw:
                continue
            domains.append(raw)
    return domains


def write_csv(results: List[DomainCheckResult], output_path: str) -> None:
    """
    Write results to a CSV file.

    For your current workflow we keep it very simple:
    - domain
    - contains_llms_txt (yes/no)
    """
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["domain", "contains_llms_txt"])
        for r in results:
            writer.writerow(
                [
                    r.domain,
                    "yes" if r.has_llms_txt else "no",
                ]
            )


def print_summary(results: List[DomainCheckResult]) -> None:
    """
    Print a human-readable summary to the console.
    """
    total_in_results = len(results)
    with_llms = sum(1 for r in results if r.has_llms_txt)
    failed = [r for r in results if r.error is not None and r.http_status is None]

    print(f"Total domains processed: {total_in_results}")
    print(f"Domains with llms.txt: {with_llms}")
    print(f"Domains that failed to check (no response): {len(failed)}")
    print()
    print("Per-domain results:")
    print("-" * 60)
    for r in results:
        status_str = "YES" if r.has_llms_txt else "NO"
        extra = ""
        if r.http_status is not None:
            extra = f" (HTTP {r.http_status})"
        elif r.error:
            extra = f" (error: {r.error})"
        print(f"{r.domain:<30} -> llms.txt: {status_str}{extra}")

    if failed:
        print()
        print("Failed domains (unable to obtain):")
        for r in failed:
            print(f"- {r.domain}: {r.error}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check which domains expose an llms.txt file."
    )
    parser.add_argument(
        "input_file",
        help="Input file path (text or CSV).",
    )
    parser.add_argument(
        "-o",
        "--output-csv",
        help="Optional path to write results as CSV.",
        default=None,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds for each HTTP request (default: 5.0).",
    )
    parser.add_argument(
        "--input-format",
        choices=["text", "csv"],
        default="text",
        help=(
            "Format of the input file: 'text' for one domain per line, "
            "'csv' for a CSV file (default: text)."
        ),
    )
    parser.add_argument(
        "--domain-column",
        default="domain",
        help=(
            "When using --input-format csv, name of the column that contains domains "
            "(default: domain)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    try:
        if args.input_format == "csv":
            domains = load_domains_from_csv(args.input_file, args.domain_column)
        else:
            domains = load_domains(args.input_file)
    except FileNotFoundError:
        print(f"Input file not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading input file: {e}", file=sys.stderr)
        sys.exit(1)

    if not domains:
        print("No domains found in the input file.", file=sys.stderr)
        sys.exit(1)

    results: List[DomainCheckResult] = []
    for d in domains:
        result = check_single_domain(d, timeout=args.timeout)
        results.append(result)

    print_summary(results)

    if args.output_csv:
        try:
            write_csv(results, args.output_csv)
            print()
            print(f"Results written to CSV: {args.output_csv}")
        except Exception as e:
            print(f"Failed to write CSV file: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

