# Postman Migration Guide

fling can convert Postman v2.1 collections into `.http` files using the `fling convert` command. This guide covers the conversion process, what gets translated, and what may need manual adjustment.

## Basic Usage

```bash
# Convert to a single .http file
fling convert my-api.postman_collection.json -o ./http-files/

# Split into one file per top-level folder
fling convert my-api.postman_collection.json -o ./http-files/ --split-folders
```

The `-o` flag specifies the output directory (defaults to the current directory). The output file is named after the collection.

## Single File vs. Split Folders

### Single file (default)

All requests are written to a single `.http` file. Folder boundaries are preserved as comment banners:

```http
# My API Collection
# Collection description

@baseUrl = https://api.example.com

# ============================================================
# Folder: Authentication
# ============================================================

### Login
POST {{baseUrl}}/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

### Logout
POST {{baseUrl}}/auth/logout
Authorization: Bearer {{token}}

# ============================================================
# Folder: Users
# ============================================================

### Get Users
GET {{baseUrl}}/users
Authorization: Bearer {{token}}
```

### Split folders (`--split-folders`)

Each top-level folder becomes a separate `.http` file. Top-level requests (not in any folder) go into a file named after the collection. All files share the same variable preamble (collection name, description, and variables).

```
output/
├── authentication.http
├── users.http
└── my-api-collection.http    # top-level requests (if any)
```

Subfolder boundaries within each file are preserved as comment banners.

## What Gets Converted

### Requests

| Postman Feature | `.http` Output |
|---|---|
| Method + URL | Request line (`GET https://...`) |
| Headers | Header lines (`Name: Value`) |
| Disabled headers | Comment lines (`# Name: Value`) |
| Request name | `### Name` separator |
| Request description | Comment lines below separator |
| Disabled request | `# @disabled` metadata tag |

### Request Body

| Postman Body Mode | `.http` Output |
|---|---|
| `raw` (JSON) | Inline body + `Content-Type: application/json` |
| `raw` (XML) | Inline body + `Content-Type: application/xml` |
| `raw` (text) | Inline body + `Content-Type: text/plain` |
| `urlencoded` | `key=value&key2=value2` + `Content-Type: application/x-www-form-urlencoded` |
| `formdata` | `key=value` pairs + `Content-Type: multipart/form-data`; file entries as `# @file key: path` comments |
| `graphql` | JSON body with `query` and `variables` + `Content-Type: application/json` |

The `Content-Type` header is added automatically when the body mode implies one, unless the request already has an explicit `Content-Type` header.

### Authentication

Postman's auth configuration is resolved through an inheritance chain and converted to explicit headers:

| Postman Auth Type | `.http` Output |
|---|---|
| `bearer` | `Authorization: Bearer <token>` |
| `basic` | `Authorization: Basic <base64(user:pass)>` |
| `apikey` (in header) | `<key>: <value>` header |
| `apikey` (in query) | Appended to URL as query parameter |
| `noauth` | No auth header (blocks inheritance) |
| `oauth2`, `digest`, etc. | Not converted (unsupported) |

### Auth Inheritance

Postman supports auth inheritance where requests inherit auth from their parent folder or the collection root. fling resolves the effective auth for each request by walking the chain:

1. Request's own auth (if set and not `noauth`)
2. Nearest parent folder's auth
3. Collection-level auth

An explicit `noauth` at any level stops the chain -- requests below it will have no auth even if a parent defines one.

The resolved auth is written as an explicit header on each request in the `.http` output, so there is no implicit inheritance in the generated files.

### Variables

| Postman Source | `.http` Output |
|---|---|
| Collection variables | `@key = value` file-level variables |
| Folder variables | `@key = value` (within the folder section) |
| Disabled variables | Skipped |

Postman's `{{variable}}` syntax is preserved as-is since fling uses the same template syntax. However, Postman variables are resolved differently (they come from collection/environment/global scopes in Postman), so you may need to:

1. Create an `http-client.env.json` file with your environment variables
2. Move collection variables that should vary by environment into the env file

