from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from replayt.types import LogMode

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_SECRETISH_QUERY_PARTS = ("auth", "key", "password", "secret", "sig", "signature", "token")
_REDACTION_SENTINEL = {"_redacted": True}

# Common LLM-related env vars. replayt's OpenAI-compat client reads OPENAI_API_KEY / OPENAI_BASE_URL
# / REPLAYT_*; other names are audited for presence only (never values) for compliance reviews.
# Keep this tuple sorted alphabetically so doctor/config JSON and diffs stay stable.
LLM_CREDENTIAL_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "COHERE_API_KEY",
    "DEEPSEEK_API_KEY",
    "FIREWORKS_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "MISTRAL_API_KEY",
    "OLLAMA_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "TOGETHER_API_KEY",
    "XAI_API_KEY",
)

# Proxy-related names: many HTTP stacks honor lowercase variants on POSIX; audit both without echoing values.
_EGRESS_PROXY_ENV_VARS: frozenset[str] = frozenset({"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"})
# Common env vars that steer TLS trust or HTTP proxy behavior for stacks replayt may use indirectly.
# Sorted for stable doctor/config JSON.
EGRESS_TRUST_ENV_VARS: tuple[str, ...] = (
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)


def _env_nonempty(name: str) -> bool:
    raw = os.environ.get(name)
    return raw is not None and bool(str(raw).strip())


def llm_credential_env_presence() -> list[dict[str, bool]]:
    """Return fixed-name credential env flags for machine-readable doctor/config reports."""

    return [{"name": name, "present": _env_nonempty(name)} for name in LLM_CREDENTIAL_ENV_VARS]


def egress_trust_env_presence() -> list[dict[str, bool]]:
    """Return proxy / TLS-trust env flags (presence only) for compliance-style egress reviews."""

    rows: list[dict[str, bool]] = []
    for name in EGRESS_TRUST_ENV_VARS:
        if name in _EGRESS_PROXY_ENV_VARS:
            present = _env_nonempty(name) or _env_nonempty(name.lower())
        else:
            present = _env_nonempty(name)
        rows.append({"name": name, "present": present})
    return rows


def extraneous_llm_credential_env_names() -> tuple[str, ...]:
    """Env vars from :data:`LLM_CREDENTIAL_ENV_VARS` (except OPENAI_API_KEY) that are non-empty."""

    return tuple(n for n in LLM_CREDENTIAL_ENV_VARS if n != "OPENAI_API_KEY" and _env_nonempty(n))


def _base_url_safe_label(url: str) -> str:
    """Strip userinfo and query from a URL for operator-facing messages (avoid echoing secrets)."""

    parts = urlsplit(url)
    host = parts.hostname
    if host is not None:
        netloc = f"{host}:{parts.port}" if parts.port is not None else host
    else:
        netloc = ""
    return urlunsplit((parts.scheme, netloc, parts.path or "", "", ""))


def sanitize_base_url_for_output(url: str | None) -> str | None:
    """Return a log-safe base URL label that omits userinfo and query parameters."""

    if url is None:
        return None
    raw = str(url).strip()
    if not raw:
        return raw
    return _base_url_safe_label(raw)


@dataclass(frozen=True)
class TrustBoundaryCheck:
    name: str
    ok: bool
    detail: str
    hint: str | None = None
    soft: bool = True


