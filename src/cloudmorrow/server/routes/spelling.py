"""Spelling: the languages, and whether some words are in one (server/spelling.py).

Asked by the web app's editors as somebody types — a screenful of words at
a time, the ones not asked before — and when they right-click a marked
word. What is checked is the words alone: nothing of the page they are on
is sent, and nothing is kept.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.spelling import MAX_WORDS, SpellingError, language_id

router = APIRouter(prefix="/api/spelling", tags=["spelling"])


class Languages(BaseModel):
    languages: list[dict]
    # Why nothing can be checked, when nothing can; '' otherwise.
    problem: str = ""


class CheckRequest(BaseModel):
    language: str
    words: list[str] = Field(default_factory=list, max_length=MAX_WORDS)


class Checked(BaseModel):
    wrong: list[str]


class SuggestRequest(BaseModel):
    language: str
    word: str = Field(max_length=64)


class Suggested(BaseModel):
    suggestions: list[str]


def _language(value: str) -> str:
    found = language_id(value)
    if not found:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="that is not a language")
    return found


def _refused(exc: SpellingError) -> HTTPException:
    # A dictionary that cannot be had, or an engine that is not there: not
    # the asker's doing, and nothing they can change from here.
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.get("/languages", response_model=Languages)
def languages(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> Languages:
    """The languages a document or a note can be checked in: the catalog's
    dictionaries, and the ones fetched before. `ready` says the files are
    here; the first check in a language fetches them."""
    return Languages(languages=state.spelling.languages(), problem=state.spelling.problem())


@router.post("/check", response_model=Checked)
def check(payload: CheckRequest, state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> Checked:
    """Which of these words the language does not know."""
    try:
        return Checked(wrong=state.spelling.check(_language(payload.language), payload.words))
    except SpellingError as exc:
        raise _refused(exc) from exc


@router.post("/suggest", response_model=Suggested)
def suggest(
    payload: SuggestRequest, state: AppState = Depends(get_state), _: User = Depends(get_current_user)
) -> Suggested:
    """What a word might have been."""
    try:
        return Suggested(suggestions=state.spelling.suggest(_language(payload.language), payload.word))
    except SpellingError as exc:
        raise _refused(exc) from exc
