"""Secret CRUD. Everything is scoped to the caller, a vault and an environment.

Values are never in a listing unless the caller asks for them with
`?reveal=true`: the default answer describes each secret without handing it
over. The vault is `?vault=` or the `X-Cloudmorrow-Vault` header, and the
default vault when neither is given, so the common case names nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from cloudmorrow import dotenv
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import (
    AppState,
    Scope,
    get_current_user,
    get_environment,
    get_scope,
    get_state,
)
from cloudmorrow.server.schemas import (
    EnvironmentOut,
    SecretImport,
    SecretImportOut,
    SecretOut,
    SecretWrite,
    VaultOut,
)
from cloudmorrow.server.secrets import (
    InvalidEnvironmentError,
    InvalidSecretNameError,
    InvalidVaultError,
    UnknownSecretError,
)

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _not_found(key: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no such secret: {key}")


@router.get("", response_model=list[SecretOut])
def list_secrets(
    env: str | None = Query(default=None, description="One environment; omit for all of them."),
    reveal: bool = Query(default=False, description="Include the values."),
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> list[SecretOut]:
    try:
        secrets = state.secrets.list(scope.owner, scope.vault, env, reveal=reveal)
    except InvalidEnvironmentError as exc:
        raise _bad_request(exc) from exc
    return [SecretOut(**secret.to_dict()) for secret in secrets]


@router.get("/vaults", response_model=list[VaultOut])
def list_vaults(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[VaultOut]:
    """The vaults that hold something. Not scoped: this is the list to pick from."""
    return [VaultOut(**vault.to_dict()) for vault in state.secrets.vaults(user.username)]


@router.get("/environments", response_model=list[EnvironmentOut])
def list_environments(
    state: AppState = Depends(get_state), scope: Scope = Depends(get_scope)
) -> list[EnvironmentOut]:
    return [
        EnvironmentOut(**environment.to_dict())
        for environment in state.secrets.environments(scope.owner, scope.vault)
    ]


@router.get("/export")
def export_secrets(
    environment: str = Depends(get_environment),
    format: str = Query(default="env", pattern="^(env|json)$"),
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> Response:
    """Every value in one environment, as a `.env` file or as JSON."""
    entries = state.secrets.export(scope.owner, scope.vault, environment)
    if format == "json":
        return JSONResponse(entries, headers=_no_store())
    header = (
        f"{scope.vault} · {environment}\nWritten by cloudmorrow. Keep it out of version control."
    )
    return PlainTextResponse(dotenv.dump(entries, header=header), headers=_no_store())


@router.post("/import", response_model=SecretImportOut)
def import_secrets(
    payload: SecretImport,
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> SecretImportOut:
    """Set many secrets at once — what a `.env` file turns into."""
    try:
        result = state.secrets.set_many(
            scope.owner,
            scope.vault,
            payload.environment,
            payload.entries,
            prune=payload.prune,
            overwrite=payload.overwrite,
            dry_run=payload.dry_run,
        )
    except (InvalidEnvironmentError, InvalidSecretNameError) as exc:
        raise _bad_request(exc) from exc
    return SecretImportOut(**result.to_dict())


@router.get("/item/{key}", response_model=SecretOut)
def read_secret(
    key: str,
    environment: str = Depends(get_environment),
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> SecretOut:
    """One secret, value included — the only place a single value is handed out."""
    try:
        secret = state.secrets.require(scope.owner, scope.vault, environment, key)
    except InvalidSecretNameError as exc:
        raise _bad_request(exc) from exc
    except UnknownSecretError as exc:
        raise _not_found(key) from exc
    return SecretOut(**secret.to_dict())


@router.put("/item/{key}", response_model=SecretOut)
def write_secret(
    key: str,
    payload: SecretWrite,
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> SecretOut:
    try:
        secret, _ = state.secrets.set(
            scope.owner, scope.vault, payload.environment, key, payload.value
        )
    except (InvalidEnvironmentError, InvalidSecretNameError) as exc:
        raise _bad_request(exc) from exc
    return SecretOut(**secret.to_dict())


@router.delete("/item/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret(
    key: str,
    environment: str = Depends(get_environment),
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> None:
    try:
        state.secrets.delete(scope.owner, scope.vault, environment, key)
    except InvalidSecretNameError as exc:
        raise _bad_request(exc) from exc
    except UnknownSecretError as exc:
        raise _not_found(key) from exc


@router.delete("/environment/{environment}")
def delete_environment(
    environment: str,
    state: AppState = Depends(get_state),
    scope: Scope = Depends(get_scope),
) -> dict:
    """Drop a whole environment. Returns how many secrets went with it."""
    try:
        removed = state.secrets.delete_environment(scope.owner, scope.vault, environment)
    except InvalidEnvironmentError as exc:
        raise _bad_request(exc) from exc
    return {"environment": environment, "removed": removed}


@router.delete("/vault/{vault}")
def delete_vault(
    vault: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Drop a whole vault, every environment of it. Returns how many secrets went."""
    try:
        removed = state.secrets.delete_vault(user.username, vault)
    except InvalidVaultError as exc:
        raise _bad_request(exc) from exc
    return {"vault": vault, "removed": removed}


def _no_store() -> dict[str, str]:
    """Plaintext answers are not for any cache to keep."""
    return {"Cache-Control": "no-store"}
