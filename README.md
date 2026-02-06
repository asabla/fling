# fling

A Python-native HTTP API testing tool built on `.http` files. Run, test, and manage HTTP requests from the command line, a terminal UI, or a web browser.

## Features

- **`.http` file support** -- parse and execute requests defined in the standard `.http` / `.rest` format used by JetBrains IDEs and the REST Client VS Code extension
- **Variable resolution** -- environment files (`http-client.env.json`), `.env` files, file-level `@variables`, system variables (`$uuid`, `$timestamp`, etc.), and request chaining (`{{login.response.body.$.token}}`)
- **Response handler scripting** -- `> {% %}` inline scripts with `client.test()` assertions and `client.global.set()` for passing data between requests; best-effort JS-to-Python transpilation
- **Postman converter** -- import Postman v2.1 collections (with auth inheritance, folders, variables) into `.http` files
- **Formatting and validation** -- `fling fmt` normalises `.http` files to canonical style; `fling validate` catches duplicate names, circular refs, undefined variables, and missing headers
- **Three interfaces**:
  - **CLI** -- `fling run`, `fling list`, `fling envs`, `fling convert`, `fling fmt`, `fling validate`
  - **TUI** -- interactive Textual terminal UI with collection tree, request/response panels, and collection runner
  - **Web** -- FastAPI + HTMX browser interface with SSE streaming, live file watching, environment editing, execution history, and response comparison

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

```bash
# Install core (CLI only)
pip install fling

# Install with TUI support
pip install fling[tui]

# Install with web interface
pip install fling[web]

# Install everything
pip install fling[all]
```

For development:

```bash
git clone <repo-url>
cd fling
uv sync --all-extras
```

## Quick Start

### 1. Create an `.http` file

```http
### Login
# @name login
POST https://api.example.com/auth/login
Content-Type: application/json

{
    "username": "{{username}}",
    "password": "{{password}}"
}

> {%
client.test("Login successful", function() {
    client.assert(response.status === 200);
});
client.global.set("token", response.body.token);
%}

###

### Get Users
# @ref login
GET https://api.example.com/users
Authorization: Bearer {{login.response.body.$.token}}
```

### 2. Create an environment file

Create `http-client.env.json` in the same directory:

```json
{
    "_shared": {
        "host": "https://api.example.com"
    },
    "development": {
        "username": "dev@example.com",
        "password": "devpass"
    },
    "production": {
        "username": "admin@example.com",
        "password": "prodpass"
    }
}
```

### 3. Run requests

```bash
# Run all requests in the file
fling run api.http --all

# Run a specific named request
fling run api.http --name login

# Run with an environment
fling run api.http --all --env development

# See verbose output
fling run api.http --name login --env development --verbose
```

### 4. List requests and environments

```bash
# List all requests in a file
fling list api.http

# List available environments
fling envs
fling envs --env-file ./config/
```

### 5. Format and validate

```bash
# Format files to canonical style
fling fmt api.http

# Check formatting without modifying
fling fmt --check api.http

# Validate for common issues
fling validate api.http

# Strict mode: treat warnings as errors
fling validate --strict api.http
```

### 6. Convert from Postman

```bash
# Convert a Postman v2.1 collection to a single .http file
fling convert collection.json -o ./output/

# Split into one file per top-level folder
fling convert collection.json -o ./output/ --split-folders
```

### 7. Launch interactive interfaces

```bash
# Terminal UI
fling tui api.http

# Web interface (scans current directory for .http files)
fling serve

# Web interface with a specific file and environment
fling serve api.http --env development --port 9000
```

## CLI Reference

| Command | Description |
|---|---|
| `fling run FILE` | Run HTTP requests from a `.http` file |
| `fling list FILE` | List all requests in a `.http` file |
| `fling envs` | List available environments |
| `fling convert FILE` | Convert a Postman collection to `.http` files |
| `fling fmt FILES...` | Format `.http` files to canonical style |
| `fling validate FILES...` | Validate `.http` files for common issues |
| `fling tui [FILE]` | Launch the interactive TUI |
| `fling serve [PATH]` | Launch the web interface |

See the full [CLI Reference](docs/cli-reference.md) for all options and flags.

## `.http` File Format

