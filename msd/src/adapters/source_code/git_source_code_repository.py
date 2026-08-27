"""Real git-backed adapter for ISourceCodeRepository (SRS DSM-MSD req 2.2,
13-16): shallow clone with .git stripping, pointed at the Gitea mock
(dev/gitea) for local dev instead of a Bitbucket-hosted repo.

A Makefile is only considered "found" if it also contains one of the
configured include patterns (msd.ini's makefile_include_patterns), not
merely if a file named Makefile exists.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List

from adapters.config import get_config
from adapters.source_code.mandatory_file_catalog import (
    MAKEFILE_RELATIVE_PATH,
    get_mandatory_files,
    makefile_has_valid_include,
)
from model.acquired_file import AcquiredFile
from model.data_source import DataSourceConfig
from model.inventory import SoftwareUnitVersion
from ports.source_code_repository import (
    ISourceCodeRepository,
    SourceRepoAccessError,
    SourceRepoAuthError,
    SourceRepoIntegrityError,
)

logger = logging.getLogger(__name__)

CLONE_TIMEOUT_SECONDS = 300


class GitSourceCodeRepository(ISourceCodeRepository):
    """Adapter cloning software unit repositories from a git server (the Gitea mock)."""

    def __init__(self, base_url: str, org: str, user: str, password: str):
        self._base_url = base_url.rstrip("/")
        self._org = org
        self._user = user
        self._password = password

    @classmethod
    def from_data_source_config(cls, config: DataSourceConfig) -> "GitSourceCodeRepository":
        """Build a repository from a saved DataSourceConfig (req 4).

        Expects connection_address as "<base_url>/<org>" and user_info as
        "<user>:<password>" — matching dev/gitea's seeded defaults
        (http://localhost:3000/dsm-src, dsm:dsm).
        """
        base_url, _, org = config.connection_address.rpartition("/")
        user, _, password = config.user_info.partition(":")
        return cls(base_url=base_url, org=org, user=user, password=password)

    def _clone_url(self, unit_name: str) -> str:
        scheme, _, rest = self._base_url.partition("://")
        return f"{scheme}://{self._user}:{self._password}@{rest}/{self._org}/{unit_name}.git"

    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
        clone_path = dest_dir / unit.unit_name
        cmd = ["git", "-c", "http.sslVerify=false", "clone", "--depth", "1", "--branch", unit.version, self._clone_url(unit.unit_name), str(clone_path)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=CLONE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise SourceRepoAccessError(f"Clone of '{unit.unit_name}' timed out: {exc}") from exc
        except OSError as exc:
            raise SourceRepoAccessError(f"Clone of '{unit.unit_name}' failed: {exc}") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Authentication" in stderr or "401" in stderr or "403" in stderr:
                raise SourceRepoAuthError(f"Authentication failed cloning '{unit.unit_name}': {stderr}")
            raise SourceRepoAccessError(f"Could not clone '{unit.unit_name}' at '{unit.version}': {stderr}")

        git_dir = clone_path / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        return self.scan_cloned_unit(unit, clone_path)

    def scan_cloned_unit(self, unit: SoftwareUnitVersion, clone_path: Path) -> List[AcquiredFile]:
        """Collect the mandatory-file records from an already-cloned unit
        directory (no network access) — used by the parse step to reuse
        previously cloned repositories."""
        acquired: List[AcquiredFile] = []
        now = datetime.now()
        for relative_path in get_mandatory_files(unit.unit_name):
            file_path = clone_path / relative_path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_bytes()
            except OSError as exc:
                raise SourceRepoIntegrityError(f"Could not read '{relative_path}' for '{unit.unit_name}': {exc}") from exc

            if relative_path == MAKEFILE_RELATIVE_PATH:
                patterns = get_config().analyzer.makefile_include_patterns
                if not makefile_has_valid_include(content.decode("utf-8", errors="replace"), patterns):
                    logger.debug("Makefile for '%s' lacks a configured include pattern; treating as not found.", unit.unit_name)
                    continue

            acquired.append(
                AcquiredFile(
                    unit_name=unit.unit_name,
                    file_name=file_path.name,
                    file_path=str(file_path),
                    package_version=unit.version,
                    updated_at=now,
                )
            )
        return acquired

    def list_mandatory_files(self, unit_name: str) -> List[str]:
        return get_mandatory_files(unit_name)
