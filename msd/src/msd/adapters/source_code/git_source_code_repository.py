"""Real git-backed adapter for ISourceCodeRepository (SRS DSM-MSD req 2.2,
13-16): shallow clone with .git stripping, pointed at the Gitea mock
(dev/gitea) for local dev instead of a Bitbucket-hosted repo.

A Makefile is only considered "found" if it also contains one of the
configured include patterns (config.ini's makefile_include_patterns), not
merely if a file named Makefile exists.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from msd.adapters.source_code.mandatory_file_catalog import (
    MAKEFILE_RELATIVE_PATH,
    get_mandatory_files,
    makefile_has_valid_include,
)
from msd.domain.acquired_file import AcquiredFile
from msd.domain.data_source import DataSourceConfig
from msd.domain.inventory import SoftwareUnitVersion
from msd.ports.source_code_repository import (
    ISourceCodeRepository,
    SourceRepoAccessError,
    SourceRepoAuthError,
    SourceRepoIntegrityError,
)

logger = logging.getLogger(__name__)

CLONE_TIMEOUT_SECONDS = 300
LS_REMOTE_TIMEOUT_SECONDS = 60

_TAG_REF_PREFIX = "refs/tags/"


def natural_version_key(version: str) -> Tuple[tuple, ...]:
    """Sort key ordering version strings by their numeric parts, so 1.0.10
    comes after 1.0.9 rather than before it as a plain string sort would.

    Digit runs compare as numbers and everything else as text; the (0, …) /
    (1, …) discriminator keeps a number from ever being compared against a
    string, so no version string can raise here however it is shaped."""
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", version)
        if part
    )


class GitSourceCodeRepository(ISourceCodeRepository):
    """Adapter cloning software unit repositories from a git server (the Gitea mock)."""

    def __init__(self, base_url: str, org: str, user: str, password: str, makefile_include_patterns: List[str]):
        self._base_url = base_url.rstrip("/")
        self._org = org
        self._user = user
        self._password = password
        self._makefile_include_patterns = makefile_include_patterns

    @classmethod
    def from_data_source_config(cls, config: DataSourceConfig, makefile_include_patterns: List[str]) -> "GitSourceCodeRepository":
        """Build a repository from a saved DataSourceConfig (req 4).

        Expects connection_address as "<base_url>/<org>" and user_info as
        "<user>:<password>" — matching dev/gitea's seeded defaults
        (http://localhost:3000/dsm-src, dsm:dsm). `makefile_include_patterns`
        (config.ini's analyzer patterns) decides which Makefiles count as found.
        """
        base_url, _, org = config.connection_address.rpartition("/")
        user, _, password = config.user_info.partition(":")
        return cls(base_url=base_url, org=org, user=user, password=password,
                   makefile_include_patterns=makefile_include_patterns)

    def _clone_url(self, unit_name: str) -> str:
        scheme, _, rest = self._base_url.partition("://")
        return f"{scheme}://{self._user}:{self._password}@{rest}/{self._org}/{unit_name}.git"

    def _run_git(self, cmd: List[str], failure_message: str, timeout: int) -> subprocess.CompletedProcess:
        """Run a git command against the remote, mapping every way it can fail
        onto the port's error types (req 16). `failure_message` describes the
        attempt ("clone 'nav_app' at '1.0.0'"), and is suffixed with git's own
        stderr on a non-zero exit."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise SourceRepoAccessError(f"Could not {failure_message}: timed out: {exc}") from exc
        except OSError as exc:
            raise SourceRepoAccessError(f"Could not {failure_message}: {exc}") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Authentication" in stderr or "401" in stderr or "403" in stderr:
                raise SourceRepoAuthError(f"Authentication failed, could not {failure_message}: {stderr}")
            raise SourceRepoAccessError(f"Could not {failure_message}: {stderr}")
        return result

    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
        clone_path = dest_dir / unit.unit_name
        cmd = ["git", "-c", "http.sslVerify=false", "clone", "--depth", "1", "--branch", unit.version, self._clone_url(unit.unit_name), str(clone_path)]

        self._run_git(
            cmd,
            f"clone '{unit.unit_name}' at '{unit.version}'",
            CLONE_TIMEOUT_SECONDS,
        )

        git_dir = clone_path / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        return self.scan_cloned_unit(unit, clone_path)

    def scan_cloned_unit(self, unit: SoftwareUnitVersion, clone_path: Path) -> List[AcquiredFile]:
        """Collect the mandatory-file records from an already-cloned unit
        directory (no network access) — used by the generate step to reuse
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
                if not makefile_has_valid_include(content.decode("utf-8", errors="replace"), self._makefile_include_patterns):
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

    def list_available_versions(self, unit_name: str) -> List[str]:
        """The unit repository's tags, newest first (req 11).

        A version is a tag here because that is how a unit's versions are
        published (see dev/gitea/seed.sh), and it is the same ref `clone_unit`
        asks for — so every version this returns is one a run can actually
        acquire."""
        result = self._run_git(
            ["git", "-c", "http.sslVerify=false", "ls-remote", "--tags", "--refs", self._clone_url(unit_name)],
            f"list the versions of '{unit_name}'",
            LS_REMOTE_TIMEOUT_SECONDS,
        )

        versions = []
        for line in result.stdout.splitlines():
            _, _, ref = line.partition("\t")
            ref = ref.strip()
            if ref.startswith(_TAG_REF_PREFIX):
                versions.append(ref[len(_TAG_REF_PREFIX):])
        versions.sort(key=natural_version_key, reverse=True)
        logger.info("versions: %s has %d published version(s)", unit_name, len(versions))
        return versions
