"""Safely persist a local IBKR Flex credential pair in config.yaml."""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ib_common.config import load_config


_CONFIG_ERROR = "configuration could not be read or validated; repair config.yaml and retry"


def configure_flex(
    config_path: str | Path, token: str, query_id: str, force: bool = False
) -> dict:
    """Persist both Flex credentials, preserving comments and rejecting replacement."""
    if not token.strip() or not query_id.strip():
        raise ValueError("Flex token and query ID must not be blank")

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run ib-suite first-run setup before configuring Flex"
        )

    yaml = YAML(typ="rt")
    try:
        contents = path.read_text(encoding="utf-8")
        doc = yaml.load(contents)
        if doc is None:
            doc = yaml.load(f"{contents}\n{{}}\n")
    except (OSError, YAMLError):
        raise ValueError(_CONFIG_ERROR) from None

    if not isinstance(doc, Mapping):
        raise ValueError(_CONFIG_ERROR)

    flex = doc.get("flex")
    if flex is not None and not isinstance(flex, Mapping):
        raise ValueError(_CONFIG_ERROR)
    if not force and (
        flex is not None
        and (flex.get("token") is not None or flex.get("query_id") is not None)
    ):
        raise FileExistsError(
            "Flex credentials already exist; pass --force to replace both values"
        )

    if flex is None:
        doc["flex"] = {}
    doc["flex"]["token"] = token
    doc["flex"]["query_id"] = query_id

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            yaml.dump(doc, file)

        config = load_config(temporary_path)
        if config.flex.token != token or config.flex.query_id != query_id:
            raise ValueError("staged Flex credentials did not reload exactly")
        os.replace(temporary_path, path)
        temporary_path = None
    except Exception:
        raise ValueError(_CONFIG_ERROR) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {"config": str(path), "ready": True}


def main() -> None:
    """Parse local configuration arguments and print the public setup result."""
    parser = argparse.ArgumentParser(
        description="Persist local IBKR Flex credentials for the read-only trade-history skill"
    )
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument("--token", required=True, help="IBKR Flex token")
    parser.add_argument("--query-id", required=True, help="IBKR Flex Query ID")
    parser.add_argument(
        "--force", action="store_true", help="replace an existing Flex credential pair"
    )
    args = parser.parse_args()
    try:
        result = configure_flex(args.config, args.token, args.query_id, args.force)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
