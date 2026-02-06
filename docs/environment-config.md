# Environment Configuration

fling uses a layered environment system for managing variables across different contexts (development, staging, production, etc.). This guide covers all configuration files, the `_shared` concept, private overrides, and variable resolution precedence.

## Environment Files

fling looks for environment files in the same directory as the `.http` file (or the directory specified with `--env-file`):

| File | Purpose | Version Control |
|---|---|---|
| `http-client.env.json` | Public environment variables | Commit to VCS |
| `http-client.private.env.json` | Private overrides (secrets, tokens) | Gitignore |
| `.env` | Standard dotenv variables | Gitignore |

### `http-client.env.json`

The primary environment file. It's a JSON object where each key is an environment name and each value is an object of variable key-value pairs:

```json
{
    "_shared": {
        "host": "https://api.example.com",
        "apiVersion": "v2"
    },
    "development": {
        "host": "http://localhost:3000",
        "username": "dev@example.com",
        "password": "devpass",
        "debug": "true"
    },
    "staging": {
        "host": "https://staging.api.example.com",
        "username": "staging@example.com"
    },
    "production": {
        "username": "admin@example.com"
    }
}
```

Select an environment with the `--env` / `-e` flag:

```bash
fling run api.http --all --env development
```

### The `_shared` Environment

The special `_shared` key defines variables that are available in **all** environments. When you select an environment, `_shared` variables are used as a base, and the selected environment's variables override any that overlap.

In the example above, when using `--env production`:
- `host` resolves to `https://api.example.com` (from `_shared`, since `production` doesn't override it)
- `apiVersion` resolves to `v2` (from `_shared`)
- `username` resolves to `admin@example.com` (from `production`)

When using `--env development`:
- `host` resolves to `http://localhost:3000` (overridden by `development`)
- `apiVersion` resolves to `v2` (from `_shared`)
- `username` resolves to `dev@example.com` (from `development`)

### `http-client.private.env.json`

The private environment file has the exact same format as the public one. Its values **override** the public file, per environment. Use it for secrets, tokens, and credentials that should not be committed to version control.

```json
{
    "development": {
        "password": "real-dev-password"
    },
    "production": {
        "password": "real-prod-password",
        "apiSecret": "sk_live_..."
    }
}
```

The merge logic is:
1. Load `http-client.env.json`
2. Load `http-client.private.env.json`
3. For each environment name, merge the private variables on top of the public ones

Environments that exist only in the private file are also included.

### `.env` File

fling also loads standard `.env` files using python-dotenv:

```
DATABASE_URL=postgresql://localhost/mydb
API_KEY=sk_test_123456
DEBUG=true
```

`.env` variables are accessible in two ways:

1. Via the `$dotenv` system variable: `{{$dotenv API_KEY}}`
2. As layer 4 in the variable precedence chain (below environment variables, above system variables)

## Variable Resolution Precedence

When fling encounters a `{{variable}}` template, it resolves it through a 5-layer precedence chain. The first layer that provides a value wins:

| Priority | Layer | Source | How it's set |
|---|---|---|---|
| 1 (highest) | Request-scoped | `client.global.set()`, chaining results | At runtime via scripts or `--name` dependencies |
| 2 | File variables | `@var = value` in the `.http` file | Defined in the `.http` file header |
| 3 | Environment variables | `http-client.env.json` (merged with `_shared` and private) | Defined in env JSON files, selected with `--env` |
| 4 | `.env` variables | `.env` file | Defined in the `.env` file |
| 5 (lowest) | System variables | Dynamic values (`$uuid`, `$timestamp`, etc.) | Generated at resolution time |

### Example

Given:

```
# .env
token=dotenv-token

# http-client.env.json
{"dev": {"token": "env-token"}}
```

```http
@token = file-token

### Test
GET https://api.example.com/test
Authorization: Bearer {{token}}
```

- Without `--env`: resolves to `file-token` (layer 2)
- With `--env dev`: resolves to `file-token` (layer 2 takes priority over layer 3)

If the `@token` line is removed, the same request would resolve to:
- Without `--env`: `dotenv-token` (layer 4)
- With `--env dev`: `env-token` (layer 3 takes priority over layer 4)

## System Variables

System variables start with `$` and generate dynamic values at resolution time. They are always available regardless of environment selection.

### `$uuid` / `$guid`

Generate a random UUID v4:

```http
GET https://api.example.com/test
X-Request-ID: {{$uuid}}
X-Correlation-ID: {{$guid}}
```

Both `$uuid` and `$guid` produce the same output -- a random UUID v4 string like `550e8400-e29b-41d4-a716-446655440000`.

### `$timestamp`

Unix timestamp in seconds (integer):

```http
GET https://api.example.com/test?ts={{$timestamp}}
```

Produces something like `1706140800`.

### `$isoTimestamp`

ISO 8601 UTC timestamp:

```http
POST https://api.example.com/events
Content-Type: application/json

{"created_at": "{{$isoTimestamp}}"}
```

Produces something like `2026-01-25T10:00:00Z`.

### `$datetime`

Formatted datetime with a format specifier. Supports named formats and custom strftime patterns:

```http
# Named formats
GET https://api.example.com/test
X-Date-ISO: {{$datetime "iso8601"}}
X-Date-RFC: {{$datetime "rfc1123"}}

# Custom strftime format
X-Date-Custom: {{$datetime "%Y-%m-%d %H:%M:%S"}}
```

| Format | Example Output |
|---|---|
| `iso8601` | `2026-01-25T10:00:00Z` |
| `rfc1123` | `Sat, 25 Jan 2026 10:00:00 GMT` |
| `%Y-%m-%d` | `2026-01-25` |
| `%H:%M:%S` | `10:00:00` |

### `$randomInt`

Random integer, optionally within a range:

```http
# Default range: 0-1000
GET https://api.example.com/users/{{$randomInt}}

# Custom range: 1-100
GET https://api.example.com/users/{{$randomInt 1 100}}

# Custom max only (min defaults to 0)
GET https://api.example.com/users/{{$randomInt 50}}
```

### `$processEnv`

Read an OS environment variable:

```http
GET https://api.example.com/test
Authorization: Bearer {{$processEnv API_TOKEN}}
```

Returns the value of the `API_TOKEN` environment variable from the process environment.

### `$dotenv`

Read a variable from the `.env` file:

```http
GET https://api.example.com/test
Authorization: Bearer {{$dotenv API_KEY}}
```

### `$env.VAR`

Access an OS environment variable using dot notation:

```http
GET https://api.example.com/test
Authorization: Bearer {{$env.API_TOKEN}}
```

This is equivalent to `{{$processEnv API_TOKEN}}`.

## Listing Environments

Use `fling envs` to see available environments:

```bash
$ fling envs
Available environments:
  development
  staging
  production

$ fling envs --env-file ./config/
Available environments:
  local
  ci
```

The `_shared` and internal keys (prefixed with `_`) are excluded from the listing.

## Environment Editing (Web Interface)

The web interface provides an in-browser environment editor accessible from the environment dropdown. Changes are saved atomically to `http-client.env.json` using a temporary file and `os.replace()` for crash safety. Only the public environment file is modified -- the private file is never changed by the editor.
