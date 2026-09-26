"""The front page's call: a line for the day, and the weather for the configured place."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server import today
from cloudmorrow.server.app import create_app
from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.today import QUOTES, Weather, WeatherError, quote_for
from tests.conftest import ADMIN, token_for

GEOCODE = {
    "results": [{"name": "Copenhagen", "country": "Denmark", "latitude": 55.68, "longitude": 12.57}]
}
FORECAST = {
    "current": {
        "temperature_2m": 14.3,
        "apparent_temperature": 12.1,
        "weather_code": 61,
        "wind_speed_10m": 5.2,
        "is_day": 1,
    },
    "daily": {
        "temperature_2m_max": [16.0],
        "temperature_2m_min": [9.5],
        "precipitation_probability_max": [70],
        "sunrise": ["2026-09-20T06:58"],
        "sunset": ["2026-09-20T19:14"],
    },
}


@pytest.fixture()
def calls(monkeypatch):
    """Every URL `fetch_json` was asked for, answered from the two fixtures."""
    asked: list[str] = []

    def fake(url: str) -> dict:
        asked.append(url)
        return GEOCODE if url.startswith(today.GEOCODE_URL) else FORECAST

    monkeypatch.setattr(today, "fetch_json", fake)
    return asked


# -- the quote --------------------------------------------------------------------------
def test_the_quote_is_the_days_and_everybody_gets_the_same_one():
    day = dt.date(2026, 9, 20)
    assert quote_for(day) == quote_for(day)
    assert quote_for(day) != quote_for(day + dt.timedelta(days=1))
    # A year of days is a year of different lines.
    seen = {quote_for(day + dt.timedelta(days=n))["text"] for n in range(len(QUOTES))}
    assert len(seen) == len(QUOTES)


def test_every_quote_says_something_and_who_said_it():
    for text, who in QUOTES:
        assert text.strip() and who.strip()
        assert len(text) < 240, text


# -- the weather ----------------------------------------------------------------------------
def test_a_named_place_is_looked_up_once_and_the_forecast_kept(calls):
    weather = Weather("Copenhagen")
    first = weather.current()
    assert first["place"] == "Copenhagen, Denmark"
    assert first["temperature"] == 14.3
    assert first["summary"] == "Light rain"
    assert first["glyph"] == "rain"
    assert first["high"] == 16.0 and first["low"] == 9.5
    assert first["rain_chance"] == 70
    assert first["sunrise"] == "06:58" and first["sunset"] == "19:14"
    assert first["stale"] is False
    assert len(calls) == 2  # the lookup, and the forecast
    assert weather.current() is first
    assert len(calls) == 2  # ten minutes have not passed


def test_coordinates_are_taken_as_given(calls):
    Weather("55.68, 12.57").current()
    assert len(calls) == 1
    assert calls[0].startswith(today.FORECAST_URL)
    assert "latitude=55.68" in calls[0]


def test_no_place_means_no_weather_and_no_call(calls):
    assert Weather("").current() is None
    assert Weather("   ").current() is None
    assert calls == []


def test_a_failure_after_a_success_hands_out_the_last_answer_marked_stale(monkeypatch, calls):
    weather = Weather("Copenhagen")
    weather.current()
    weather._fetched = 0.0  # ten minutes pass

    def down(url: str) -> dict:
        raise WeatherError("could not reach api.open-meteo.com")

    monkeypatch.setattr(today, "fetch_json", down)
    again = weather.current()
    assert again["temperature"] == 14.3
    assert again["stale"] is True


def test_a_failure_with_nothing_to_fall_back_on_raises(monkeypatch):
    def down(url: str) -> dict:
        raise WeatherError("could not reach geocoding-api.open-meteo.com")

    monkeypatch.setattr(today, "fetch_json", down)
    with pytest.raises(WeatherError):
        Weather("Copenhagen").current()


def test_an_unknown_place_is_said_so(monkeypatch):
    monkeypatch.setattr(today, "fetch_json", lambda url: {"results": []})
    with pytest.raises(WeatherError, match="no place called"):
        Weather("Nowhere-on-Sea").current()


def test_the_night_gets_a_moon():
    assert today.describe(0, is_day=True) == ("Clear", "sun")
    assert today.describe(0, is_day=False) == ("Clear", "moon")
    assert today.describe(2, is_day=False) == ("Partly cloudy", "part-moon")
    assert today.describe(95) == ("Thunderstorm", "storm")
    assert today.describe(1234) == ("Unsettled", "cloud")


# -- the call ------------------------------------------------------------------------------------
def test_today_needs_a_sign_in(client):
    assert client.get("/api/today").status_code == 401


def test_today_without_a_place_has_the_quote_and_no_weather(client, auth):
    body = client.get("/api/today", headers=auth).json()
    assert body["date"] == dt.date.today().isoformat()
    assert body["quote"] == quote_for()
    assert body["weather"] is None
    assert body["weather_error"] == ""


def test_today_with_a_place_has_the_weather(tmp_path, users, calls):
    config = ServerConfig(
        notes_dir=tmp_path / "notes",
        data_dir=tmp_path / "data",
        secret_key="test-signing-key-that-is-long-enough-for-hs256",
        weather_place="Copenhagen",
    )
    client = TestClient(create_app(config))
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    body = client.get("/api/today", headers=auth).json()
    assert body["weather"]["place"] == "Copenhagen, Denmark"
    assert body["weather"]["glyph"] == "rain"
    assert body["weather_error"] == ""


def test_today_says_when_the_weather_could_not_be_had(tmp_path, users, monkeypatch):
    monkeypatch.setattr(
        today, "fetch_json", lambda url: (_ for _ in ()).throw(WeatherError("could not reach it"))
    )
    config = ServerConfig(
        notes_dir=tmp_path / "notes",
        data_dir=tmp_path / "data",
        secret_key="test-signing-key-that-is-long-enough-for-hs256",
        weather_place="Copenhagen",
    )
    client = TestClient(create_app(config))
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    body = client.get("/api/today", headers=auth).json()
    assert body["weather"] is None
    assert body["weather_error"] == "could not reach it"


def test_weather_place_is_read_from_toml_and_the_environment(tmp_path, monkeypatch):
    from cloudmorrow.server.config import load_config

    path = tmp_path / "server.toml"
    path.write_text('[server]\nweather_place = "Aarhus"\n')
    assert load_config(path).weather_place == "Aarhus"
    monkeypatch.setenv("CLOUDMORROW_WEATHER_PLACE", "55.68,12.57")
    assert load_config(path).weather_place == "55.68,12.57"