fling supports the standard `.http` file format used by JetBrains IDEs and the REST Client VS Code extension. Here is a quick overview:

```http
@host = https://api.example.com

### Create User
# @name createUser
# @note Creates a new user account
POST {{host}}/users
Content-Type: application/json

{
    "name": "Alice",
    "email": "alice@example.com"
}

> {%
client.test("User created", function() {
    client.assert(response.status === 201);
});
client.global.set("userId", response.body.id);
%}

###

### Get User
# @ref createUser
GET {{host}}/users/{{createUser.response.body.$.id}}
Authorization: Bearer {{token}}

>> ./responses/user.json
```

### Key features

- **File-level variables**: `@var = value` at the top of the file
- **Request separators**: `###` between requests (with optional title)
- **Metadata tags**: `# @name`, `# @ref`, `# @timeout`, `# @disabled`, `# @no-redirect`, `# @no-cookie-jar`, `# @prompt`, `# @note`
- **Body types**: inline JSON/XML/text, file references (`< ./body.json`), GraphQL
- **Response handlers**: inline scripts (`> {% ... %}`), file references (`> ./handler.js`)
- **Response saving**: `>> ./output.json` (create/overwrite), `>>! ./output.json` (force overwrite)
- **Request chaining**: `{{name.response.body.$.jsonpath}}` and `{{name.response.headers.HeaderName}}`

See the full [`.http` File Format Guide](docs/http-file-format.md) for complete syntax documentation.

## Environment Configuration

fling supports a layered environment system with five levels of variable precedence:

| Priority | Source | Description |
|---|---|---|
| 1 (highest) | Request-scoped | From chaining, `client.global.set()` |
| 2 | File variables | `@var = value` in `.http` file |
| 3 | Environment | `http-client.env.json` |
| 4 | `.env` file | Standard `.env` format |
| 5 (lowest) | System variables | `$uuid`, `$timestamp`, `$randomInt`, etc. |

### Environment files

- `http-client.env.json` -- public environment variables (committed to VCS)
- `http-client.private.env.json` -- private overrides (gitignored, for secrets/tokens)
- `.env` -- standard dotenv file, accessed via `{{$dotenv VAR_NAME}}`

### System variables

| Variable | Description |
|---|---|
| `{{$uuid}}` / `{{$guid}}` | Random UUID v4 |
| `{{$timestamp}}` | Unix timestamp (seconds) |
| `{{$isoTimestamp}}` | ISO 8601 UTC timestamp |
| `{{$datetime "format"}}` | Custom-formatted datetime (`iso8601`, `rfc1123`, or strftime) |
| `{{$randomInt}}` | Random integer 0--1000 |
| `{{$randomInt min max}}` | Random integer in range |
| `{{$processEnv VAR}}` | OS environment variable |
| `{{$dotenv VAR}}` | Variable from `.env` file |

See the full [Environment Configuration Guide](docs/environment-config.md) for details on `_shared` environments, private overrides, and variable precedence.

## Response Handler Scripting

fling supports JetBrains-style response handler scripts with best-effort JS-to-Python transpilation:

```http
### Login
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

> {%
// Test the response
client.test("Login returns 200", function() {
    client.assert(response.status === 200);
});

// Extract token for later requests
client.global.set("authToken", response.body.token);
%}
```

### Available APIs

- `response.status` -- HTTP status code
- `response.body` -- parsed JSON body (with dot-access) or raw string
- `response.headers` -- response headers dict
- `response.content_type` -- Content-Type header value
- `client.test(name, callback)` -- register a named test
- `client.assert(condition)` -- assert a condition
- `client.global.set(key, value)` -- set a global variable
- `client.global.get(key)` -- get a global variable

See the full [Scripting Guide](docs/scripting.md) for transpilation details and supported patterns.

## Postman Migration

Convert Postman v2.1 collections to `.http` files:

```bash
fling convert my-api.postman_collection.json -o ./http-files/
```

### What gets converted

- Request method, URL, headers, and body (raw, urlencoded, formdata, GraphQL)
- Auth inheritance (bearer, basic, API key) resolved to explicit headers
- Collection and folder variables mapped to `@variable = value`
- Folder structure preserved as comment banners
- Disabled requests marked with `# @disabled`
- Pre-request and test scripts preserved as comments with TODO markers

