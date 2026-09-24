"""Agent enrolment, the job queue, and the endpoints agents themselves call."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from cloudmorrow.server.agents import (
    Agent,
    AgentExistsError,
    EnrollmentError,
    InvalidAgentNameError,
    UnknownAgentError,
    UnknownJobError,
)
from cloudmorrow.server.configsync import UnknownBundleError, validate_bundle
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import (
    AppState,
    get_current_agent,
    get_current_user,
    get_state,
)
from cloudmorrow.server.schemas import (
    AgentOut,
    AgentSyncUpdate,
    CredentialsCheck,
    CredentialsOut,
    EnrollRequest,
    EnrollResponse,
    EnrollSelfRequest,
    EnrollTokenRequest,
    EnrollTokenResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatShare,
    JobCreate,
    JobOut,
    JobResult,
)

# What an agent is allowed to be asked to do. The agent enforces this too, and
# refuses anything it was not configured to allow.
KNOWN_JOB_TYPES = {"ping", "sysinfo", "backup", "shell"}

router = APIRouter(prefix="/api/agents", tags=["agents"])
agent_router = APIRouter(prefix="/api/agent", tags=["agent"])


# -- operator-facing ---------------------------------------------------------
@router.post("/enroll-token", response_model=EnrollTokenResponse)
def create_enroll_token(
    payload: EnrollTokenRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> EnrollTokenResponse:
    """Mint a single-use token for installing an agent on a machine."""
    token, expires_at = state.agents.create_enrollment_token(
        user.username, label=payload.label, ttl_minutes=payload.ttl_minutes
    )
    return EnrollTokenResponse(enrollment_token=token, expires_at=expires_at)


@router.post("/enroll-self", response_model=EnrollResponse)
def enroll_self(
    payload: EnrollSelfRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> EnrollResponse:
    """Enrol the machine the caller is signed in from.

    This is the path the client takes at login, so that having an agent is not
    something anyone has to think about. Re-enrolling rotates the token.
    """
    try:
        agent, token = state.agents.enroll_for_user(
            user.username,
            name=payload.name,
            hostname=payload.hostname,
            platform=payload.platform,
            version=payload.version,
            capabilities=payload.capabilities,
        )
    except InvalidAgentNameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return EnrollResponse(agent_id=agent.id, name=agent.name, agent_token=token)


@router.get("", response_model=list[AgentOut])
def list_agents(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[AgentOut]:
    return [AgentOut(**agent.to_dict()) for agent in state.agents.list(user.username)]


@router.patch("/{agent_id}/sync", response_model=AgentOut)
def set_agent_sync(
    agent_id: int,
    payload: AgentSyncUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> AgentOut:
    """Turn config syncing on or off for one machine.

    The machine itself is not asked: it finds out on its next heartbeat, which
    is what makes the tick in the TUI feel like it did something.
    """
    try:
        bundles = [validate_bundle(name) for name in payload.sync_bundles]
    except UnknownBundleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"no such config bundle: {exc}"
        ) from exc
    try:
        agent = state.agents.set_sync_bundles(user.username, agent_id, bundles)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such agent") from exc
    return AgentOut(**agent.to_dict())


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: int,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    try:
        state.agents.delete(user.username, agent_id)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such agent") from exc
    # The shares it served went with it; there is no machine to serve them.
    state.shares.forget_agent(agent_id)


@router.post("/{agent_id}/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    agent_id: int,
    payload: JobCreate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Queue work for a machine."""
    if payload.type not in KNOWN_JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown job type: {payload.type}",
        )
    try:
        state.agents.require(user.username, agent_id)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such agent") from exc
    job = state.jobs.create(agent_id, user.username, payload.type, payload.payload)
    return JobOut(**job.to_dict())


@router.get("/{agent_id}/jobs", response_model=list[JobOut])
def list_jobs(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[JobOut]:
    jobs = state.jobs.list_for_agent(user.username, agent_id, limit=limit)
    return [JobOut(**job.to_dict()) for job in jobs]


# -- agent-facing ------------------------------------------------------------
@agent_router.post("/enroll", response_model=EnrollResponse)
def enroll(payload: EnrollRequest, state: AppState = Depends(get_state)) -> EnrollResponse:
    """Trade a single-use enrolment token for a long-lived agent token."""
    try:
        agent, token = state.agents.enroll(
            payload.enrollment_token,
            name=payload.name,
            hostname=payload.hostname,
            platform=payload.platform,
            version=payload.version,
            capabilities=payload.capabilities,
        )
    except EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AgentExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an agent with that name is already enrolled",
        ) from exc
    except InvalidAgentNameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return EnrollResponse(agent_id=agent.id, name=agent.name, agent_token=token)


@agent_router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    payload: HeartbeatRequest,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> HeartbeatResponse:
    state.agents.touch(
        agent.id,
        hostname=payload.hostname,
        platform=payload.platform,
        version=payload.version,
        capabilities=payload.capabilities,
        dav_base=payload.dav_base,
    )
    state.jobs.reap_stale()
    return HeartbeatResponse(
        agent_id=agent.id,
        queued_jobs=state.jobs.queued_count(agent.id),
        # Only bundles the machine says it can handle. Ticking the box for a
        # machine that has since stopped being an Omarchy box does nothing.
        sync_bundles=[
            bundle
            for bundle in agent.sync_bundles
            if bundle in (payload.capabilities or agent.capabilities)
        ],
        shares=[
            HeartbeatShare(name=share.name, path=str(share.path))
            for share in state.shares.on_agent(agent.id)
        ],
    )


@agent_router.post("/credentials", response_model=CredentialsOut)
def check_credentials(
    payload: CredentialsCheck,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> CredentialsOut:
    """Is this a good username and password for a mount of a machine share?

    An agent serving a share has no way to check a password or a token of
    its own — the hashes and the signing key are here — so it asks. Only
    the agent's owner may mount what it serves: a machine share is one
    person's disk, for that person's other machines.
    """
    if payload.username.strip().lower() != agent.owner.lower():
        return CredentialsOut(valid=False)
    return CredentialsOut(valid=state.credential_check(payload.username, payload.password))


@agent_router.post("/jobs/claim", response_model=JobOut | None)
def claim_job(
    state: AppState = Depends(get_state), agent: Agent = Depends(get_current_agent)
) -> JobOut | None:
    """Take the next queued job, or get null when there is nothing to do."""
    state.agents.touch(agent.id)
    job = state.jobs.claim_next(agent.id)
    return JobOut(**job.to_dict()) if job else None


@agent_router.post("/jobs/{job_id}/result", response_model=JobOut)
def report_result(
    job_id: int,
    payload: JobResult,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> JobOut:
    try:
        job = state.jobs.finish(
            agent.id, job_id, status=payload.status, result=payload.result
        )
    except UnknownJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no such job for this agent"
        ) from exc
    return JobOut(**job.to_dict())