def normalize_name_list(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or ():
        item = str(raw).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return tuple(out)


def redact_named_fields(value: Any, *, field_names: list[str] | tuple[str, ...] | None) -> Any:
    names = {item.lower() for item in normalize_name_list(field_names)}
    if not names:
        return value
    return _redact_named_fields(value, names)


def _redact_named_fields(value: Any, field_names: set[str]) -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            key_label = str(key).strip().lower()
            if key_label in field_names:
                out[key] = dict(_REDACTION_SENTINEL)
            else:
                out[key] = _redact_named_fields(item, field_names)
        return out
    if isinstance(value, list):
        return [_redact_named_fields(item, field_names) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_named_fields(item, field_names) for item in value)
    return value


def missing_actor_fields(
    actor: dict[str, Any] | None,
    *,
    required_fields: list[str] | tuple[str, ...] | None,
) -> list[str]:
    required = normalize_name_list(required_fields)
    if not required:
        return []
    actor_lookup = {str(key).strip().lower(): value for key, value in (actor or {}).items()}
    missing: list[str] = []
    for key in required:
        value = actor_lookup.get(key.lower(), None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def approval_reason_missing(reason: str | None, *, required: bool) -> bool:
    """Return ``True`` when a required approval reason is absent or blank."""

    if not required:
        return False
    if reason is None:
        return True
    return not bool(str(reason).strip())


def _permission_bit_check(
    *,
    name: str,
    mode: int,
    mask: int,
    ok_detail: str,
    bad_detail: str,
    hint: str,
) -> TrustBoundaryCheck:
    if mode & mask:
        return TrustBoundaryCheck(name=name, ok=False, detail=bad_detail, hint=hint)
    return TrustBoundaryCheck(name=name, ok=True, detail=ok_detail)


def log_directory_permission_trust_checks(log_dir: Path | None) -> list[TrustBoundaryCheck]:
    """Soft warnings when the log directory mode is group/world-accessible (POSIX only; best-effort)."""

    if log_dir is None or os.name == "nt":
        return []
    try:
        resolved = log_dir.resolve()
        if not resolved.is_dir():
            return []
        mode = resolved.stat().st_mode
    except OSError:
        return []

    return [
        _permission_bit_check(
            name="trust_log_dir_group_readable",
            mode=mode,
            mask=stat.S_IRGRP,
            ok_detail="log_dir is not group-readable",
            bad_detail="log_dir is readable by the owning Unix group (group-readable bit)",
            hint="Strip group read on the log directory unless every account in that group is allowed to read JSONL.",
        ),
        _permission_bit_check(
            name="trust_log_dir_group_writable",
            mode=mode,
            mask=stat.S_IWGRP,
            ok_detail="log_dir is not group-writable",
            bad_detail="log_dir is writable by the owning Unix group (group-writable bit)",
            hint=(
                "Strip group write or move logs to a single-writer directory so peer accounts "
                "cannot append or tamper."
            ),
        ),
        _permission_bit_check(
            name="trust_log_dir_other_readable",
            mode=mode,
            mask=stat.S_IROTH,
            ok_detail="log_dir is not world-readable",
            bad_detail="log_dir is readable by users outside the owning user/group (world-readable bit)",
            hint="Use chmod to strip other read access, or place logs on a dedicated volume with stricter ACLs.",
        ),
        _permission_bit_check(
            name="trust_log_dir_other_writable",
            mode=mode,
            mask=stat.S_IWOTH,
            ok_detail="log_dir is not world-writable",
            bad_detail="log_dir is writable by users outside the owning user/group (world-writable bit)",
            hint="Strip other write on the log directory so unrelated accounts cannot append or tamper with JSONL.",
        ),
    ]


def dotenv_trust_candidate_paths(
    *,
    cwd: Path | None = None,
    project_config_path: Path | str | None = None,
) -> list[Path]:
    """Paths to common `.env` files for permission audits (no reads of file contents)."""

    root = Path.cwd() if cwd is None else cwd
    seen: set[str] = set()
    out: list[Path] = []
    for candidate in (root / ".env",):
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    if project_config_path is not None:
        try:
            cfg_parent = Path(project_config_path).resolve().parent
        except OSError:
            cfg_parent = Path(project_config_path).parent
        env_next = cfg_parent / ".env"
        try:
            key = str(env_next.resolve())
        except OSError:
            key = str(env_next)
        if key not in seen:
            seen.add(key)
            out.append(env_next)
    return out


def dotenv_permission_trust_checks(candidate_paths: Sequence[Path]) -> list[TrustBoundaryCheck]:
    """Soft warnings when a discovered `.env` file is group/world-readable or writable (POSIX only)."""

    if os.name == "nt":
        return []
    existing: list[Path] = []
    resolved_seen: set[str] = set()
    for raw in candidate_paths:
        try:
            p = raw.resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in resolved_seen:
            continue
        resolved_seen.add(key)
        existing.append(p)
    if not existing:
        return []

    bad_read: list[str] = []
    bad_write: list[str] = []
    bad_group_read: list[str] = []
    bad_group_write: list[str] = []
    for p in existing:
        try:
            mode = p.stat().st_mode
        except OSError:
            continue
        label = str(p)
        if mode & stat.S_IRGRP:
            bad_group_read.append(label)
        if mode & stat.S_IWGRP:
            bad_group_write.append(label)
        if mode & stat.S_IROTH:
            bad_read.append(label)
        if mode & stat.S_IWOTH:
            bad_write.append(label)

    checks: list[TrustBoundaryCheck] = []
    if bad_group_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_group_readable",
                ok=False,
                detail="group-readable .env file(s): " + ", ".join(bad_group_read),
                hint=(
                    "Use chmod 600 (or tighter) on .env files that hold API keys; "
                    "shared Unix groups should not read them unless that access is intentional."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_group_readable",
                ok=True,
                detail=f"checked {len(existing)} .env file(s); none are group-readable",
            )
        )

    if bad_group_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_group_writable",
                ok=False,
                detail="group-writable .env file(s): " + ", ".join(bad_group_write),
                hint=(
                    "Strip group write on .env so peer accounts cannot swap in attacker-controlled "
                    "or wrong-environment secrets."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_group_writable",
                ok=True,
                detail=f"checked {len(existing)} .env file(s); none are group-writable",
            )
        )

    if bad_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_readable",
                ok=False,
                detail="world-readable .env file(s): " + ", ".join(bad_read),
                hint=(
                    "Use chmod 600 (or tighter) on .env files that hold API keys; "
                    "other OS accounts should not read them."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_readable",
                ok=True,
                detail=f"checked {len(existing)} .env file(s); none are world-readable",
            )
        )

    if bad_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_writable",
                ok=False,
                detail="world-writable .env file(s): " + ", ".join(bad_write),
                hint=(
                    "Strip world write on .env so unrelated accounts cannot replace your keys "
                    "with attacker-controlled values."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_writable",
                ok=True,
                detail=f"checked {len(existing)} .env file(s); none are world-writable",
            )
        )
    return checks


