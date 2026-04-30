"""Version synchronization helpers for the add-on and integration manifest."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


APP_ROOT = Path(__file__).resolve().parent
ADDON_ROOT = APP_ROOT.parent
DEFAULT_ADDON_CONFIG = ADDON_ROOT / "config.yaml"
DEFAULT_INTEGRATION_MANIFEST = (
    ADDON_ROOT / "integration" / "custom_components" / "ai_scene" / "manifest.json"
)
DEFAULT_INTEGRATION_SOURCE = ADDON_ROOT / "integration" / "custom_components" / "ai_scene"

_VERSION_PATTERN = re.compile(r"^version:\s*[\"']?([^\"'\s]+)[\"']?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class VersionSyncResult:
    """Details about a version sync operation."""

    addon_version: str
    integration_version: str
    updated: bool
    addon_config_path: Path
    integration_manifest_path: Path


@dataclass(frozen=True)
class IntegrationInstallResult:
    """Details about addon-managed integration installation/update."""

    source_path: Path
    target_path: Path
    installed: bool
    version_sync: VersionSyncResult


def _read_text_if_exists(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def read_addon_version(addon_config_path: Path = DEFAULT_ADDON_CONFIG) -> str:
    """Read the add-on version from config.yaml."""

    content = _read_text_if_exists(addon_config_path)
    if content is None:
        raise FileNotFoundError(addon_config_path)
    match = _VERSION_PATTERN.search(content)
    if not match:
        raise ValueError(f"No version field found in {addon_config_path}")
    return match.group(1).strip()


def read_integration_version(integration_manifest_path: Path = DEFAULT_INTEGRATION_MANIFEST) -> str:
    """Read the Home Assistant integration version from manifest.json."""

    content = _read_text_if_exists(integration_manifest_path)
    if content is None:
        raise FileNotFoundError(integration_manifest_path)
    payload = json.loads(content)
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"No version field found in {integration_manifest_path}")
    return version.strip()


def sync_integration_manifest(
    addon_config_path: Path = DEFAULT_ADDON_CONFIG,
    integration_manifest_path: Path = DEFAULT_INTEGRATION_MANIFEST,
) -> VersionSyncResult:
    """Ensure the integration manifest version matches the add-on version.

    The add-on manifest is treated as the source of truth. If the integration
    manifest is missing, the function becomes a no-op so runtime startup in the
    container stays safe.
    """

    addon_version = read_addon_version(addon_config_path)
    if not integration_manifest_path.exists():
        return VersionSyncResult(
            addon_version=addon_version,
            integration_version=addon_version,
            updated=False,
            addon_config_path=addon_config_path,
            integration_manifest_path=integration_manifest_path,
        )

    integration_version = read_integration_version(integration_manifest_path)

    updated = False
    if integration_version != addon_version:
        payload = json.loads(integration_manifest_path.read_text(encoding="utf-8"))
        payload["version"] = addon_version
        integration_manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        updated = True
        integration_version = addon_version

    return VersionSyncResult(
        addon_version=addon_version,
        integration_version=integration_version,
        updated=updated,
        addon_config_path=addon_config_path,
        integration_manifest_path=integration_manifest_path,
    )


def ensure_integration_installed(
    ha_config_path: Path,
    addon_config_path: Path = DEFAULT_ADDON_CONFIG,
    integration_source_path: Path = DEFAULT_INTEGRATION_SOURCE,
) -> IntegrationInstallResult:
    """Install or update the bundled custom integration into HA config.

    The add-on remains the source of truth, so a user only needs to install the
    add-on. When HA_CONFIG_PATH is provided, startup copies the packaged custom
    component into <config>/custom_components/ai_scene and aligns its manifest
    version with the add-on.
    """

    if not integration_source_path.exists():
        raise FileNotFoundError(integration_source_path)

    target = ha_config_path / "custom_components" / "ai_scene"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(integration_source_path, target, dirs_exist_ok=True)
    version_sync = sync_integration_manifest(addon_config_path, target / "manifest.json")
    return IntegrationInstallResult(
        source_path=integration_source_path,
        target_path=target,
        installed=True,
        version_sync=version_sync,
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for version checks and synchronization."""

    parser = argparse.ArgumentParser(description="Sync the integration manifest version")
    parser.add_argument("--check", action="store_true", help="Only verify versions and exit non-zero on mismatch")
    parser.add_argument(
        "--addon-config",
        type=Path,
        default=DEFAULT_ADDON_CONFIG,
        help="Path to addon config.yaml",
    )
    parser.add_argument(
        "--integration-manifest",
        type=Path,
        default=DEFAULT_INTEGRATION_MANIFEST,
        help="Path to integration manifest.json",
    )
    args = parser.parse_args(argv)

    try:
        addon_version = read_addon_version(args.addon_config)
    except FileNotFoundError:
        print(f"Add-on config not found: {args.addon_config}")
        return 1

    if not args.integration_manifest.exists():
        print(f"Integration manifest not found: {args.integration_manifest}")
        return 1 if args.check else 0

    integration_version = read_integration_version(args.integration_manifest)

    if args.check:
        if addon_version != integration_version:
            print(f"Version mismatch: addon={addon_version} integration={integration_version}")
            return 1
        print(f"Versions are aligned at {addon_version}")
        return 0

    result = sync_integration_manifest(args.addon_config, args.integration_manifest)
    if result.updated:
        print(
            f"Updated integration manifest version {integration_version} -> {result.integration_version}"
        )
    else:
        print(f"Integration manifest already matches add-on version {result.addon_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
