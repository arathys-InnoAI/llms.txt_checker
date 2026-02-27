# llms.txt checker

Check a list of domains and report whether each one has an `llms.txt` file (typically at `https://<domain>/llms.txt`).

This repo contains a single script (`llms_checker.py`) plus docs.

## Requirements

- Python 3.8+ (any modern Python 3 should work)
- No extra packages required (uses Python standard library only)

Verify Python:

```powershell
python --version
# or
py --version
```

## Quick start

From the project folder:

```powershell
cd <repo_path>
python llms_checker.py domains.txt --input-format text -o
```

## Input options

The script supports **two** input formats:

### Option A: Text file (one domain per line)

Create a file like `domains.txt`:

```text
example.com
https://another-site.org
subdomain.mycompany.net
# comment lines start with '#'
```

Run:

```powershell
python llms_checker.py domains.txt --input-format text -o results.csv
```

### Option B: CSV file (domain column + any metadata)

Example `domains.csv`:

```text
domain,country,created,language
example.com,US,2020,en
another-site.org,DE,2019,de
```

Run (default domain column name is `domain`):

```powershell
python llms_checker.py domains.csv --input-format csv -o
```

If your domain column has a different name (example: `host`):

```powershell
python llms_checker.py domains.csv --input-format csv --domain-column host -o results.csv
```

## Output

### Console summary

The script prints:

- Total domains processed
- How many had `llms.txt`
- How many failed to check (no response) and the reason
- Per-domain result lines (HTTP status or error)

### CSV output

If you pass `-o`, results are written to a timestamped folder:

- `outputs/<timestamp>/results.csv`

If you pass an explicit name/path, that location is used instead.

Output file format:

```text
domain,contains_llms_txt,http_status,details
example.com,yes,200,Found (HTTP 2xx)
another-site.org,no,404,HTTP 404 Not Found (llms.txt not present at that URL)
```

The `details` column is especially useful to distinguish:

- **HTTP 404 Not Found**: the server says the file/path does not exist (most likely no `llms.txt`).
- **HTTP 403 Forbidden**: the server understood the request but refuses access (often bot blocking, IP restrictions, or authentication required).

## Useful options

- **Choose the output file name**:

```powershell
python llms_checker.py domains.csv --input-format csv -o my_results.csv
```

- **Write into a specific folder** (script will create it if missing):

```powershell
python llms_checker.py domains.csv --input-format csv -o output
```

This writes `output/results.csv`.

- **Timeout per request (seconds)**:

```powershell
python llms_checker.py domains.csv --input-format csv --timeout 10 -o results.csv
```

## Notes / troubleshooting

- **HTTPS vs HTTP**: if your input is `example.com` (no scheme), the script assumes `https://example.com`.
- **403 / auth issues while pushing this repo**: unrelated to script usage; it’s GitHub permissions/authentication.
- **Some sites block bots**: servers may return `403` or other statuses even if the file exists for browsers.
- **Network failures** (DNS errors, timeouts) are listed under “Failed domains (unable to obtain)” in the console output.

## More detailed docs

See `llms_checker_workflow.md` for the internal workflow/logic explanation.
