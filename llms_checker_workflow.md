## Overview

This mini-tool helps you check a list of domains and see which ones expose an `llms.txt` file, typically at the root of the site (for example, `https://example.com/llms.txt`).

The script:

- **Normalizes each domain** into a proper URL
- **Builds the full `llms.txt` URL**
- **Performs an HTTP GET request** with a timeout
- **Reports which domains have `llms.txt` and which do not**
- **Optionally writes a CSV file** with simple results (`domain`, `contains_llms_txt`)

---

## Files

- **`llms_checker.py`**: The main Python script that does all the work.
- **`domains.txt`** or **`domains.csv`** (optional/example): A simple text file/csv file where you list your domains.
- **`llms_checker_workflow.md`**: This explanation file you are reading.

---

## Input formats

The script supports **two** input formats:

- A **plain text file** like `domains.txt`
- A **CSV file** with a `domain` column (plus any other metadata you like)

You select the format at runtime using the `--input-format` option.

---

### 1. Text input (`domains.txt`)

Create a file called `domains.txt` (or any name you like) with **one domain per line**. Examples:

```text
example.com
https://another-site.org
subdomain.mycompany.net
# you can comment lines like this
```

Rules:

- **One domain (or full URL) per line**
- **Blank lines are ignored**
- **Lines starting with `#` are treated as comments and ignored**

The script is flexible:

- If the line **already includes** `http://` or `https://`, it uses that as-is.
- If the line is just a domain like `example.com`, the script automatically assumes `https://example.com`.

---

### 2. CSV input

You can also provide a CSV such as:

```text
domain,country,created,language
example.com,US,2020,en
another-site.org,DE,2019,de
```

Rules:

- The CSV must have a header row.
- One of the columns must contain the domains (by default it is called `domain`).
- You can rename that column and tell the script via `--domain-column`(case-insensitive match).

Example variations:

- If your column is called `domain`, you can just use the default.
- If your column is called `host`, run with `--domain-column host`.

---

## How the script works (`llms_checker.py`)

### 1. Loading domains

The script has two loaders:

- `load_domains(path: str) -> List[str>` for **text files**
  - Opens the specified text file.
  - Reads each line.
  - Skips:
    - Empty lines
    - Lines starting with `#`
  - Returns a clean list of domain strings.

- `load_domains_from_csv(path: str, domain_column: str = "domain") -> List[str>` for **CSV files**
  - Uses `csv.DictReader` to read the CSV.
  - Checks that the header contains `domain_column` (case-insensitive match).
  - Reads that column for each row, trims whitespace, ignores empty values.
  - Returns a list of domain strings.

### 2. Normalizing domains

Function: `normalize_domain(domain: str) -> str`

- Trims whitespace.
- If the domain already starts with `http://` or `https://`, it is kept (except for a trailing `/` which is removed).
- Otherwise, it prepends `https://` to the domain.

Result: a clean base URL like `https://example.com`.

### 3. Building the `llms.txt` URL

Function: `build_llms_url(base_url: str) -> str`

- Parses the base URL into components.
- Ensures the path ends with `/llms.txt`.
- Examples:
  - `https://example.com` -> `https://example.com/llms.txt`
  - `https://example.com/` -> `https://example.com/llms.txt`
  - `https://example.com/some/path` -> `https://example.com/some/path/llms.txt`

### 4. Checking each domain

Function: `check_single_domain(domain: str, timeout: float = 5.0) -> DomainCheckResult`

For each input domain:

1. Normalize it to a base URL.
2. Build the corresponding `llms.txt` URL.
3. Make an HTTP GET request to that URL with a configurable timeout (default 5 seconds).
4. Capture:
   - The **final URL** that was checked
   - The **HTTP status code** (if any)
   - Whether `llms.txt` **exists** (2xx status)
   - Any **error message** (connection issues, DNS failure, etc.)

It returns a `DomainCheckResult` data object that holds:

- `domain`
- `url_checked`
- `has_llms_txt` (True/False)
- `http_status` (or `None`)
- `error` (or `None`)

### 5. Printing a summary

Function: `print_summary(results: List[DomainCheckResult])`

For all processed domains, it:

- Counts the **total number of domains processed**.
- Counts how many had `llms.txt`.
- Counts HTTP 404/403.
- Finds domains that **failed to check** (e.g. DNS error, timeout).

Example style of output:

```text
Total domains processed: 40
Domains with llms.txt: 34
HTTP 404 Not Found: 5
HTTP 403 Forbidden: 0
Domains that failed to check (no response): 1

Per-domain results:
------------------------------------------------------------
example.com            -> llms.txt: NO (HTTP 404)
www.anothersite.com    -> llms.txt: YES (HTTP 200)
example2.com          -> llms.txt: NO (HTTP 404)

Failed domains (unable to obtain):
- broken-domain.xyz: [Errno 11001] getaddrinfo failed
...
```

This gives you:

- How many domains are in the input.
- How many were successfully checked and have `llms.txt`.
- Distinguishing 403 Forbidden vs 404 Not Found
- Which domains were **unable to obtain**, and **why**.

### 6. Writing a CSV (optional)

Function: `write_csv(results: List[DomainCheckResult], output_path: str)`

For the current workflow, the CSV is intentionally simple:

- Columns:
  - `domain`
  - `contains_llms_txt` (`yes` / `no`)
  - `http_status`
  - `details` (human-friendly explanation)

Example output CSV:

```text
domain,contains_llms_txt,http_status,details
example.com,yes,200,Found (HTTP 2xx)
another-site.org,no,404,HTTP 404 Not Found (llms.txt not present at that URL)
```

The `details` column is designed to make the common “no” cases clearer:

- **HTTP 404 Not Found**: the server says the `llms.txt` path does not exist.
- **HTTP 403 Forbidden**: the server understood the request but refuses access (often bot blocking, IP restrictions, or authentication required).

### 7. Output file location (timestamped or explicit)

The output location is controlled by `-o` / `--output-csv`:

- If you **omit** `-o`, no CSV is written (console output only).
- If you use **`-o` with no value**, the script writes to a timestamped folder:
  - `outputs/<YYYYmmdd-HHMMSS>/results.csv`
- If you pass a value:
  - If it ends with `.csv`, it is treated as an explicit file path (example: `-o my_results.csv`).
  - Otherwise it is treated as a directory (example: `-o output` writes `output/results.csv`).

---

## How to run the script

### 1. Make sure Python is installed

You need **Python 3** installed on your system. On Windows, you can test with:

```powershell
python --version
```

or

```powershell
py --version
```

Use whichever command works on your machine (`python` or `py`).

### 2. Choose your input file

#### Option A: Text file (`domains.txt`)

In the same folder as `llms_checker.py`, create a file `domains.txt` with your domains.

Example:

```text
example.com
mydomain.io
https://already-with-scheme.net
```

Run from your repo path:

```powershell
cd <repo_path>
python llms_checker.py domains.txt --input-format text
```

If your Python command is `py` instead of `python`, use:

```powershell
py llms_checker.py domains.txt --input-format text
```

#### Option B: CSV file

Assume you have a CSV `domains.csv` like:

```text
domain,country,created,language
example.com,US,2020,en
another-site.org,DE,2019,de
```

Run:

```powershell
cd <repo_path>
python llms_checker.py domains.csv --input-format csv
```

If your column is named differently (e.g. `host`):

```powershell
python llms_checker.py domains.csv --input-format csv --domain-column host
```

### 3. Optional: Save results to CSV

Add the `-o` / `--output-csv` option (works with both text and CSV input):

- Timestamped output folder:

```powershell
python llms_checker.py domains.csv --input-format csv --domain-column domain -o
```

- Explicit output file name:

```powershell
python llms_checker.py domains.csv --input-format csv --domain-column domain -o results.csv
```

- Output directory (writes `output/results.csv`):

```powershell
python llms_checker.py domains.csv --input-format csv --domain-column domain -o output
```

These will:

- Print the summary to the console, and
- Write a simple results file: `domain,contains_llms_txt`.

---

## Customization ideas

- **Change timeout**: Increase or decrease the HTTP timeout:

  ```powershell
  python llms_checker.py domains.csv --input-format csv --timeout 10
  ```

- **Check a subset**: Create multiple domain files (e.g. `domains_batch1.txt`, `domains_batch2.txt`) and run the script on each.
- **Integrate with other tools**: Use the generated CSV as input to dashboards or further analysis.

---

## Quick mental model

In short:

- **Input**: Either a simple text file of domains or a CSV with a domain column.
- **Process**: For each domain, build `<domain>/llms.txt`, send an HTTP GET, and record whether it exists. Also capture failures and reasons.
- **Output**: A console summary plus (optionally) a CSV with `domain,contains_llms_txt`.