def workflow_entrypoint_permission_trust_checks(candidate_paths: Sequence[Path]) -> list[TrustBoundaryCheck]:
    """Soft warnings when a workflow entry file is group/world-readable or writable (POSIX only)."""

    if os.name == "nt" or not candidate_paths:
        return []
    existing: list[Path] = []
    resolved_seen: set[str] = set()
    for raw in candidate_paths:
        try:
            p = raw.resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in resolved_seen:
            continue
        resolved_seen.add(key)
        existing.append(p)
    if not existing:
        return []

    bad_group_read: list[str] = []
    bad_group_write: list[str] = []
    bad_other_read: list[str] = []
    bad_other_write: list[str] = []
    for p in existing:
        try:
            mode = p.stat().st_mode
        except OSError:
            continue
        label = str(p)
        if mode & stat.S_IRGRP:
            bad_group_read.append(label)
        if mode & stat.S_IWGRP:
            bad_group_write.append(label)
        if mode & stat.S_IROTH:
            bad_other_read.append(label)
        if mode & stat.S_IWOTH:
            bad_other_write.append(label)

    checks: list[TrustBoundaryCheck] = []
    if bad_group_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_group_readable",
                ok=False,
                detail="group-readable workflow entry file(s): " + ", ".join(bad_group_read),
                hint=(
                    "Tighten permissions on workflow sources (for example chmod 640) unless every account "
                    "in the owning Unix group is trusted to read the code replayt executes."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_group_readable",
                ok=True,
                detail=f"checked {len(existing)} workflow entry file(s); none are group-readable",
            )
        )

    if bad_group_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_group_writable",
                ok=False,
                detail="group-writable workflow entry file(s): " + ", ".join(bad_group_write),
                hint=(
                    "Strip group write on workflow files so peer accounts cannot swap in "
                    "attacker-controlled code before the next run."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_group_writable",
                ok=True,
                detail=f"checked {len(existing)} workflow entry file(s); none are group-writable",
            )
        )

    if bad_other_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_other_readable",
                ok=False,
                detail="world-readable workflow entry file(s): " + ", ".join(bad_other_read),
                hint=(
                    "Restrict workflow file permissions so other OS accounts cannot read proprietary "
                    "or regulated logic replayt loads from disk."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_other_readable",
                ok=True,
                detail=f"checked {len(existing)} workflow entry file(s); none are world-readable",
            )
        )

    if bad_other_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_other_writable",
                ok=False,
                detail="world-writable workflow entry file(s): " + ", ".join(bad_other_write),
                hint=(
                    "Strip world write on workflow entry files so unrelated accounts cannot replace "
                    "the code path replayt executes."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_workflow_entry_other_writable",
                ok=True,
                detail=f"checked {len(existing)} workflow entry file(s); none are world-writable",
            )
        )
    return checks


