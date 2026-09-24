"""Boards and the tasks on them.

Tasks hang off their board in the URL, so a task can only ever be reached
through something the caller owns — there is no `/api/tasks/{id}` to guess at.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.schemas import (
    BoardCreate,
    BoardOut,
    BoardUpdate,
    TaskCreate,
    TaskMove,
    TaskOut,
    TaskUpdate,
)
from cloudmorrow.server.tasks import (
    BoardExistsError,
    InvalidLaneError,
    InvalidSlugError,
    UnknownBoardError,
    UnknownTaskError,
)

router = APIRouter(prefix="/api/boards", tags=["tasks"])


def _board_or_404(state: AppState, user: User, slug: str):
    try:
        return state.tasks.require_board(user.username, slug)
    except UnknownBoardError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such board: {slug}"
        ) from exc


def _task_or_404(state: AppState, user: User, board: str, task_id: int):
    try:
        task = state.tasks.require_task(user.username, task_id)
    except UnknownTaskError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no such task"
        ) from exc
    if task.board != board:
        # Right owner, wrong board: the URL is what says which board, so a task
        # reached through the wrong one does not exist as far as this call goes.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such task")
    return task


@router.get("", response_model=list[BoardOut])
def list_boards(
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[BoardOut]:
    return [BoardOut(**board.to_dict()) for board in state.tasks.boards(user.username)]


@router.post("", response_model=BoardOut, status_code=status.HTTP_201_CREATED)
def create_board(
    payload: BoardCreate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> BoardOut:
    try:
        board = state.tasks.create_board(
            user.username, payload.title, slug=payload.slug or ""
        )
    except BoardExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="a board with that id exists"
        ) from exc
    except (InvalidSlugError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BoardOut(**board.to_dict())


@router.patch("/{slug}", response_model=BoardOut)
def rename_board(
    slug: str,
    payload: BoardUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> BoardOut:
    _board_or_404(state, user, slug)
    try:
        board = state.tasks.rename_board(user.username, slug, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BoardOut(**board.to_dict())


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_board(
    slug: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    _board_or_404(state, user, slug)
    state.tasks.delete_board(user.username, slug)


@router.get("/{slug}/tasks", response_model=list[TaskOut])
def list_tasks(
    slug: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[TaskOut]:
    """Every task on the board — and the moment the Done lane is swept."""
    _board_or_404(state, user, slug)
    return [TaskOut(**task.to_dict()) for task in state.tasks.tasks(user.username, slug)]


@router.post("/{slug}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    slug: str,
    payload: TaskCreate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> TaskOut:
    _board_or_404(state, user, slug)
    try:
        task = state.tasks.create_task(
            user.username, slug, payload.title, body=payload.body, lane=payload.lane
        )
    except (InvalidLaneError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TaskOut(**task.to_dict())


@router.patch("/{slug}/tasks/{task_id}", response_model=TaskOut)
def edit_task(
    slug: str,
    task_id: int,
    payload: TaskUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> TaskOut:
    _board_or_404(state, user, slug)
    _task_or_404(state, user, slug, task_id)
    try:
        task = state.tasks.edit_task(
            user.username, task_id, title=payload.title, body=payload.body
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TaskOut(**task.to_dict())


@router.post("/{slug}/tasks/{task_id}/move", response_model=TaskOut)
def move_task(
    slug: str,
    task_id: int,
    payload: TaskMove,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> TaskOut:
    """Drop a task into a lane. This is what dragging a card comes down to."""
    _board_or_404(state, user, slug)
    _task_or_404(state, user, slug, task_id)
    try:
        task = state.tasks.move_task(user.username, task_id, payload.lane, payload.index)
    except InvalidLaneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TaskOut(**task.to_dict())


@router.delete("/{slug}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    slug: str,
    task_id: int,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    _board_or_404(state, user, slug)
    _task_or_404(state, user, slug, task_id)
    state.tasks.delete_task(user.username, task_id)
