# `.http` File Format

fling uses the `.http` file format (also known as `.rest`) for defining HTTP requests. This format is compatible with JetBrains IDEs (IntelliJ, WebStorm, etc.) and the REST Client extension for VS Code.

## Basic Structure

An `.http` file contains one or more HTTP requests separated by `###` lines:

```http
### First Request
GET https://api.example.com/users

###

### Second Request
POST https://api.example.com/users
Content-Type: application/json

{"name": "Alice"}
```

## Request Syntax

Each request consists of:

1. An optional separator (`###`) with an optional title
2. Optional metadata comments (`# @name`, `# @ref`, etc.)
3. The request line: `METHOD URL [HTTP-VERSION]`
4. Optional headers (`Name: Value`, one per line)
5. A blank line followed by an optional body
6. Optional response handler or save directive

### Request Line

```http
GET https://api.example.com/users
POST https://api.example.com/users HTTP/1.1
DELETE https://api.example.com/users/123
```

The HTTP version is optional. Supported methods include GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS, TRACE, and CONNECT.

### Headers

Headers follow the request line, one per line in `Name: Value` format:

```http
GET https://api.example.com/users
Accept: application/json
Authorization: Bearer {{token}}
X-Request-ID: {{$uuid}}
```

### Request Body

A blank line separates headers from the body:

```http
POST https://api.example.com/users
Content-Type: application/json

{
    "name": "Alice",
    "email": "alice@example.com"
}
```

## File-Level Variables

Define reusable variables at the top of the file with `@name = value`:

```http
@host = https://api.example.com
@contentType = application/json

### Get Users
GET {{host}}/users
Accept: {{contentType}}

###

### Create User
POST {{host}}/users
Content-Type: {{contentType}}

{"name": "Alice"}
```

Variables defined this way are available to all requests in the file. They can contain `{{...}}` template expressions that are resolved at execution time.

## Request Separators

Requests are separated by `###` on its own line. The separator can optionally include a title:

```http
### Login Request
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

### Get User Profile
GET https://api.example.com/profile
Authorization: Bearer {{token}}
```

A separator is required between requests but optional before the first request and after the last.

## Metadata Tags

Metadata tags are special comments that control request behaviour. They appear on lines immediately before the request line:

```http
### Login
# @name login
# @timeout 5000
# @note Main authentication endpoint
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "{{username}}", "password": "{{password}}"}
```

### Available Tags

| Tag | Description |
|---|---|
| `# @name <name>` | Name the request. Required for request chaining and for targeting with `--name` |
| `# @ref <name>` | Declare a dependency on another named request. That request will run first |
| `# @no-redirect` | Disable automatic redirect following for this request |
| `# @no-cookie-jar` | Disable cookie persistence for this request |
| `# @timeout <ms>` | Set a per-request timeout in milliseconds |
| `# @disabled` | Skip this request during execution |
| `# @prompt <var> <description>` | Prompt the user for a variable value at runtime |
| `# @note <text>` | Add a descriptive note (displayed in the TUI and web interface) |

### `@name`

Names a request so it can be referenced by other requests or targeted from the CLI:

```http
# @name login
POST https://api.example.com/auth/login
```

```bash
fling run api.http --name login
```

### `@ref`

Declares that this request depends on another named request. The referenced request will be executed first, and its results are available for chaining:

```http
# @name login
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

###

# @name getProfile
# @ref login
GET https://api.example.com/profile
Authorization: Bearer {{login.response.body.$.token}}
```

Multiple `@ref` tags are allowed on a single request.

### `@prompt`

Prompts the user for a value at runtime:

```http
# @prompt apiKey Enter your API key
GET https://api.example.com/data
Authorization: Bearer {{apiKey}}
```

## Body Types

### Inline Body

The most common form. A blank line after headers starts the body:

```http
POST https://api.example.com/users
Content-Type: application/json

{
    "name": "Alice",
    "email": "alice@example.com"
}
```

### File Reference

Load the body from an external file using `< path`:

```http
POST https://api.example.com/users
Content-Type: application/json

< ./bodies/create-user.json
```

The path is relative to the `.http` file's directory.

### GraphQL