def policy_hook_script_permission_trust_checks(candidate_paths: Sequence[Path]) -> list[TrustBoundaryCheck]:
    """Soft warnings when a configured policy hook script path is group/world-readable or writable (POSIX only)."""

    if os.name == "nt" or not candidate_paths:
        return []
    existing: list[Path] = []
    resolved_seen: set[str] = set()
    for raw in candidate_paths:
        try:
            p = raw.resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in resolved_seen:
            continue
        resolved_seen.add(key)
        existing.append(p)
    if not existing:
        return []

    bad_group_read: list[str] = []
    bad_group_write: list[str] = []
    bad_other_read: list[str] = []
    bad_other_write: list[str] = []
    for p in existing:
        try:
            mode = p.stat().st_mode
        except OSError:
            continue
        label = str(p)
        if mode & stat.S_IRGRP:
            bad_group_read.append(label)
        if mode & stat.S_IWGRP:
            bad_group_write.append(label)
        if mode & stat.S_IROTH:
            bad_other_read.append(label)
        if mode & stat.S_IWOTH:
            bad_other_write.append(label)

    checks: list[TrustBoundaryCheck] = []
    if bad_group_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_group_readable",
                ok=False,
                detail="group-readable policy hook script file(s): " + ", ".join(bad_group_read),
                hint=(
                    "Tighten permissions on hook scripts (for example chmod 750) unless every account "
                    "in the owning Unix group is trusted to read the code replayt invokes before runs, "
                    "exports, or resumes."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_group_readable",
                ok=True,
                detail=f"checked {len(existing)} policy hook script file(s); none are group-readable",
            )
        )

    if bad_group_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_group_writable",
                ok=False,
                detail="group-writable policy hook script file(s): " + ", ".join(bad_group_write),
                hint=(
                    "Strip group write on hook scripts so peer accounts cannot replace run_gate, export_gate, "
                    "or resume_gate logic with attacker-controlled code."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_group_writable",
                ok=True,
                detail=f"checked {len(existing)} policy hook script file(s); none are group-writable",
            )
        )

    if bad_other_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_other_readable",
                ok=False,
                detail="world-readable policy hook script file(s): " + ", ".join(bad_other_read),
                hint=(
                    "Restrict hook script permissions so other OS accounts cannot read policy logic "
                    "that gates regulated workflows."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_other_readable",
                ok=True,
                detail=f"checked {len(existing)} policy hook script file(s); none are world-readable",
            )
        )

    if bad_other_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_other_writable",
                ok=False,
                detail="world-writable policy hook script file(s): " + ", ".join(bad_other_write),
                hint=(
                    "Strip world write on policy hook scripts so unrelated accounts cannot swap in "
                    "malicious gate implementations."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_policy_hook_script_other_writable",
                ok=True,
                detail=f"checked {len(existing)} policy hook script file(s); none are world-writable",
            )
        )
    return checks


