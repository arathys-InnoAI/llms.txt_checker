import argparse
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
from datetime import datetime
import time
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import csv
import sys


@dataclass
class UrlAttempt:
    url: str
    http_status: Optional[int]
    error: Optional[str]
    content_type: Optional[str] = None
    looks_like_html: bool = False


@dataclass
class DomainCheckResult:
    domain: str
    url_checked: str
    has_llms_txt: bool
    http_status: Optional[int]
    error: Optional[str]
    attempts: List[UrlAttempt] = field(default_factory=list)


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
    # llms.txt is typically served from the site root.
    return urlunparse(parsed._replace(path="/llms.txt", query="", fragment=""))


def build_candidate_llms_urls(domain: str, try_www_variants: bool = True) -> List[str]:
    """
    Build one or more candidate llms.txt URLs to try.

    By default, tries both:
    - https://example.com/llms.txt
    - https://www.example.com/llms.txt

    If the input already contains www, it will also try the non-www variant.
    """
    base_url = normalize_domain(domain)
    if not base_url:
        return []

    parsed = urlparse(base_url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc
    if not host:
        return []

    hosts: List[str] = [host]
    if try_www_variants:
        if host.lower().startswith("www."):
            hosts.append(host[4:])
        else:
            hosts.append(f"www.{host}")

    # Deduplicate while preserving order
    seen = set()
    out: List[str] = []
    for h in hosts:
        if not h or h.lower() in seen:
            continue
        seen.add(h.lower())
        out.append(urlunparse((scheme, h, "/llms.txt", "", "", "")))
    return out


def fetch_with_retries(
    url: str,
    timeout: float,
    retries: int,
    retry_wait_s: float,
    backoff_factor: float,
) -> List[UrlAttempt]:
    """
    Fetch a URL with retry/backoff behavior.

    Retries apply to:
    - transient HTTP statuses: 429 and 5xx
    - timeouts / connection errors
    """
    max_attempts = max(1, 1 + retries)
    attempts: List[UrlAttempt] = []

    transient_statuses = {429, 500, 502, 503, 504}

    for attempt_idx in range(1, max_attempts + 1):
        req = Request(url, method="GET", headers={"User-Agent": "llms-checker/1.0"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()

                # Read a small sample of the body to distinguish real text files
                # from generic HTML "page not found" responses.
                body_sample = resp.read(4096) or b""
                content_type = resp.headers.get("Content-Type", None)
                lower_sample = body_sample.lower()
                looks_like_html = b"<html" in lower_sample or b"<!doctype html" in lower_sample

                attempts.append(
                    UrlAttempt(
                        url=url,
                        http_status=status,
                        error=None,
                        content_type=content_type,
                        looks_like_html=looks_like_html,
                    )
                )
                if status in transient_statuses and attempt_idx < max_attempts:
                    wait = retry_wait_s * (backoff_factor ** (attempt_idx - 1))
                    time.sleep(wait)
                    continue
                return attempts
        except HTTPError as e:
            status = e.code
            attempts.append(
                UrlAttempt(url=url, http_status=status, error=str(e), content_type=None, looks_like_html=False)
            )
            if status in transient_statuses and attempt_idx < max_attempts:
                wait = retry_wait_s * (backoff_factor ** (attempt_idx - 1))
                time.sleep(wait)
                continue
            return attempts
        except URLError as e:
            attempts.append(
                UrlAttempt(
                    url=url,
                    http_status=None,
                    error=str(e.reason),
                    content_type=None,
                    looks_like_html=False,
                )
            )
            if attempt_idx < max_attempts:
                wait = retry_wait_s * (backoff_factor ** (attempt_idx - 1))
                time.sleep(wait)
                continue
            return attempts
        except Exception as e:  # Catch-all to avoid script crash on weird cases
            attempts.append(
                UrlAttempt(
                    url=url,
                    http_status=None,
                    error=str(e),
                    content_type=None,
                    looks_like_html=False,
                )
            )
            if attempt_idx < max_attempts:
                wait = retry_wait_s * (backoff_factor ** (attempt_idx - 1))
                time.sleep(wait)
                continue
            return attempts

    return attempts


def check_single_domain(
    domain: str,
    timeout: float = 5.0,
    try_www_variants: bool = True,
    retries: int = 0,
    retry_wait_s: float = 1.0,
    backoff_factor: float = 2.0,
) -> DomainCheckResult:
    """
    Check if a single domain exposes /llms.txt.
    Tries HTTPS first (if no scheme given).
    """
    if not domain.strip():
        return DomainCheckResult(
            domain=domain,
            url_checked="",
            has_llms_txt=False,
            http_status=None,
            error="empty_domain",
        )

    candidate_urls = build_candidate_llms_urls(domain, try_www_variants=try_www_variants)
    if not candidate_urls:
        return DomainCheckResult(
            domain=domain,
            url_checked="",
            has_llms_txt=False,
            http_status=None,
            error="invalid_domain_or_url",
        )

    all_attempts: List[UrlAttempt] = []

    for url in candidate_urls:
        attempts = fetch_with_retries(
            url=url,
            timeout=timeout,
            retries=retries,
            retry_wait_s=retry_wait_s,
            backoff_factor=backoff_factor,
        )
        all_attempts.extend(attempts)

        # Stop early if any attempt clearly succeeded with a real llms.txt
        for a in attempts:
            if a.http_status is not None and 200 <= a.http_status < 300:
                # Heuristic: treat as llms.txt only if it doesn't look like HTML
                # and the content type is text-like or unspecified.
                ct = (a.content_type or "").lower()
                if a.looks_like_html:
                    continue
                if ct and not ct.startswith("text/") and "llms" not in ct:
                    continue
                return DomainCheckResult(
                    domain=domain,
                    url_checked=a.url,
                    has_llms_txt=True,
                    http_status=a.http_status,
                    error=None,
                    attempts=all_attempts,
                )

    statuses = [a.http_status for a in all_attempts if a.http_status is not None]
    errors = [a.error for a in all_attempts if a.error]

    # Prefer "blocked" classification if we saw any 403; else fall back to 404; else last status.
    final_status: Optional[int] = None
    if 403 in statuses:
        final_status = 403
    elif 404 in statuses:
        final_status = 404
    elif statuses:
        final_status = statuses[-1]

    final_error: Optional[str] = None
    if final_status is None and errors:
        final_error = errors[-1]

    return DomainCheckResult(
        domain=domain,
        url_checked=all_attempts[-1].url if all_attempts else "",
        has_llms_txt=False,
        http_status=final_status,
        error=final_error,
        attempts=all_attempts,
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
        fieldnames = reader.fieldnames or []
        # Make domain column matching more forgiving (case-insensitive).
        fieldname_map = {name.lower(): name for name in fieldnames}
        resolved_domain_column = fieldname_map.get(domain_column.lower())
        if not resolved_domain_column:
            raise ValueError(
                f"CSV file does not contain a '{domain_column}' column. "
                f"Available columns: {', '.join(fieldnames)}"
            )
        for row in reader:
            raw = (row.get(resolved_domain_column) or "").strip()
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
    def explain_status(r: DomainCheckResult) -> str:
        """
        Human-friendly explanation of common outcomes.

        Key difference:
        - 404 Not Found: the server says the file/path doesn't exist.
        - 403 Forbidden: the server understood the request but refuses access
          (often bot blocking, IP restrictions, or authentication required).
        """
        parts: List[str] = []

        if r.attempts:
            per_url: List[str] = []
            for a in r.attempts:
                if a.http_status is not None:
                    suffix = ""
                    if a.looks_like_html:
                        suffix = " (body looks like HTML)"
                    per_url.append(f"{a.url} -> HTTP {a.http_status}{suffix}")
                elif a.error:
                    per_url.append(f"{a.url} -> error: {a.error}")
            if per_url:
                parts.append(" | ".join(per_url))

        if r.has_llms_txt:
            parts.append("Found (HTTP 2xx)")
            return " ; ".join(parts) if parts else "Found (HTTP 2xx)"

        if r.http_status == 404:
            parts.append("HTTP 404 Not Found (llms.txt not present at that URL)")
        elif r.http_status == 403:
            parts.append(
                "HTTP 403 Forbidden (server refused access; may block bots/auth required)"
            )
        elif r.http_status == 429:
            parts.append(
                "HTTP 429 Too Many Requests (rate limited; try --delay and/or retries)"
            )
        elif r.http_status is not None:
            parts.append(f"HTTP {r.http_status}")
        elif r.error:
            parts.append(f"error: {r.error}")

        return " ; ".join(parts)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["domain", "contains_llms_txt", "http_status", "details"])
        for r in results:
            writer.writerow(
                [
                    r.domain,
                    "yes" if r.has_llms_txt else "no",
                    r.http_status if r.http_status is not None else "",
                    explain_status(r),
                ]
            )


def build_timestamped_output_path(filename: str = "results.csv") -> str:
    """
    Create an output path like: outputs/YYYYmmdd-HHMMSS/results.csv
    Returns the full path as a string. Directory is created if needed.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path("outputs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    return str(out_dir / filename)


def resolve_output_csv_path(output_csv_arg: str) -> str:
    """
    Interpret --output-csv argument.

    Supported behaviors:
    - If the value ends with .csv -> treat it as a file path.
    - Otherwise -> treat it as a directory and write results.csv inside it.
    """
    p = Path(output_csv_arg)
    if p.suffix.lower() == ".csv":
        # Ensure parent directory exists (if any)
        if p.parent and str(p.parent) not in (".", ""):
            p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)

    # Treat as directory
    p.mkdir(parents=True, exist_ok=True)
    return str(p / "results.csv")


def print_summary(results: List[DomainCheckResult]) -> None:
    """
    Print a human-readable summary to the console.
    """
    total_in_results = len(results)
    with_llms = sum(1 for r in results if r.has_llms_txt)
    # Domain-level (final classification)
    count_domain_404 = sum(1 for r in results if r.http_status == 404)
    count_domain_403 = sum(1 for r in results if r.http_status == 403)
    count_domain_429 = sum(1 for r in results if r.http_status == 429)

    # Request-level (all HTTP responses across retries + www/non-www)
    count_http_404 = sum(
        1 for r in results for a in r.attempts if a.http_status == 404
    )
    count_http_403 = sum(
        1 for r in results for a in r.attempts if a.http_status == 403
    )
    count_http_429 = sum(1 for r in results for a in r.attempts if a.http_status == 429)
    failed = [r for r in results if r.error is not None and r.http_status is None]

    print(f"Total domains processed: {total_in_results}")
    print(f"Domains with llms.txt: {with_llms}")
    print(f"Domain result = HTTP 404 Not Found: {count_domain_404}")
    print(f"Domain result = HTTP 403 Forbidden: {count_domain_403}")
    print(f"Domain result = HTTP 429 Too Many Requests: {count_domain_429}")
    #print(f"HTTP 404 responses (all requests): {count_http_404}")
    #print(f"HTTP 403 responses (all requests): {count_http_403}")
    #print(f"HTTP 429 responses (all requests): {count_http_429}")
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
        help=(
            "Write results to CSV. Usage:\n"
            "  - omit to not write a CSV\n"
            "  - '-o' (no value) to write to outputs/<timestamp>/results.csv\n"
            "  - '-o results.csv' to write to a specific file\n"
            "  - '-o outputs' to write to outputs/results.csv"
        ),
        nargs="?",
        const="__TIMESTAMPED__",
        default=None,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds for each HTTP request (default: 5.0).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help="Number of retries per URL for transient failures (default: 0).",
    )
    parser.add_argument(
        "--retry-wait",
        type=float,
        default=1.0,
        help="Base wait time (seconds) before retrying (default: 1.0).",
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=2.0,
        help="Exponential backoff factor for retries (default: 2.0).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay (seconds) between domains to reduce rate-limits (default: 0).",
    )
    parser.add_argument(
        "--no-www-fallback",
        action="store_true",
        help="Do not try www/non-www variants (default: try both).",
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
    for idx, d in enumerate(domains):
        result = check_single_domain(
            d,
            timeout=args.timeout,
            try_www_variants=not args.no_www_fallback,
            retries=max(0, args.retries),
            retry_wait_s=max(0.0, args.retry_wait),
            backoff_factor=max(1.0, args.backoff),
        )
        results.append(result)

        if args.delay > 0 and idx < (len(domains) - 1):
            time.sleep(args.delay)

    print_summary(results)

    if args.output_csv:
        try:
            if args.output_csv == "__TIMESTAMPED__":
                output_path = build_timestamped_output_path("results.csv")
            else:
                output_path = resolve_output_csv_path(args.output_csv)

            write_csv(results, output_path)
            print()
            print(f"Results written to CSV: {output_path}")
        except Exception as e:
            print(f"Failed to write CSV file: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