### Scripts and Events

Postman pre-request and test scripts are preserved as comments with TODO markers:

```http
### Login
# [Pre-request Script]
# TODO: Convert to response handler
#   pm.environment.set("timestamp", Date.now());
# [Test Script]
# TODO: Convert to response handler
#   pm.test("Status code is 200", function () {
#       pm.response.to.have.status(200);
#   });
POST https://api.example.com/auth/login
```

These need manual conversion to fling's response handler format. See the [Scripting Guide](scripting.md) for the available APIs.

**Common Postman-to-fling script mappings:**

| Postman (`pm.*`) | fling |
|---|---|
| `pm.test("name", function() {...})` | `client.test("name", function() {...})` |
| `pm.response.to.have.status(200)` | `client.assert(response.status === 200)` |
| `pm.response.json()` | `response.body` (auto-parsed) |
| `pm.environment.set("key", val)` | `client.global.set("key", val)` |
| `pm.environment.get("key")` | `client.global.get("key")` |
| `pm.globals.set("key", val)` | `client.global.set("key", val)` |

## Limitations

### Not converted

- **OAuth 2.0 / Digest / NTLM / Hawk auth** -- only bearer, basic, and API key auth types are supported
- **Pre-request scripts** -- preserved as comments; need manual conversion
- **Test scripts** -- preserved as comments; need manual conversion
- **Postman dynamic variables** -- `{{$randomInt}}`, `{{$guid}}`, etc. use the same syntax but Postman has different dynamic variables than fling. Most common ones (`$randomInt`, `$guid`, `$timestamp`) work in both
- **Certificate-based auth** -- not supported in `.http` format
- **Proxy settings** -- not converted
- **Collection runner settings** (delays, iterations) -- not converted

### May need adjustment

- **Environment variables** -- create `http-client.env.json` and migrate Postman environment exports
- **Variable scoping** -- Postman has global/collection/environment/local scopes; fling has a different precedence chain
- **File uploads** -- form-data file entries are written as comments (`# @file key: path`)
- **URL construction** -- Postman's structured URL is reconstructed; complex path parameters may need review
- **Response time assertions** -- Postman's `pm.response.responseTime` has no fling equivalent

## Migration Workflow

1. **Export from Postman**: Export your collection as Collection v2.1 JSON
2. **Convert**: Run `fling convert collection.json -o ./http-files/`
3. **Create environments**: Create `http-client.env.json` with your environment variables
4. **Review scripts**: Search for `TODO: Convert to response handler` comments and rewrite them
5. **Test**: Run `fling validate ./http-files/*.http` to catch issues, then `fling run` to verify
6. **Format**: Run `fling fmt ./http-files/*.http` to normalize the generated files

## Example

### Input: Postman Collection

```json
{
    "info": {
        "name": "User API",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    },
    "auth": {
        "type": "bearer",
        "bearer": [{"key": "token", "value": "{{authToken}}"}]
    },
    "variable": [
        {"key": "baseUrl", "value": "https://api.example.com"}
    ],
    "item": [
        {
            "name": "Get Users",
            "request": {
                "method": "GET",
                "url": {"raw": "{{baseUrl}}/users"}
            }
        },
        {
            "name": "Create User",
            "request": {
                "method": "POST",
                "url": {"raw": "{{baseUrl}}/users"},
                "header": [
                    {"key": "Content-Type", "value": "application/json"}
                ],
                "body": {
                    "mode": "raw",
                    "raw": "{\"name\": \"Alice\"}",
                    "options": {"raw": {"language": "json"}}
                }
            }
        }
    ]
}
```

### Output: `.http` File

```http
# User API

@baseUrl = https://api.example.com

### Get Users
GET {{baseUrl}}/users
Authorization: Bearer {{authToken}}

### Create User
POST {{baseUrl}}/users
Authorization: Bearer {{authToken}}
Content-Type: application/json

{"name": "Alice"}
```

Notice how the collection-level bearer auth is resolved to an explicit `Authorization` header on each request.