See the full [Postman Migration Guide](docs/postman-migration.md) for details.

## Web Interface

The web interface provides a browser-based UI for working with `.http` files:

```bash
# Scan current directory for .http files
fling serve

# Serve a specific directory with environment
fling serve ./api/ --env development --port 9000
```

### Features

- **Directory scanning** -- automatically discovers all `.http` files in a directory
- **Live file watching** -- SSE-based hot-reload when `.http` or environment files change
- **Request execution** -- SSE-streamed execution with real-time output
- **Environment management** -- switch environments, edit variables in-browser
- **Execution history** -- SQLite-backed history stored in `.fling/history.db`
- **Response comparison** -- side-by-side diff of two historical responses (text and JSON)
- **Run All** -- execute all requests in a file sequentially with progress streaming

## TUI

The TUI provides a terminal-based interface built on Textual:

```bash
fling tui api.http --env development
```

### Features

- Collection tree with request browser
- Request detail panel with headers and body
- Response panel with formatted output
- Collection runner with progress display
- Keyboard-driven navigation

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
make test

# Run linter
make lint

# Run type checker
make typecheck

# Run all checks (lint + typecheck + test)
make check

# Format code
make fmt

# Build CSS for web interface
make build-css

# See all available targets
make help
```

### Output Formats

The `fling run` command supports multiple output formats via the `-o` / `--output` flag:

| Format | Description |
|---|---|
| `exchange` | Full HTTP exchange (request + response) |
| `headers` | Response headers only |
| `body` | Response body only |
| `json` | Structured JSON output |
| `json-report` | Full test report in JSON |
| `junit` | JUnit XML format (for CI integration) |
| `markdown` | Markdown-formatted report |

### CI Integration

```bash
# Run with JUnit output for CI
fling run api.http --all --env ci -o junit > results.xml

# Stop on first failure
fling run api.http --all --bail -o json-report

# Validate before running
fling validate --strict api.http && fling run api.http --all

# Format check in CI
fling fmt --check api.http tests.http
```

### Repeat Execution

```bash
# Run a request 10 times sequentially
fling run api.http --name healthcheck --repeat 10

# Run 5 times in parallel
fling run api.http --name healthcheck --repeat 5 --repeat-mode parallel
```

## Project Structure

```
src/fling/
├── __init__.py              # Package root, version
├── cli.py                   # Click CLI entry point
├── core/
│   ├── models.py            # Pydantic v2 data models
│   ├── parser.py            # .http file parser (line-by-line state machine)
│   ├── variables.py         # Variable resolution engine
│   ├── executor.py          # HTTP execution (httpx async)
│   ├── runner.py            # Orchestrator (parse -> resolve -> execute)
│   ├── environment.py       # Environment file loading
│   ├── scripting.py         # Response handler scripting engine
│   ├── formatter.py         # .http file canonical formatter
│   ├── validator.py         # .http file validation checks
│   ├── formatters.py        # Output formatters (JSON, JUnit, Markdown)
│   └── postman.py           # Postman collection converter
├── tui/                     # Textual TUI
│   ├── app.py
│   ├── screens/
│   ├── widgets/
│   └── styles/
└── web/                     # FastAPI + HTMX web interface
    ├── app.py               # FastAPI factory
    ├── scanner.py           # Directory scanning
    ├── watcher.py           # Live file watcher (SSE)
    ├── history.py           # SQLite execution history
    ├── diff.py              # Response comparison utilities
    ├── routes/
    │   ├── pages.py         # Page routes
    │   ├── execution.py     # SSE-streamed execution
    │   ├── environments.py  # Environment CRUD
    │   ├── history.py       # History listing/detail
    │   ├── compare.py       # Response comparison
    │   └── watch.py         # File-change SSE stream
    ├── templates/
    └── static/
```

## Documentation

- [CLI Reference](docs/cli-reference.md) -- all commands, flags, and usage examples
- [`.http` File Format](docs/http-file-format.md) -- complete syntax guide
- [Environment Configuration](docs/environment-config.md) -- environment files, variables, and precedence
- [Response Handler Scripting](docs/scripting.md) -- JS-to-Python transpilation, client/response APIs
- [Postman Migration](docs/postman-migration.md) -- converting Postman collections

## License

MIT
