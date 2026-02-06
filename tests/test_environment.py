"""Tests for environment file loading and merging."""

import json
from pathlib import Path

import pytest

from fling.core.environment import (
    get_dotenv_variables,
    list_environments,
    load_dotenv_file,
    load_env_json,
    load_environment,
    merge_environments,
    resolve_environment,
)
from fling.core.models import EnvironmentFile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env_dir(fixtures_dir: Path) -> Path:
    """Full environment directory with public + private env files."""
    return fixtures_dir / "env_full"


@pytest.fixture
def env_private_only_dir(fixtures_dir: Path) -> Path:
    """Directory with only a private env file."""
    return fixtures_dir / "env_private_only"


@pytest.fixture
def env_dotenv_dir(fixtures_dir: Path) -> Path:
    """Directory with env JSON and .env file."""
    return fixtures_dir / "env_dotenv"


@pytest.fixture
def env_invalid_dir(fixtures_dir: Path) -> Path:
    """Directory with invalid JSON env file."""
    return fixtures_dir / "env_invalid"


@pytest.fixture
def env_shared_only_dir(fixtures_dir: Path) -> Path:
    """Directory with only _shared environment."""
    return fixtures_dir / "env_shared_only"


@pytest.fixture
def env_empty_dir(fixtures_dir: Path) -> Path:
    """Empty directory with no env files."""
    return fixtures_dir / "env_empty"


# ---------------------------------------------------------------------------
# load_env_json
# ---------------------------------------------------------------------------


