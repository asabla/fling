"""Tests for the .http file validator."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from click.testing import CliRunner

from fling.cli import main
from fling.core.validator import (
    Severity,
    ValidationResult,
    validate_http_string,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Duplicate request names
# ---------------------------------------------------------------------------


class TestDuplicateNames:
    """Tests for duplicate @name detection."""

    def test_no_duplicates(self) -> None:
        content = dedent("""\
            # @name first
            GET https://example.com/a

            ###

            # @name second
            GET https://example.com/b
        """)
        result = validate_http_string(content)
        dup_issues = [i for i in result.issues if "duplicate" in i.message]
        assert len(dup_issues) == 0

    def test_duplicate_names_detected(self) -> None:
        content = dedent("""\
            # @name login
            POST https://example.com/auth

            ###

            # @name login
            GET https://example.com/check
        """)
        result = validate_http_string(content)
        dup_issues = [i for i in result.issues if "duplicate" in i.message]
        assert len(dup_issues) == 1
        assert dup_issues[0].severity == Severity.ERROR
        assert "'login'" in dup_issues[0].message

    def test_unnamed_requests_not_flagged(self) -> None:
        content = dedent("""\
            GET https://example.com/a

            ###

            GET https://example.com/b
        """)
        result = validate_http_string(content)
        dup_issues = [i for i in result.issues if "duplicate" in i.message]
        assert len(dup_issues) == 0


# ---------------------------------------------------------------------------
# Circular @ref dependencies
# ---------------------------------------------------------------------------


class TestCircularRefs:
    """Tests for circular @ref dependency detection."""

    def test_no_cycle(self) -> None:
        content = dedent("""\
            # @name a
            GET https://example.com/a

            ###

            # @name b
            # @ref a
            GET https://example.com/b
        """)
        result = validate_http_string(content)
        cycle_issues = [i for i in result.issues if "circular" in i.message]
        assert len(cycle_issues) == 0

    def test_direct_cycle_a_b_a(self) -> None:
        content = dedent("""\
            # @name a
            # @ref b
            GET https://example.com/a

            ###

            # @name b
            # @ref a
            GET https://example.com/b
        """)
        result = validate_http_string(content)
        cycle_issues = [i for i in result.issues if "circular" in i.message]
        assert len(cycle_issues) >= 1
        assert cycle_issues[0].severity == Severity.ERROR

    def test_transitive_cycle_a_b_c_a(self) -> None:
        content = dedent("""\
            # @name a
            # @ref c
            GET https://example.com/a

            ###

            # @name b
            # @ref a
            GET https://example.com/b

            ###

            # @name c
            # @ref b
            GET https://example.com/c
        """)
        result = validate_http_string(content)
        cycle_issues = [i for i in result.issues if "circular" in i.message]
        assert len(cycle_issues) >= 1

    def test_self_ref_is_cycle(self) -> None:
        content = dedent("""\
            # @name a
            # @ref a
            GET https://example.com/a
        """)
        result = validate_http_string(content)
        cycle_issues = [i for i in result.issues if "circular" in i.message]
        assert len(cycle_issues) == 1


# ---------------------------------------------------------------------------
# Undefined variable references
# ---------------------------------------------------------------------------


class TestUndefinedVariables:
    """Tests for undefined variable reference detection."""

    def test_defined_variable_not_flagged(self) -> None:
        content = dedent("""\
            @host = example.com

            ###

            GET https://{{host}}/users
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 0

    def test_undefined_variable_flagged(self) -> None:
        content = dedent("""\
            GET https://{{host}}/users
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 1
        assert "'host'" in undef_issues[0].message

    def test_system_vars_not_flagged(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            X-Request-Id: {{$uuid}}
            X-Timestamp: {{$timestamp}}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 0

    def test_env_vars_not_flagged(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            Authorization: Bearer {{$env.API_KEY}}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 0

    def test_chaining_refs_not_flagged(self) -> None:
        content = dedent("""\
            # @name login
            POST https://example.com/auth
            Content-Type: application/json

            {"user": "admin"}

            ###

            # @name getUsers
            # @ref login
            GET https://example.com/users
            Authorization: Bearer {{login.response.body.$.token}}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 0

    def test_process_env_not_flagged(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            Authorization: Bearer {{$processEnv API_KEY}}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 0

    def test_dotenv_not_flagged(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            Authorization: Bearer {{$dotenv API_KEY}}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 0

    def test_undefined_in_body(self) -> None:
        content = dedent("""\
            POST https://example.com/users
            Content-Type: application/json

            {"name": "{{userName}}"}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 1
        assert "'userName'" in undef_issues[0].message

    def test_undefined_in_header_value(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            Authorization: Bearer {{token}}
        """)
        result = validate_http_string(content)
        undef_issues = [i for i in result.issues if "undefined variable" in i.message]
        assert len(undef_issues) == 1
        assert "'token'" in undef_issues[0].message


# ---------------------------------------------------------------------------
# Missing Content-Type
# ---------------------------------------------------------------------------


class TestMissingContentType:
    """Tests for missing Content-Type header detection."""

    def test_body_with_content_type_ok(self) -> None:
        content = dedent("""\
            POST https://example.com/users
            Content-Type: application/json

            {"name": "John"}
        """)
        result = validate_http_string(content)
        ct_issues = [i for i in result.issues if "Content-Type" in i.message]
        assert len(ct_issues) == 0

    def test_body_without_content_type_flagged(self) -> None:
        content = dedent("""\
            POST https://example.com/users

            {"name": "John"}
        """)
        result = validate_http_string(content)
        ct_issues = [i for i in result.issues if "Content-Type" in i.message]
        assert len(ct_issues) == 1
        assert ct_issues[0].severity == Severity.WARNING

    def test_no_body_no_flag(self) -> None:
        content = dedent("""\
            GET https://example.com/users
        """)
        result = validate_http_string(content)
        ct_issues = [i for i in result.issues if "Content-Type" in i.message]
        assert len(ct_issues) == 0

    def test_content_type_case_insensitive(self) -> None:
        content = dedent("""\
            POST https://example.com/users
            content-type: application/json

            {"name": "John"}
        """)
        result = validate_http_string(content)
        ct_issues = [i for i in result.issues if "Content-Type" in i.message]
        assert len(ct_issues) == 0


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


class TestParseErrors:
    """Tests for parse error reporting."""

    def test_clean_file_no_issues(self) -> None:
        content = dedent("""\
            GET https://example.com/users
        """)
        result = validate_http_string(content)
        assert len(result.issues) == 0

    def test_empty_file_no_issues(self) -> None:
        result = validate_http_string("")
        # Empty file: no requests, no issues
        assert not result.has_errors


# ---------------------------------------------------------------------------
# ValidationResult properties
# ---------------------------------------------------------------------------


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_has_errors_true(self) -> None:
        from fling.core.validator import ValidationIssue

        result = ValidationResult(
            issues=[
                ValidationIssue(severity=Severity.ERROR, message="test error"),
            ],
        )
        assert result.has_errors is True
        assert result.error_count == 1
        assert result.warning_count == 0

    def test_has_errors_false_with_warnings(self) -> None:
        from fling.core.validator import ValidationIssue

        result = ValidationResult(
            issues=[
                ValidationIssue(severity=Severity.WARNING, message="test warning"),
            ],
        )
        assert result.has_errors is False
        assert result.has_warnings is True

    def test_empty_result(self) -> None:
        result = ValidationResult()
        assert result.has_errors is False
        assert result.has_warnings is False
        assert result.error_count == 0
        assert result.warning_count == 0


# ---------------------------------------------------------------------------
# ValidationIssue.format()
# ---------------------------------------------------------------------------


class TestIssueFormat:
    """Tests for ValidationIssue.format()."""

    def test_format_with_location(self) -> None:
        from fling.core.models import SourceLocation
        from fling.core.validator import ValidationIssue

        issue = ValidationIssue(
            severity=Severity.ERROR,
            message="duplicate request name 'login'",
            location=SourceLocation(file_path="test.http", start_line=5, end_line=5),
        )
        assert issue.format() == "test.http:5: error: duplicate request name 'login'"

    def test_format_without_location(self) -> None:
        from fling.core.validator import ValidationIssue

        issue = ValidationIssue(
            severity=Severity.WARNING,
            message="something odd",
        )
        assert issue.format() == "warning: something odd"


# ---------------------------------------------------------------------------
# Fixture file validation
# ---------------------------------------------------------------------------


class TestFixtureValidation:
    """Validate existing fixture files to ensure no false positives."""

    def test_simple_fixture_clean(self) -> None:
        from fling.core.validator import validate_http_file

        result = validate_http_file(FIXTURES_DIR / "simple.http")
        assert not result.has_errors

    def test_multiple_fixture_clean(self) -> None:
        from fling.core.validator import validate_http_file

        result = validate_http_file(FIXTURES_DIR / "multiple.http")
        assert not result.has_errors

    def test_chaining_fixture_no_errors(self) -> None:
        from fling.core.validator import validate_http_file

        result = validate_http_file(FIXTURES_DIR / "chaining.http")
        assert not result.has_errors


# ---------------------------------------------------------------------------
# CLI: fling validate
# ---------------------------------------------------------------------------


class TestValidateCommand:
    """Tests for the 'fling validate' CLI command."""

    def test_validate_clean_file(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.http"
        f.write_text("GET https://example.com/users\n")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(f)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_duplicate_names(self, tmp_path: Path) -> None:
        content = dedent("""\
            # @name login
            POST https://example.com/auth

            ###

            # @name login
            GET https://example.com/check
        """)
        f = tmp_path / "dup.http"
        f.write_text(content)

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(f)])
        assert result.exit_code == 1

    def test_validate_strict_promotes_warnings(self, tmp_path: Path) -> None:
        content = dedent("""\
            POST https://example.com/users

            {"name": "John"}
        """)
        f = tmp_path / "warn.http"
        f.write_text(content)

        runner = CliRunner()
        # Without --strict: warnings only → exit 0
        result = runner.invoke(main, ["validate", str(f)])
        assert result.exit_code == 0

        # With --strict: warnings become errors → exit 1
        result_strict = runner.invoke(main, ["validate", "--strict", str(f)])
        assert result_strict.exit_code == 1

    def test_validate_directory(self, tmp_path: Path) -> None:
        (tmp_path / "ok.http").write_text("GET https://example.com/a\n")
        (tmp_path / "bad.http").write_text("# @name x\nGET https://a.com\n\n###\n\n# @name x\nGET https://b.com\n")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 1
