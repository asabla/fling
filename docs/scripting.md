# Response Handler Scripting

fling supports response handler scripts attached to HTTP requests. Scripts run after the request completes and can test assertions, extract values, and set global variables for subsequent requests.

fling uses best-effort JS-to-Python transpilation to support the JetBrains-style JavaScript syntax commonly found in `.http` files.

## Syntax

### Inline Multi-Line Handler

```http
POST https://api.example.com/auth/login
Content-Type: application/json

{"username": "admin", "password": "secret"}

> {%
client.test("Login successful", function() {
    client.assert(response.status === 200);
});
client.global.set("token", response.body.token);
%}
```

### Inline Single-Line Handler

```http
GET https://api.example.com/health

> {% client.assert(response.status === 200); %}
```

### File Reference Handler

Load the script from an external file:

```http
GET https://api.example.com/users

> ./handlers/check-users.js
```

The path is relative to the `.http` file's directory. The file contents are transpiled the same way as inline scripts.

## Available APIs

### `response` Object

| Property | Type | Description |
|---|---|---|
| `response.status` | `int` | HTTP status code (e.g., 200, 404) |
| `response.body` | object or string | Parsed JSON body (with dot-access) or raw string if not JSON |
| `response.headers` | `dict` | Response headers (first value per header name) |
| `response.content_type` | `string` | Value of the Content-Type header |

When the response body is valid JSON, `response.body` provides recursive dot-access. For example, if the body is `{"data": {"user": {"name": "Alice"}}}`, you can access `response.body.data.user.name`.

When the body is not valid JSON, `response.body` is the raw response string.

### `client` Object

| Method | Description |
|---|---|
| `client.test(name, callback)` | Register a named test. The callback runs immediately. If it throws, the test fails |
| `client.assert(condition)` | Assert a condition is truthy. Throws `AssertionError` if falsy |
| `client.global.set(key, value)` | Set a global variable available to subsequent requests |
| `client.global.get(key)` | Get a global variable value |

### `client.test()`

Registers a named test with an assertion callback:

```javascript
client.test("Status is 200", function() {
    client.assert(response.status === 200);
});

client.test("Has user data", function() {
    client.assert(response.body.users !== null);
    client.assert(response.body.users.length > 0);
});
```

The test name appears in the output. If the callback throws any exception, the test is marked as failed with the error message.

If no callback is provided, the test passes automatically:

```javascript
client.test("Placeholder test");
```

### `client.assert()`

Asserts a condition. Used inside `client.test()` callbacks:

```javascript
client.assert(response.status === 200);
client.assert(response.body.token !== null);
client.assert(response.body.items.length > 0);
```

If the condition is falsy, an `AssertionError` is raised with the message "Assertion failed" (or a custom message if the original script provides one).

### `client.global.set()` / `client.global.get()`

Set and retrieve global variables that persist across requests in the same execution run:

```javascript
// In the login request handler
client.global.set("authToken", response.body.token);
client.global.set("userId", response.body.user.id);

// In a later request handler
var token = client.global.get("authToken");
client.assert(token !== null);
```

Variables set with `client.global.set()` become available as `{{variableName}}` in subsequent requests (layer 1 in the variable precedence chain).

## JS-to-Python Transpilation

fling uses best-effort transpilation to convert JetBrains-style JavaScript to executable Python. The following transformations are applied:

### Supported Transformations

| JavaScript | Python |
|---|---|
| `===` | `==` |
| `!==` | `!=` |
| `null` | `None` |
| `undefined` | `None` |
| `true` | `True` |
| `false` | `False` |
| `var x = ...` / `let x = ...` / `const x = ...` | `x = ...` |
| `client.assert(...)` | `client.assert_(...)` |
| `client.global.set(...)` | `client.globals.set(...)` |
| `client.global.get(...)` | `client.globals.get(...)` |
| `response.body.field` | `response.body["field"]` |
| `response.body.data.status` | `response.body["data"]["status"]` |
| `// comment` | `# comment` |
| `function() { ... }` (in test) | `lambda: (...)` |
| trailing `;` | stripped |

### Multi-Line `client.test()`

Multi-line test blocks with `function() { ... }` are collected and converted to a lambda:

```javascript
// Input (JS)
client.test("User created", function() {
    client.assert(response.status === 201);
    client.assert(response.body.id !== null);
});
```

```python
# Output (Python)
client.test("User created", lambda: (client.assert_(response.status == 201); client.assert_(response.body["id"] != None)))
```

### Single-Line `client.test()`

```javascript
client.test("OK", function() { client.assert(response.status === 200); });
```

Transpiles to:

```python
client.test("OK", lambda: (client.assert_(response.status == 200)))
```

### Response Body Access

Chained dot-access on `response.body` is converted to subscript access:

```javascript
// These are transpiled:
response.body.token          // -> response.body["token"]
response.body.data.status    // -> response.body["data"]["status"]
response.body.users[0].name  // -> response.body["users"][0]["name"]

// These are left as-is:
response.body                // no further access
response.body["key"]         // already subscript
response.status              // not body access
response.headers             // not body access
```

### Unsupported Constructs

The transpiler warns about unsupported JavaScript constructs:

- `for` / `while` loops
- `switch` / `case` statements
- `try` / `catch` / `throw`
- `new` operator
- `typeof` / `instanceof`

These constructs produce a warning but are left in the output. They will likely cause a Python syntax error at execution time.

### Execution Environment

The transpiled Python code is executed with `exec()` in a namespace containing:

| Name | Value |
|---|---|
| `response` | `_ResponseObject` proxy (provides `.status`, `.body`, `.headers`, `.content_type`) |
| `client` | `_ClientObject` proxy (provides `.test()`, `.assert_()`, `.globals`) |
| `json` | Python `json` module (available for manual parsing) |

## Best Practices

### Keep scripts simple

The transpiler handles common patterns well. Stick to `client.test()`, `client.assert()`, `client.global.set/get()`, and simple property access:

```javascript
// Good -- well supported
> {%
client.test("Status OK", function() {
    client.assert(response.status === 200);
});
client.global.set("id", response.body.id);
%}
```

### Avoid complex logic

For complex validation, consider using request chaining and separate requests rather than elaborate scripts:

```javascript
// Avoid -- complex constructs may not transpile correctly
> {%
for (var i = 0; i < response.body.items.length; i++) {
    client.assert(response.body.items[i].active === true);
}
%}
```

### Use `client.global.set()` for chaining

When you need to pass data between requests, use global variables:

```http
### Login
# @name login
POST https://api.example.com/auth
Content-Type: application/json

{"username": "admin", "password": "secret"}

> {%
client.global.set("token", response.body.token);
%}

###

### Use Token
GET https://api.example.com/protected
Authorization: Bearer {{token}}
```

## Script Results

After execution, each script produces a `ScriptResult` containing:

- **tests**: list of named test results (name, passed/failed, error message)
- **global_vars**: dictionary of global variables set during execution
- **warnings**: list of transpilation warnings
- **error**: error message if script execution failed

Test results are displayed in the CLI output, TUI response panel, and web interface execution view.
