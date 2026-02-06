"""Environment file loading and merging for fling.

Loads http-client.env.json and http-client.private.env.json from a project
directory. Supports .env files via python-dotenv. Handles the _shared concept
where variables are available in all environments.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from fling.core.models import EnvironmentFile

logger = logging.getLogger(__name__)

PUBLIC_ENV_FILENAME = "http-client.env.json"
PRIVATE_ENV_FILENAME = "http-client.private.env.json"
DOTENV_FILENAME = ".env"
SHARED_ENV_KEY = "_shared"


def load_env_json(path: Path) -> dict[str, dict[str, Any]]:
    """Load an environment JSON file and return parsed environments.

    Args:
        path: Path to the JSON environment file.

    Returns:
        Dictionary mapping environment names to their variables.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        ValueError: If the file content is not a JSON object.
    """
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)

    if not isinstance(data, dict):
        msg = f"Expected JSON object in {path}, got {type(data).__name__}"
        raise ValueError(msg)

    result: dict[str, dict[str, Any]] = {}
    for env_name, env_vars in data.items():
        if not isinstance(env_vars, dict):
            logger.warning(
                "Skipping environment '%s' in %s: expected object, got %s",
                env_name,
                path,
                type(env_vars).__name__,
            )
            continue
        result[env_name] = env_vars

    return result


def merge_environments(
    public: dict[str, dict[str, Any]],
    private: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge public and private environment definitions.

    Private values override public values per environment. Environments that
    exist only in private are also included.

    Args:
        public: Public environment variables.
        private: Private environment variables (overrides).

    Returns:
        Merged environment dictionary.
    """
    merged: dict[str, dict[str, Any]] = {}

    # Start with all public environments
    for env_name, env_vars in public.items():
        merged[env_name] = dict(env_vars)

    # Overlay private environments
    for env_name, env_vars in private.items():
        if env_name in merged:
            merged[env_name].update(env_vars)
        else:
            merged[env_name] = dict(env_vars)

    return merged


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Load a .env file and return its variables.

    Args:
        path: Path to the .env file.

    Returns:
        Dictionary of variable names to string values.
    """
    if not path.is_file():
        return {}

    raw = dotenv_values(path)
    # dotenv_values can return None values for keys without values
    return {k: v for k, v in raw.items() if v is not None}


def load_environment(
    directory: Path,
    *,
    public_filename: str = PUBLIC_ENV_FILENAME,
    private_filename: str = PRIVATE_ENV_FILENAME,
    dotenv_filename: str = DOTENV_FILENAME,
) -> EnvironmentFile:
    """Load environment configuration from a directory.

    Loads the public env file, optionally overlays the private env file,
    and optionally loads .env file variables.

    Args:
        directory: Directory to search for environment files.
        public_filename: Name of the public env file.
        private_filename: Name of the private env file.
        dotenv_filename: Name of the .env file.

    Returns:
        Loaded and merged EnvironmentFile.
    """
    directory = Path(directory)

    # Load public env
    public_path = directory / public_filename
    public: dict[str, dict[str, Any]] = {}
    if public_path.is_file():
        logger.debug("Loading public environment from %s", public_path)
        public = load_env_json(public_path)
    else:
        logger.debug("No public environment file found at %s", public_path)

    # Load private env
    private_path = directory / private_filename
    private: dict[str, dict[str, Any]] = {}
    if private_path.is_file():
        logger.debug("Loading private environment from %s", private_path)
        private = load_env_json(private_path)
    else:
        logger.debug("No private environment file found at %s", private_path)

    # Merge public + private
    merged = merge_environments(public, private)

    # Load .env file and inject as a special _dotenv key
    dotenv_path = directory / dotenv_filename
    dotenv_vars = load_dotenv_file(dotenv_path)
    if dotenv_vars:
        logger.debug("Loaded %d variables from %s", len(dotenv_vars), dotenv_path)
        merged["_dotenv"] = dotenv_vars

    return EnvironmentFile(environments=merged)


def list_environments(env_file: EnvironmentFile) -> list[str]:
    """List available environment names (excluding internal keys).

    Args:
        env_file: Loaded environment file.

    Returns:
        Sorted list of environment names.
    """
    return sorted(name for name in env_file.environments if not name.startswith("_"))


def resolve_environment(
    env_file: EnvironmentFile,
    env_name: str,
) -> dict[str, Any]:
    """Resolve variables for a specific environment.

    Merges _shared variables with the selected environment's variables.
    The selected environment's values take precedence over _shared values.

    Args:
        env_file: Loaded environment file.
        env_name: Name of the environment to resolve.

    Returns:
        Resolved variables dictionary.

    Raises:
        KeyError: If the environment name does not exist.
    """
    if env_name not in env_file.environments:
        available = list_environments(env_file)
        msg = f"Environment '{env_name}' not found. Available: {available}"
        raise KeyError(msg)

    # Start with _shared as base
    shared = env_file.environments.get(SHARED_ENV_KEY, {})
    resolved: dict[str, Any] = dict(shared)

    # Overlay selected environment
    resolved.update(env_file.environments[env_name])

    return resolved


def get_dotenv_variables(env_file: EnvironmentFile) -> dict[str, str]:
    """Get .env file variables from the environment file.

    Args:
        env_file: Loaded environment file.

    Returns:
        Dictionary of .env variables, or empty dict if none loaded.
    """
    dotenv_vars = env_file.environments.get("_dotenv", {})
    return {k: str(v) for k, v in dotenv_vars.items()}
