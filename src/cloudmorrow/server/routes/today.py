"""The front page's one call: today's line to think on, and the weather.

Anything signed in may ask. There is nothing here that is anybody's, so
there is nothing to guard beyond the sign-in, and no feature switch: the
front page is the app's front door rather than one of its rooms.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.today import WeatherError, quote_for

router = APIRouter(prefix="/api/today", tags=["today"])


class QuoteOut(BaseModel):
    text: str
    who: str


class WeatherOut(BaseModel):
    place: str
    temperature: float | None = None
    feels_like: float | None = None
    wind_ms: float | None = None
    summary: str
    glyph: str
    is_day: bool = True
    high: float | None = None
    low: float | None = None
    rain_chance: float | None = None
    sunrise: str = ""
    sunset: str = ""
    # True when this is the last good answer rather than a fresh one.
    stale: bool = False


class TodayOut(BaseModel):
    date: str
    quote: QuoteOut
    # None with no place in the server config, and None when the lookup
    # failed — `weather_error` says which, in words the page can show.
    weather: WeatherOut | None = None
    weather_error: str = ""


@router.get("", response_model=TodayOut)
def today(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> TodayOut:
    weather = None
    error = ""
    try:
        forecast = state.weather.current()
        weather = WeatherOut(**forecast) if forecast else None
    except WeatherError as exc:
        error = str(exc)
    return TodayOut(
        date=dt.date.today().isoformat(),
        quote=QuoteOut(**quote_for()),
        weather=weather,
        weather_error=error,
    )
