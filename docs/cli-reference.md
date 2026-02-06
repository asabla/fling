# CLI Reference

fling provides a command-line interface for running, managing, and converting HTTP requests defined in `.http` files.

```
fling [OPTIONS] COMMAND [ARGS]...
```

**Global options:**

| Option | Description |
|---|---|
| `--version` | Show the version and exit |
| `--help` | Show help and exit |

---

## `fling run`

Run HTTP requests from a `.http` file.

```
fling run [OPTIONS] FILE
```

**Arguments:**

| Argument | Description |
|---|---|
| `FILE` | Path to the `.http` file to execute (required) |

**Options:**

| Option | Description |
|---|---|
| `-n, --name TEXT` | Run a specific named request (by its `@name` tag) |
| `--all` | Run all requests in order |
| `-e, --env TEXT` | Environment name to use (from `http-client.env.json`) |
| `--env-file PATH` | Path to directory containing environment files |
| `-v, --verbose` | Show extra detail (full request/response exchange) |
| `-o, --output FORMAT` | Output format (see table below) |
| `--timeout INTEGER` | Request timeout in milliseconds |
| `-k, --insecure` | Skip SSL certificate verification |
| `--bail` | Stop execution on the first failure |
| `--filter TEXT` | Glob pattern to filter requests by name |
| `--repeat INTEGER` | Number of times to repeat execution |
| `--repeat-mode MODE` | How to run repeated executions: `sequential` (default) or `parallel` |

**Output formats:**

| Format | Description |
|---|---|
| `exchange` | Full HTTP exchange showing request and response |
| `headers` | Response headers only |
| `body` | Response body only |
| `json` | Structured JSON output with all execution details |
| `json-report` | Full test report in JSON format |
| `junit` | JUnit XML format for CI/CD integration |
| `markdown` | Markdown-formatted report |

**Examples:**

```bash
# Run all requests with an environment
fling run api.http --all --env production

# Run a named request with verbose output
fling run api.http --name login --env dev --verbose

# Run requests matching a pattern
fling run api.http --all --filter "user*"

# Output as JUnit XML for CI
fling run api.http --all -o junit > results.xml

# Stop on first failure with JSON report
fling run api.http --all --bail -o json-report

# Repeat a request 10 times in parallel
fling run api.http --name healthcheck --repeat 10 --repeat-mode parallel

# Skip SSL verification for self-signed certs
fling run api.http --name test -k

# Set a global timeout of 5 seconds
fling run api.http --all --timeout 5000
```

---

## `fling list`

List all requests in a `.http` file.

```
fling list [OPTIONS] FILE
```

**Arguments:**

| Argument | Description |
|---|---|
| `FILE` | Path to the `.http` file (required) |

**Example:**

```bash
$ fling list api.http
1. login (POST https://api.example.com/auth/login)
2. getUsers (GET https://api.example.com/users)
3. createUser (POST https://api.example.com/users)
```

---

## `fling envs`

List available environments from environment configuration files.

```
fling envs [OPTIONS]
```

**Options:**

| Option | Description |
|---|---|
| `--env-file PATH` | Path to directory containing environment files (default: current directory) |

**Example:**

```bash
$ fling envs
Available environments:
  development
  staging
  production
```

---

## `fling convert`

Convert a Postman v2.1 collection to `.http` file(s).

```
fling convert [OPTIONS] POSTMAN_FILE
```

**Arguments:**

| Argument | Description |
|---|---|
| `POSTMAN_FILE` | Path to the Postman collection JSON file (required) |

**Options:**

| Option | Description |
|---|---|
| `-o, --output PATH` | Output directory for `.http` files (default: current directory) |
| `--split-folders` | Create one `.http` file per top-level folder |

**Examples:**

```bash
# Convert to a single .http file
fling convert my-api.postman_collection.json -o ./http-files/

# Split into separate files per folder
fling convert my-api.postman_collection.json -o ./http-files/ --split-folders
```

---

## `fling fmt`

Format `.http` file(s) to canonical style.

```
fling fmt [OPTIONS] FILES...
```

Normalises whitespace, aligns headers on the `:` character, ensures consistent `###` separators, and sorts file-level variables to the top.

**Arguments:**

| Argument | Description |
|---|---|
| `FILES...` | One or more `.http` files to format (required) |

**Options:**

| Option | Description |
|---|---|
| `--check` | Don't write changes; exit with code 1 if any file would change |
| `--diff` | Show a unified diff of changes instead of writing |

**Formatting rules:**

1. File-level variables (`@name = value`) are placed first
2. Requests are separated by `###` on its own line with blank lines before and after
3. Metadata comments (`# @name`, `# @ref`, etc.) appear immediately before the request line
4. Headers are vertically aligned on the `:` character
5. A single blank line separates headers from body
6. Response handlers and save directives are preceded by a blank line
7. Trailing whitespace is stripped from all lines
8. The file ends with a single trailing newline

**Examples:**

```bash
# Format files in-place
fling fmt api.http tests.http

# Check formatting without modifying (useful in CI)
fling fmt --check api.http

# Show what would change
fling fmt --diff api.http
```

---

## `fling validate`

Validate `.http` file(s) for common issues.

```
fling validate [OPTIONS] FILES...
```

**Arguments:**

| Argument | Description |
|---|---|
| `FILES...` | One or more `.http` files to validate (required) |

**Options:**

| Option | Description |
|---|---|
| `--strict` | Treat warnings as errors (exit with code 1 on any warning) |

**Checks performed:**

| Check | Severity | Description |
|---|---|---|
| Parse errors | Error | Syntax errors in the `.http` file |
| Duplicate names | Error | Two or more requests share the same `@name` |
| Circular `@ref` | Error | Circular dependency chains between requests |
| Undefined variables | Warning | `{{var}}` references that can't be resolved statically |
| Missing Content-Type | Warning | Requests with a body but no `Content-Type` header |

The undefined-variables check is intentionally lenient: references to environment variables, system variables (`$uuid`, etc.), `$env.X`, `$processEnv`, `$dotenv`, and chaining patterns are considered potentially resolvable at runtime and are not flagged.

**Examples:**

```bash
# Validate a file
fling validate api.http

# Strict mode for CI
fling validate --strict api.http tests.http
```

---

## `fling tui`

Launch the interactive terminal UI.

```
fling tui [OPTIONS] [FILE]
```

**Arguments:**

| Argument | Description |
|---|---|
| `FILE` | Path to a `.http` file (optional) |

**Options:**

| Option | Description |
|---|---|
| `-e, --env TEXT` | Environment name to use |

**Example:**

```bash
fling tui api.http --env development
```

---

## `fling serve`

Launch the web interface for `.http` files.

```
fling serve [OPTIONS] [PATH]
```

PATH can be a single `.http` file or a directory containing `.http` files. When omitted, the current working directory is scanned.

**Arguments:**

| Argument | Description |
|---|---|
| `PATH` | `.http` file or directory (optional, defaults to `.`) |

**Options:**

| Option | Description |
|---|---|
| `-p, --port INTEGER` | Port to serve on (default: 8000) |
| `--host TEXT` | Host to bind to (default: `127.0.0.1`) |
| `-e, --env TEXT` | Environment name to use |
| `--watch / --no-watch` | Enable or disable live file watching (default: on) |

**Examples:**

```bash
# Serve current directory
fling serve

# Serve a specific directory on a custom port
fling serve ./api/ --port 9000

# Serve with an environment and file watching disabled
fling serve api.http --env production --no-watch
```