GraphQL requests use a JSON body with `query` and optional `variables`:

```http
POST https://api.example.com/graphql
Content-Type: application/json

{
    "query": "query { users { id name email } }",
    "variables": {"limit": 10}
}
```

## Response Handlers

Response handlers let you run scripts after a request completes. They can test assertions, extract values, and set global variables for subsequent requests.

### Inline Handler

```http
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

> {%
client.test("Login successful", function() {
    client.assert(response.status === 200);
    client.assert(response.body.token !== null);
});
client.global.set("token", response.body.token);
%}
```

### Single-Line Handler

For simple checks:

```http
GET https://api.example.com/health

> {% client.assert(response.status === 200); %}
```

### File Reference Handler

Load the handler script from an external file:

```http
GET https://api.example.com/users

> ./handlers/check-users.js
```

See the [Scripting Guide](scripting.md) for full details on the available APIs and transpilation rules.

## Response Save

Save the response body to a file:

```http
GET https://api.example.com/users

>> ./responses/users.json
```

Use `>>!` to force overwrite:

```http
GET https://api.example.com/users

>>! ./responses/users.json
```

The path is relative to the `.http` file's directory.

## Pre-Request Scripts

Execute a script before the request is sent:

```http
### Request with pre-processing
< {%
// Pre-request script (currently preserved by formatter)
%}
POST https://api.example.com/data
Content-Type: application/json

{"timestamp": "{{$timestamp}}"}
```

## Comments

Lines starting with `#` or `//` are treated as comments:

```http
# This is a comment
// This is also a comment

### Get Users
# Fetch all active users from the API
GET https://api.example.com/users?active=true
```

Comments starting with `# @` are parsed as metadata tags (see above). All other `#` comments are preserved as regular comments.

## Request Chaining

Request chaining lets you use values from a previous request's response in subsequent requests.

### Body Chaining (JSONPath)

Extract values from a JSON response body using JSONPath syntax:

```http
### Login
# @name login
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

###

### Access Protected Resource
# @ref login
GET https://api.example.com/protected
Authorization: Bearer {{login.response.body.$.token}}
```

The syntax is `{{requestName.response.body.$.jsonpath}}` where `jsonpath` is a JSONPath expression evaluated against the response body.

### Header Chaining

Extract a specific response header:

```http
### Create Resource
# @name create
POST https://api.example.com/resources
Content-Type: application/json

{"name": "test"}

###

### Get Created Resource
# @ref create
GET {{create.response.headers.Location}}
```

The syntax is `{{requestName.response.headers.HeaderName}}`.

## Variable Interpolation

Variables are enclosed in double curly braces: `{{variableName}}`. They can appear in URLs, headers, and request bodies. Variables are **not** resolved during parsing -- they are resolved at execution time.

```http
@host = https://api.example.com

### Example
GET {{host}}/users/{{$randomInt 1 100}}
Authorization: Bearer {{$processEnv API_TOKEN}}
X-Request-ID: {{$uuid}}
Accept: application/json
```

See the [Environment Configuration Guide](environment-config.md) for details on all variable types and their resolution precedence.

## Complete Example

```http
@host = https://api.example.com

### Login
# @name login
# @note Authenticate and get a bearer token
POST {{host}}/auth/login
Content-Type: application/json

{
    "username": "{{username}}",
    "password": "{{password}}"
}

> {%
client.test("Login returns 200", function() {
    client.assert(response.status === 200);
});
client.test("Has token", function() {
    client.assert(response.body.token !== null);
});
client.global.set("authToken", response.body.token);
%}

###

### Create User
# @name createUser
# @ref login
POST {{host}}/users
Content-Type: application/json
Authorization: Bearer {{login.response.body.$.token}}

{
    "name": "Alice",
    "email": "alice@example.com",
    "role": "admin"
}

> {%
client.test("User created", function() {
    client.assert(response.status === 201);
});
%}

>> ./responses/created-user.json

###

### Get User
# @ref createUser
GET {{host}}/users/{{createUser.response.body.$.id}}
Authorization: Bearer {{login.response.body.$.token}}

###

### Health Check
# @no-redirect
# @timeout 3000
GET {{host}}/health
```