class TestLoadEnvJson:
    """Tests for load_env_json."""

    def test_load_public_env(self, env_dir: Path) -> None:
        result = load_env_json(env_dir / "http-client.env.json")
        assert "_shared" in result
        assert "development" in result
        assert "production" in result
        assert "staging" in result

    def test_load_public_env_values(self, env_dir: Path) -> None:
        result = load_env_json(env_dir / "http-client.env.json")
        assert result["_shared"]["baseUrl"] == "https://api.example.com"
        assert result["_shared"]["apiVersion"] == "v2"
        assert result["development"]["token"] == "dev-token-123"
        assert result["development"]["debug"] is True
        assert result["production"]["debug"] is False

    def test_load_private_env(self, env_dir: Path) -> None:
        result = load_env_json(env_dir / "http-client.private.env.json")
        assert "development" in result
        assert "production" in result
        assert result["development"]["token"] == "real-dev-secret-token"
        assert result["development"]["secretKey"] == "dev-secret-key"

    def test_file_not_found(self, env_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_env_json(env_dir / "nonexistent.json")

    def test_invalid_json(self, env_invalid_dir: Path) -> None:
        with pytest.raises(json.JSONDecodeError):
            load_env_json(env_invalid_dir / "http-client.env.json")

    def test_non_object_root(self, tmp_path: Path) -> None:
        path = tmp_path / "env.json"
        path.write_text('["not", "an", "object"]')
        with pytest.raises(ValueError, match="Expected JSON object"):
            load_env_json(path)

    def test_non_object_env_skipped(self, tmp_path: Path) -> None:
        """Non-dict environment entries are skipped with a warning."""
        path = tmp_path / "env.json"
        path.write_text('{"good": {"key": "val"}, "bad": "not-a-dict"}')
        result = load_env_json(path)
        assert "good" in result
        assert "bad" not in result


# ---------------------------------------------------------------------------
# merge_environments
# ---------------------------------------------------------------------------


class TestMergeEnvironments:
    """Tests for merge_environments."""

    def test_merge_private_overrides_public(self) -> None:
        public = {"dev": {"token": "public-token", "host": "localhost"}}
        private = {"dev": {"token": "secret-token"}}
        merged = merge_environments(public, private)
        assert merged["dev"]["token"] == "secret-token"
        assert merged["dev"]["host"] == "localhost"

    def test_merge_private_adds_new_keys(self) -> None:
        public = {"dev": {"host": "localhost"}}
        private = {"dev": {"secret": "my-secret"}}
        merged = merge_environments(public, private)
        assert merged["dev"]["host"] == "localhost"
        assert merged["dev"]["secret"] == "my-secret"

    def test_merge_private_adds_new_environment(self) -> None:
        public = {"dev": {"host": "localhost"}}
        private = {"staging": {"host": "staging.example.com"}}
        merged = merge_environments(public, private)
        assert "dev" in merged
        assert "staging" in merged

    def test_merge_empty_public(self) -> None:
        public: dict = {}
        private = {"dev": {"token": "secret"}}
        merged = merge_environments(public, private)
        assert merged["dev"]["token"] == "secret"

    def test_merge_empty_private(self) -> None:
        public = {"dev": {"token": "public"}}
        private: dict = {}
        merged = merge_environments(public, private)
        assert merged["dev"]["token"] == "public"

    def test_merge_both_empty(self) -> None:
        merged = merge_environments({}, {})
        assert merged == {}

    def test_merge_preserves_shared(self) -> None:
        public = {"_shared": {"baseUrl": "https://api.example.com"}, "dev": {"token": "t"}}
        private = {"_shared": {"apiKey": "key123"}}
        merged = merge_environments(public, private)
        assert merged["_shared"]["baseUrl"] == "https://api.example.com"
        assert merged["_shared"]["apiKey"] == "key123"


# ---------------------------------------------------------------------------
# load_dotenv_file
# ---------------------------------------------------------------------------


class TestLoadDotenvFile:
    """Tests for load_dotenv_file."""

    def test_load_dotenv(self, env_dotenv_dir: Path) -> None:
        result = load_dotenv_file(env_dotenv_dir / ".env")
        assert result["API_KEY"] == "dotenv-api-key-123"
        assert result["DATABASE_URL"] == "postgresql://localhost:5432/mydb"
        assert result["DEBUG"] == "true"

    def test_missing_dotenv_returns_empty(self, tmp_path: Path) -> None:
        result = load_dotenv_file(tmp_path / ".env")
        assert result == {}

    def test_dotenv_filters_none_values(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"
        path.write_text("HAS_VALUE=yes\nNO_VALUE")
        result = load_dotenv_file(path)
        assert result.get("HAS_VALUE") == "yes"
        assert "NO_VALUE" not in result


# ---------------------------------------------------------------------------
# load_environment (integration)
# ---------------------------------------------------------------------------


class TestLoadEnvironment:
    """Tests for load_environment."""

    def test_load_full_environment(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        assert isinstance(env, EnvironmentFile)
        assert "_shared" in env.environments
        assert "development" in env.environments
        assert "production" in env.environments
        assert "staging" in env.environments

    def test_private_overrides_applied(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        # Private overrode the public token
        assert env.environments["development"]["token"] == "real-dev-secret-token"
        # Private added secretKey
        assert env.environments["development"]["secretKey"] == "dev-secret-key"
        # Public-only values preserved
        assert env.environments["development"]["debug"] is True

    def test_staging_not_in_private(self, env_dir: Path) -> None:
        """Staging only exists in public, should be unchanged."""
        env = load_environment(env_dir)
        assert env.environments["staging"]["token"] == "staging-token-789"

    def test_no_public_file(self, env_private_only_dir: Path) -> None:
        env = load_environment(env_private_only_dir)
        assert "development" in env.environments
        assert env.environments["development"]["token"] == "private-only-token"

    def test_no_files_at_all(self, env_empty_dir: Path) -> None:
        env = load_environment(env_empty_dir)
        assert env.environments == {}

    def test_dotenv_loaded(self, env_dotenv_dir: Path) -> None:
        env = load_environment(env_dotenv_dir)
        assert "_dotenv" in env.environments
        assert env.environments["_dotenv"]["API_KEY"] == "dotenv-api-key-123"

    def test_no_dotenv_no_key(self, env_dir: Path) -> None:
        """When there's no .env file, _dotenv should not appear."""
        env = load_environment(env_dir)
        assert "_dotenv" not in env.environments

    def test_shared_only(self, env_shared_only_dir: Path) -> None:
        env = load_environment(env_shared_only_dir)
        assert "_shared" in env.environments
        assert env.environments["_shared"]["baseUrl"] == "https://api.example.com"


# ---------------------------------------------------------------------------
# list_environments
# ---------------------------------------------------------------------------


class TestListEnvironments:
    """Tests for list_environments."""

    def test_list_excludes_internal_keys(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        names = list_environments(env)
        assert "_shared" not in names
        assert "_dotenv" not in names

    def test_list_sorted(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        names = list_environments(env)
        assert names == ["development", "production", "staging"]

    def test_list_empty(self) -> None:
        env = EnvironmentFile(environments={})
        names = list_environments(env)
        assert names == []

    def test_list_with_only_shared(self, env_shared_only_dir: Path) -> None:
        env = load_environment(env_shared_only_dir)
        names = list_environments(env)
        assert names == []


# ---------------------------------------------------------------------------
# resolve_environment
# ---------------------------------------------------------------------------


class TestResolveEnvironment:
    """Tests for resolve_environment."""

    def test_resolve_merges_shared(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        resolved = resolve_environment(env, "staging")
        # _shared provides apiVersion
        assert resolved["apiVersion"] == "v2"
        # staging overrides baseUrl
        assert resolved["baseUrl"] == "https://staging.api.example.com"
        assert resolved["token"] == "staging-token-789"

    def test_resolve_env_overrides_shared(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        resolved = resolve_environment(env, "development")
        # development overrides _shared baseUrl
        assert resolved["baseUrl"] == "https://dev.api.example.com"
        # _shared apiVersion still present
        assert resolved["apiVersion"] == "v2"

    def test_resolve_includes_private_overrides(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        resolved = resolve_environment(env, "development")
        assert resolved["token"] == "real-dev-secret-token"
        assert resolved["secretKey"] == "dev-secret-key"

    def test_resolve_nonexistent_env(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        with pytest.raises(KeyError, match="not found"):
            resolve_environment(env, "nonexistent")

    def test_resolve_error_lists_available(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        with pytest.raises(KeyError, match="development"):
            resolve_environment(env, "nonexistent")

    def test_resolve_no_shared(self) -> None:
        """When there's no _shared, only env-specific vars returned."""
        env = EnvironmentFile(environments={"dev": {"token": "t123"}})
        resolved = resolve_environment(env, "dev")
        assert resolved == {"token": "t123"}

    def test_resolve_preserves_non_string_values(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        resolved = resolve_environment(env, "development")
        assert resolved["debug"] is True

    def test_resolve_production(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        resolved = resolve_environment(env, "production")
        assert resolved["baseUrl"] == "https://prod.api.example.com"
        assert resolved["token"] == "real-prod-secret-token"
        assert resolved["debug"] is False
        assert resolved["apiVersion"] == "v2"


# ---------------------------------------------------------------------------
# get_dotenv_variables
# ---------------------------------------------------------------------------


class TestGetDotenvVariables:
    """Tests for get_dotenv_variables."""

    def test_get_dotenv_vars(self, env_dotenv_dir: Path) -> None:
        env = load_environment(env_dotenv_dir)
        dotenv_vars = get_dotenv_variables(env)
        assert dotenv_vars["API_KEY"] == "dotenv-api-key-123"
        assert dotenv_vars["DATABASE_URL"] == "postgresql://localhost:5432/mydb"

    def test_get_dotenv_empty_when_no_dotenv(self, env_dir: Path) -> None:
        env = load_environment(env_dir)
        dotenv_vars = get_dotenv_variables(env)
        assert dotenv_vars == {}

    def test_get_dotenv_values_are_strings(self, env_dotenv_dir: Path) -> None:
        env = load_environment(env_dotenv_dir)
        dotenv_vars = get_dotenv_variables(env)
        for value in dotenv_vars.values():
            assert isinstance(value, str)
