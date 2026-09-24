"""Note CRUD. Every path is relative to the calling user's notes root."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from cloudmorrow.paths import UnsafePathError
from cloudmorrow.server.deps import get_note_store
from cloudmorrow.server.notes import (
    InvalidImageError,
    NoteConflictError,
    NoteExistsError,
    NoteNotFoundError,
    NoteStore,
)
from cloudmorrow.server.schemas import ImageOut, NoteCreate, NoteMove, NoteOut, NoteWrite

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _bad_path(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/tree")
def get_tree(
    previews: bool = Query(default=False, description="add the first lines of each note"),
    store: NoteStore = Depends(get_note_store),
) -> dict:
    return store.tree(previews=previews).to_dict()


@router.get("/search")
def search(
    q: str = Query(min_length=1), store: NoteStore = Depends(get_note_store)
) -> dict:
    return {"query": q, "results": store.search(q)}


@router.post("/img", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
async def upload_image(
    request: Request,
    filename: str = Query(default="", description="what the file was called, if anything"),
    store: NoteStore = Depends(get_note_store),
) -> ImageOut:
    """Keep a picture. The body is the image itself, not a form around it."""
    try:
        info = store.save_image(await request.body(), filename=filename)
    except InvalidImageError as exc:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "too big" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return ImageOut(**info.to_dict())


@router.get("/img/{name}")
def read_image(name: str, store: NoteStore = Depends(get_note_store)) -> Response:
    try:
        data, content_type = store.image(name)
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such image") from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc
    return Response(
        data,
        media_type=content_type,
        # The name carries the moment it arrived, so it never means another
        # picture later: the browser may keep it for as long as it likes.
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/file/{path:path}", response_model=NoteOut)
def read_note(path: str, store: NoteStore = Depends(get_note_store)) -> NoteOut:
    try:
        note = store.read(path)
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such note") from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc
    return NoteOut(**asdict(note))


@router.put("/file/{path:path}", response_model=NoteOut)
def write_note(
    path: str, payload: NoteWrite, store: NoteStore = Depends(get_note_store)
) -> NoteOut:
    try:
        note = store.write(path, payload.content, rev=payload.rev)
    except NoteConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "conflict",
                "message": "note changed on the server",
                "rev": exc.current_rev,
                "content": exc.current_content,
            },
        ) from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc
    return NoteOut(**asdict(note))


@router.post("/file", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, store: NoteStore = Depends(get_note_store)) -> NoteOut:
    try:
        note = store.create_note(payload.path, payload.content)
    except NoteExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="note already exists"
        ) from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc
    return NoteOut(**asdict(note))


@router.post("/dir", status_code=status.HTTP_201_CREATED)
def create_dir(payload: NoteCreate, store: NoteStore = Depends(get_note_store)) -> dict:
    try:
        return {"path": store.create_dir(payload.path), "is_dir": True}
    except NoteExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="folder already exists"
        ) from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc


@router.post("/move")
def move(payload: NoteMove, store: NoteStore = Depends(get_note_store)) -> dict:
    try:
        return {"path": store.move(payload.src, payload.dest)}
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such note") from exc
    except NoteExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="destination exists"
        ) from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc


@router.delete("/{path:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    path: str,
    recursive: bool = Query(default=False),
    store: NoteStore = Depends(get_note_store),
) -> None:
    try:
        store.delete(path, recursive=recursive)
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such note") from exc
    except NoteExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="folder is not empty"
        ) from exc
    except UnsafePathError as exc:
        raise _bad_path(exc) from exc