def inputs_file_permission_trust_checks(candidate_paths: Sequence[Path]) -> list[TrustBoundaryCheck]:
    """Soft warnings when a default or explicit inputs JSON file is group/world-readable or writable (POSIX only)."""

    if os.name == "nt" or not candidate_paths:
        return []
    existing: list[Path] = []
    resolved_seen: set[str] = set()
    for raw in candidate_paths:
        try:
            p = raw.resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in resolved_seen:
            continue
        resolved_seen.add(key)
        existing.append(p)
    if not existing:
        return []

    bad_group_read: list[str] = []
    bad_group_write: list[str] = []
    bad_other_read: list[str] = []
    bad_other_write: list[str] = []
    for p in existing:
        try:
            mode = p.stat().st_mode
        except OSError:
            continue
        label = str(p)
        if mode & stat.S_IRGRP:
            bad_group_read.append(label)
        if mode & stat.S_IWGRP:
            bad_group_write.append(label)
        if mode & stat.S_IROTH:
            bad_other_read.append(label)
        if mode & stat.S_IWOTH:
            bad_other_write.append(label)

    checks: list[TrustBoundaryCheck] = []
    if bad_group_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_group_readable",
                ok=False,
                detail="group-readable inputs JSON file(s): " + ", ".join(bad_group_read),
                hint=(
                    "Tighten permissions on inputs files (for example chmod 600) unless every account "
                    "in the owning Unix group may read customer or tenant fields loaded into runs."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_group_readable",
                ok=True,
                detail=f"checked {len(existing)} inputs file(s); none are group-readable",
            )
        )

    if bad_group_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_group_writable",
                ok=False,
                detail="group-writable inputs JSON file(s): " + ", ".join(bad_group_write),
                hint=(
                    "Strip group write on inputs JSON so peer accounts cannot swap in attacker-controlled "
                    "or wrong-environment payloads before the next run."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_group_writable",
                ok=True,
                detail=f"checked {len(existing)} inputs file(s); none are group-writable",
            )
        )

    if bad_other_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_other_readable",
                ok=False,
                detail="world-readable inputs JSON file(s): " + ", ".join(bad_other_read),
                hint=(
                    "Restrict inputs file permissions so other OS accounts cannot read PII or secrets "
                    "passed as workflow inputs."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_other_readable",
                ok=True,
                detail=f"checked {len(existing)} inputs file(s); none are world-readable",
            )
        )

    if bad_other_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_other_writable",
                ok=False,
                detail="world-writable inputs JSON file(s): " + ", ".join(bad_other_write),
                hint=(
                    "Strip world write on inputs JSON so unrelated accounts cannot replace run inputs "
                    "with malicious data."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_inputs_file_other_writable",
                ok=True,
                detail=f"checked {len(existing)} inputs file(s); none are world-writable",
            )
        )
    return checks


def trust_boundary_checks(*, base_url: str | None, log_mode: LogMode | str) -> list[TrustBoundaryCheck]:
    mode = log_mode.value if isinstance(log_mode, LogMode) else str(log_mode).strip().lower()
    checks: list[TrustBoundaryCheck] = []
    if mode == LogMode.full.value:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_mode",
                ok=False,
                detail="full log mode stores raw LLM request and response bodies on disk",
                hint="Prefer redacted or structured_only when prompts or outputs may contain PII or secrets.",
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_mode",
                ok=True,
                detail=f"{mode} avoids persisting raw LLM bodies",
            )
        )

    if not base_url:
        return checks

    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    is_local_http = parts.scheme == "http" and (host in _LOCAL_HOSTS or host.endswith(".localhost"))
    if parts.scheme == "https" or is_local_http:
        detail = "HTTPS" if parts.scheme == "https" else "HTTP is limited to a local host"
        checks.append(TrustBoundaryCheck(name="trust_base_url_transport", ok=True, detail=detail))
    else:
        safe = _base_url_safe_label(base_url)
        checks.append(
            TrustBoundaryCheck(
                name="trust_base_url_transport",
                ok=False,
                detail=f"{safe} uses non-local plaintext HTTP or an unrecognized scheme",
                hint="Use HTTPS for remote providers; reserve plain HTTP for localhost gateways such as Ollama.",
            )
        )

    secretish_query_keys = sorted(
        {
            key
            for key, _value in parse_qsl(parts.query, keep_blank_values=True)
            if any(part in key.lower() for part in _SECRETISH_QUERY_PARTS)
        }
    )
    embedded_parts: list[str] = []
    if parts.username or parts.password:
        embedded_parts.append("user-info credentials")
    if secretish_query_keys:
        embedded_parts.append("query params " + ", ".join(secretish_query_keys))
    if embedded_parts:
        safe = _base_url_safe_label(base_url)
        checks.append(
            TrustBoundaryCheck(
                name="trust_base_url_credentials",
                ok=False,
                detail=f"{safe} includes " + " and ".join(embedded_parts),
                hint="Move tokens into headers or env vars instead of embedding them in OPENAI_BASE_URL.",
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_base_url_credentials",
                ok=True,
                detail="No embedded credentials detected in OPENAI_BASE_URL",
            )
        )
    return checks
