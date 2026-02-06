# fling

A Python-native HTTP API testing tool built on `.http` files. Run, test, and manage HTTP requests from the command line, a terminal UI, or a web browser.

## Features

- **`.http` file support** -- parse and execute requests defined in the standard `.http` / `.rest` format used by JetBrains IDEs and the REST Client VS Code extension
- **Variable resolution** -- environment files (`http-client.env.json`), `.env` files, file-level `@variables`, system variables (`$uuid`, `$timestamp`, etc.), and request chaining (`{{login.response.body.$.token}}`)
- **Response handler scripting** -- `> {% %}` inline scripts with `client.test()` assertions and `client.global.set()` for passing data between requests; best-effort JS-to-Python transpilation
- **Postman converter** -- import Postman v2.1 collections (with auth inheritance, folders, variables) into `.http` files
- **Three interfaces**:
  - **CLI** -- `fling run`, `fling list`, `fling envs`, `fling convert`
  - **TUI** -- interactive Textual terminal UI with collection tree, request/response panels, and collection runner
  - **Web** -- FastAPI + HTMX browser interface with SSE streaming execution

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

### Run requests from an `.http` file

```bash
# Run all requests
fling run api.http

# Run a specific named request
fling run api.http --name login

# Run with an environment
fling run api.http --env production

# List available requests
fling list api.http

# List available environments
fling envs api.http
```

### Convert a Postman collection

```bash
fling convert collection.json -o output.http
```

### Launch the TUI

```bash
fling tui api.http
```

### Launch the web interface

```bash
fling serve api.http
# Opens at http://localhost:8000
```

## `.http` File Format

```http
### Login
# @name login
# @timeout 5000
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
# @name getUsers
# @ref login
GET https://api.example.com/users
Authorization: Bearer {{login.response.body.$.token}}
```

### Supported metadata tags

| Tag | Description |
|---|---|
| `# @name <name>` | Name the request (required for chaining) |
| `# @ref <name>` | Declare a dependency on another request |
| `# @no-redirect` | Disable automatic redirect following |
| `# @no-cookie-jar` | Disable cookie persistence |
| `# @timeout <ms>` | Set per-request timeout in milliseconds |
| `# @disabled` | Skip this request during execution |
| `# @prompt <var> <text>` | Prompt for a variable value at runtime |
| `# @note <text>` | Add a descriptive note |

### Variable sources (precedence high to low)

1. Request-scoped variables (from chaining / `client.global.set`)
2. File-level variables (`@var = value`)
3. Environment variables (`http-client.env.json`)
4. `.env` file variables
5. System variables (`$uuid`, `$timestamp`, `$randomInt`, etc.)

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

# Run all checks
make check

# Format code
make fmt

# See all available targets
make help
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
│   └── postman.py           # Postman collection converter
├── tui/                     # Textual TUI
│   ├── app.py
│   ├── screens/
│   ├── widgets/
│   └── styles/
└── web/                     # FastAPI + HTMX web interface
    ├── app.py
    ├── routes/
    ├── templates/
    └── static/
```

## License

MIT
