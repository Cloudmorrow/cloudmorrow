"""What the app's front page says about today: the weather, and a line to think on.

Two small things that are not anybody's data, so they live here rather than
in a store. The quote is picked from the list below by the day, so everybody
on the server reads the same one and tomorrow's is different. The weather is
Open-Meteo's, which needs no key and no account: the place in the server
config is looked up once, and the forecast for it is kept for ten minutes so
a page opened twenty times in a morning asks the internet twice.

The time is not here. A clock the server told you would be the server's
clock, and the phone already has the right one.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# -- a line to think on -----------------------------------------------------------
# (what was said, who said it). Chosen for the second thought they leave
# behind rather than for cheer; a front page that only ever says "you can
# do it" is wallpaper by Wednesday.
QUOTES: tuple[tuple[str, str], ...] = (
    ("The unexamined life is not worth living.", "Socrates"),
    ("We are what we repeatedly do. Excellence, then, is not an act, but a habit.", "Will Durant, on Aristotle"),
    ("It is the mark of an educated mind to be able to entertain a thought without accepting it.", "attributed to Aristotle"),
    ("It is not that we have a short time to live, but that we waste a lot of it.", "Seneca"),
    ("We suffer more often in imagination than in reality.", "Seneca"),
    ("Begin at once to live, and count each separate day as a separate life.", "Seneca"),
    ("Luck is what happens when preparation meets opportunity.", "Seneca"),
    ("You have power over your mind, not outside events. Realize this, and you will find strength.", "Marcus Aurelius"),
    ("Waste no more time arguing about what a good man should be. Be one.", "Marcus Aurelius"),
    ("The impediment to action advances action. What stands in the way becomes the way.", "Marcus Aurelius"),
    ("Very little is needed to make a happy life; it is all within yourself, in your way of thinking.", "Marcus Aurelius"),
    ("It's not what happens to you, but how you react to it that matters.", "Epictetus"),
    ("First say to yourself what you would be; and then do what you have to do.", "Epictetus"),
    ("Wealth consists not in having great possessions, but in having few wants.", "Epictetus"),
    ("No man ever steps in the same river twice, for it is not the same river and he is not the same man.", "Heraclitus"),
    ("Character is destiny.", "Heraclitus"),
    ("Much learning does not teach understanding.", "Heraclitus"),
    ("The mind is not a vessel to be filled, but a fire to be kindled.", "Plutarch"),
    ("Wonder is the beginning of wisdom.", "attributed to Socrates"),
    ("The whole problem with the world is that fools and fanatics are always so certain of themselves, and wiser people so full of doubts.", "Bertrand Russell"),
    ("He who has a why to live for can bear almost any how.", "Friedrich Nietzsche"),
    ("There are no facts, only interpretations.", "Friedrich Nietzsche"),
    ("If you gaze long into an abyss, the abyss also gazes into you.", "Friedrich Nietzsche"),
    ("Become who you are.", "Friedrich Nietzsche, after Pindar"),
    ("Between stimulus and response there is a space. In that space is our power to choose our response.", "Viktor Frankl"),
    ("What we know is a drop, what we don't know is an ocean.", "Isaac Newton"),
    ("If I have seen further, it is by standing on the shoulders of giants.", "Isaac Newton"),
    ("The first principle is that you must not fool yourself, and you are the easiest person to fool.", "Richard Feynman"),
    ("Everything should be made as simple as possible, but not simpler.", "attributed to Albert Einstein"),
    ("The important thing is not to stop questioning. Curiosity has its own reason for existing.", "Albert Einstein"),
    ("Imagination is more important than knowledge.", "Albert Einstein"),
    ("Doubt is not a pleasant condition, but certainty is absurd.", "Voltaire"),
    ("The greatest enemy of knowledge is not ignorance, it is the illusion of knowledge.", "attributed to Daniel J. Boorstin"),
    ("Not everything that counts can be counted, and not everything that can be counted counts.", "William Bruce Cameron"),
    ("A ship in harbor is safe, but that is not what ships are built for.", "John A. Shedd"),
    ("The best time to plant a tree was twenty years ago. The second best time is now.", "proverb"),
    ("How we spend our days is, of course, how we spend our lives.", "Annie Dillard"),
    ("Tell me, what is it you plan to do with your one wild and precious life?", "Mary Oliver"),
    ("We do not see things as they are, we see them as we are.", "Anaïs Nin"),
    ("The cave you fear to enter holds the treasure you seek.", "Joseph Campbell"),
    ("Out of the crooked timber of humanity, no straight thing was ever made.", "Immanuel Kant"),
    ("Man is condemned to be free; because once thrown into the world, he is responsible for everything he does.", "Jean-Paul Sartre"),
    ("Life can only be understood backwards; but it must be lived forwards.", "Søren Kierkegaard"),
    ("Anxiety is the dizziness of freedom.", "Søren Kierkegaard"),
    ("The limits of my language mean the limits of my world.", "Ludwig Wittgenstein"),
    ("It is the province of knowledge to speak, and it is the privilege of wisdom to listen.", "Oliver Wendell Holmes Sr."),
    ("Be kind, for everyone you meet is fighting a hard battle.", "attributed to Ian Maclaren"),
    ("Injustice anywhere is a threat to justice everywhere.", "Martin Luther King Jr."),
    ("The arc of the moral universe is long, but it bends toward justice.", "Martin Luther King Jr., after Theodore Parker"),
    ("Those who cannot remember the past are condemned to repeat it.", "George Santayana"),
    ("Power tends to corrupt, and absolute power corrupts absolutely.", "Lord Acton"),
    ("The price of anything is the amount of life you exchange for it.", "attributed to Henry David Thoreau"),
    ("I went to the woods because I wished to live deliberately.", "Henry David Thoreau"),
    ("Our life is frittered away by detail. Simplify, simplify.", "Henry David Thoreau"),
    ("The question is not what you look at, but what you see.", "Henry David Thoreau"),
    ("As if you could kill time without injuring eternity.", "Henry David Thoreau"),
    ("A foolish consistency is the hobgoblin of little minds.", "Ralph Waldo Emerson"),
    ("Adopt the pace of nature: her secret is patience.", "Ralph Waldo Emerson"),
    ("It is not length of life, but depth of life.", "Ralph Waldo Emerson"),
    ("Do I contradict myself? Very well then I contradict myself, I am large, I contain multitudes.", "Walt Whitman"),
    ("The world breaks everyone, and afterward, some are strong at the broken places.", "Ernest Hemingway"),
    ("Try again. Fail again. Fail better.", "Samuel Beckett"),
    ("The mystery of life isn't a problem to solve, but a reality to experience.", "Frank Herbert"),
    ("Fear is the mind-killer.", "Frank Herbert"),
    ("The opposite of a correct statement is a false statement. But the opposite of a profound truth may well be another profound truth.", "Niels Bohr"),
    ("Prediction is very difficult, especially about the future.", "attributed to Niels Bohr"),
    ("Science is a way of thinking much more than it is a body of knowledge.", "Carl Sagan"),
    ("Extraordinary claims require extraordinary evidence.", "Carl Sagan"),
    ("The universe is under no obligation to make sense to you.", "Neil deGrasse Tyson"),
    ("Nothing in life is to be feared, it is only to be understood.", "Marie Curie"),
    ("One never notices what has been done; one can only see what remains to be done.", "Marie Curie"),
    ("If you want to go fast, go alone. If you want to go far, go together.", "proverb"),
    ("The journey of a thousand miles begins with a single step.", "Laozi"),
    ("Knowing others is intelligence; knowing yourself is true wisdom.", "Laozi"),
    ("Those who know do not speak. Those who speak do not know.", "Laozi"),
    ("Do the difficult things while they are easy and do the great things while they are small.", "Laozi"),
    ("He who knows that enough is enough will always have enough.", "Laozi"),
    ("A good traveler has no fixed plans and is not intent on arriving.", "Laozi"),
    ("Real knowledge is to know the extent of one's ignorance.", "Confucius"),
    ("Study the past if you would define the future.", "Confucius"),
    ("Only the very wisest and the very stupidest cannot change.", "Confucius"),
    ("The man who moves a mountain begins by carrying away small stones.", "attributed to Confucius"),
    ("Before enlightenment, chop wood, carry water. After enlightenment, chop wood, carry water.", "Zen proverb"),
    ("In the beginner's mind there are many possibilities, but in the expert's there are few.", "Shunryu Suzuki"),
    ("You can't stop the waves, but you can learn to surf.", "Jon Kabat-Zinn"),
    ("Everything that irritates us about others can lead us to an understanding of ourselves.", "Carl Jung"),
    ("Until you make the unconscious conscious, it will direct your life and you will call it fate.", "attributed to Carl Jung"),
    ("Freedom is nothing but a chance to be better.", "Albert Camus"),
    ("In the depth of winter, I finally learned that within me there lay an invincible summer.", "Albert Camus"),
    ("One must imagine Sisyphus happy.", "Albert Camus"),
    ("Man is the only creature who refuses to be what he is.", "Albert Camus"),
    ("Programs must be written for people to read, and only incidentally for machines to execute.", "Harold Abelson and Gerald Jay Sussman"),
    ("There are only two hard things in computer science: cache invalidation and naming things.", "Phil Karlton"),
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra"),
    ("The question of whether a computer can think is no more interesting than the question of whether a submarine can swim.", "Edsger W. Dijkstra"),
    ("Any sufficiently advanced technology is indistinguishable from magic.", "Arthur C. Clarke"),
    ("The only way of discovering the limits of the possible is to venture a little way past them into the impossible.", "Arthur C. Clarke"),
    ("We can only see a short distance ahead, but we can see plenty there that needs to be done.", "Alan Turing"),
    ("Computers are useless. They can only give you answers.", "Pablo Picasso"),
    ("Inspiration exists, but it has to find you working.", "Pablo Picasso"),
    ("Every child is an artist. The problem is how to remain an artist once we grow up.", "attributed to Pablo Picasso"),
    ("We are all in the gutter, but some of us are looking at the stars.", "Oscar Wilde"),
    ("Experience is simply the name we give our mistakes.", "Oscar Wilde"),
    ("The truth is rarely pure and never simple.", "Oscar Wilde"),
    ("There is nothing either good or bad, but thinking makes it so.", "William Shakespeare"),
    ("We know what we are, but know not what we may be.", "William Shakespeare"),
    ("Not all those who wander are lost.", "J. R. R. Tolkien"),
    ("All we have to decide is what to do with the time that is given us.", "J. R. R. Tolkien"),
    ("It's the job that's never started as takes longest to finish.", "J. R. R. Tolkien"),
    ("What is essential is invisible to the eye.", "Antoine de Saint-Exupéry"),
    ("Perfection is achieved, not when there is nothing more to add, but when there is nothing left to take away.", "Antoine de Saint-Exupéry"),
    ("Hope is the thing with feathers that perches in the soul.", "Emily Dickinson"),
    ("Tell all the truth but tell it slant.", "Emily Dickinson"),
    ("In three words I can sum up everything I've learned about life: it goes on.", "Robert Frost"),
    ("The best way out is always through.", "Robert Frost"),
    ("A book must be the axe for the frozen sea within us.", "Franz Kafka"),
    ("You do not need to leave your room. Remain sitting at your table and listen. Do not even listen, simply wait.", "Franz Kafka"),
    ("Whenever you find yourself on the side of the majority, it is time to pause and reflect.", "Mark Twain"),
    ("It ain't what you don't know that gets you into trouble. It's what you know for sure that just ain't so.", "attributed to Mark Twain"),
    ("I didn't have time to write a short letter, so I wrote a long one instead.", "Mark Twain, after Pascal"),
    ("Good judgment comes from experience, and experience comes from bad judgment.", "proverb"),
    ("The reasonable man adapts himself to the world; the unreasonable one persists in trying to adapt the world to himself. Therefore all progress depends on the unreasonable man.", "George Bernard Shaw"),
    ("The single biggest problem in communication is the illusion that it has taken place.", "attributed to George Bernard Shaw"),
    ("Those who can't change their minds can't change anything.", "George Bernard Shaw"),
    ("Talent hits a target no one else can hit; genius hits a target no one else can see.", "Arthur Schopenhauer"),
    ("Every man takes the limits of his own field of vision for the limits of the world.", "Arthur Schopenhauer"),
    ("An investment in knowledge pays the best interest.", "Benjamin Franklin"),
    ("Either write something worth reading or do something worth writing.", "Benjamin Franklin"),
    ("Well done is better than well said.", "Benjamin Franklin"),
    ("Anything worth doing is worth doing badly.", "G. K. Chesterton"),
    ("The traveler sees what he sees. The tourist sees what he has come to see.", "G. K. Chesterton"),
    ("Don't ever take a fence down until you know why it was put up.", "G. K. Chesterton, paraphrased"),
    ("The world will never starve for want of wonders; but only for want of wonder.", "G. K. Chesterton"),
    ("I learned that courage was not the absence of fear, but the triumph over it.", "Nelson Mandela"),
    ("May your choices reflect your hopes, not your fears.", "Nelson Mandela"),
    ("It always seems impossible until it's done.", "attributed to Nelson Mandela"),
    ("Comparison is the thief of joy.", "attributed to Theodore Roosevelt"),
    ("Do what you can, with what you have, where you are.", "attributed to Theodore Roosevelt"),
    ("It is not the critic who counts; not the man who points out how the strong man stumbles.", "Theodore Roosevelt"),
    ("Almost everything will work again if you unplug it for a few minutes, including you.", "Anne Lamott"),
    ("Life is what happens to you while you're busy making other plans.", "Allen Saunders, later John Lennon"),
    ("What the caterpillar calls the end of the world, the master calls a butterfly.", "Richard Bach"),
    ("Yesterday is history, tomorrow is a mystery, today is a gift. That is why it is called the present.", "attributed to Alice Morse Earle"),
)


def quote_for(day: dt.date | None = None) -> dict[str, str]:
    """The line for *day*: the same for everybody, and a different one tomorrow.

    Walked in order by the day's ordinal, so a server that has been up for a
    year has shown a year of them without repeating.
    """
    day = day or dt.date.today()
    text, who = QUOTES[day.toordinal() % len(QUOTES)]
    return {"text": text, "who": who}


# -- the weather --------------------------------------------------------------------
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# How long a forecast is good for. Open-Meteo updates hourly; a page that
# asks every ten minutes is not what makes it wrong.
FORECAST_TTL = 600.0
TIMEOUT = 6.0

# WMO weather codes, as Open-Meteo reports them: a word for each, and which
# of the app's pixel glyphs to draw. The day/night pair of the first two is
# decided at the end, by `is_day`.
_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "sun"),
    1: ("Mainly clear", "sun"),
    2: ("Partly cloudy", "part-cloud"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Rime fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "sleet"),
    57: ("Freezing drizzle", "sleet"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "sleet"),
    67: ("Freezing rain", "sleet"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with hail", "storm"),
    99: ("Thunderstorm with hail", "storm"),
}


def describe(code: int, is_day: bool = True) -> tuple[str, str]:
    """(what to say, which glyph) for a WMO code; the night gets a moon."""
    word, glyph = _CODES.get(int(code), ("Unsettled", "cloud"))
    if not is_day and glyph == "sun":
        glyph = "moon"
    if not is_day and glyph == "part-cloud":
        glyph = "part-moon"
    return word, glyph


class WeatherError(Exception):
    """The weather could not be had: the place is unknown, or the internet is."""


@dataclass(slots=True)
class Place:
    name: str
    latitude: float
    longitude: float


def fetch_json(url: str) -> dict:
    """One GET, as JSON. Patched in tests; the network is never called there."""
    request = urllib.request.Request(url, headers={"User-Agent": "cloudmorrow"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise WeatherError(f"could not reach {urllib.parse.urlsplit(url).netloc}") from exc


_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def locate(place: str) -> Place:
    """Where *place* is. "55.68,12.57" is taken as given; a name is looked up."""
    match = _COORDS.match(place)
    if match:
        return Place(place.strip(), float(match.group(1)), float(match.group(2)))
    query = urllib.parse.urlencode({"name": place, "count": 1, "language": "en", "format": "json"})
    found = fetch_json(f"{GEOCODE_URL}?{query}").get("results") or []
    if not found:
        raise WeatherError(f"no place called {place!r}")
    hit = found[0]
    where = ", ".join(
        part for part in (hit.get("name"), hit.get("country")) if part
    )
    return Place(where or place, float(hit["latitude"]), float(hit["longitude"]))


def forecast(place: Place) -> dict:
    """Now and today at *place*, in the shape the page draws."""
    query = urllib.parse.urlencode(
        {
            "latitude": place.latitude,
            "longitude": place.longitude,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "wind_speed_unit": "ms",
            "timezone": "auto",
            "forecast_days": 1,
        }
    )
    data = fetch_json(f"{FORECAST_URL}?{query}")
    now = data.get("current") or {}
    day = data.get("daily") or {}
    first = lambda key: (day.get(key) or [None])[0]  # noqa: E731
    is_day = bool(now.get("is_day", 1))
    word, glyph = describe(now.get("weather_code", -1), is_day)
    return {
        "place": place.name,
        "temperature": now.get("temperature_2m"),
        "feels_like": now.get("apparent_temperature"),
        "wind_ms": now.get("wind_speed_10m"),
        "summary": word,
        "glyph": glyph,
        "is_day": is_day,
        "high": first("temperature_2m_max"),
        "low": first("temperature_2m_min"),
        "rain_chance": first("precipitation_probability_max"),
        "sunrise": (first("sunrise") or "")[11:16],
        "sunset": (first("sunset") or "")[11:16],
    }


class Weather:
    """The forecast for one configured place, asked for as often as you like.

    A lookup is made once per place name and kept for the life of the
    process; a forecast is kept ten minutes. A failure after a success keeps
    handing out the last good answer, marked as such, because "it was 14°
    an hour ago" beats a blank card when the router is having a moment.
    """

    def __init__(self, place: str) -> None:
        self.place_name = place.strip()
        self._place: Place | None = None
        self._forecast: dict | None = None
        self._fetched = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.place_name)

    def current(self) -> dict | None:
        """The forecast, or None with no place set. Raises WeatherError otherwise."""
        if not self.configured:
            return None
        with self._lock:
            if self._forecast is not None and time.monotonic() - self._fetched < FORECAST_TTL:
                return self._forecast
            try:
                if self._place is None:
                    self._place = locate(self.place_name)
                self._forecast = {**forecast(self._place), "stale": False}
                self._fetched = time.monotonic()
            except WeatherError:
                if self._forecast is None:
                    raise
                self._forecast = {**self._forecast, "stale": True}
                # Ask again next time rather than in ten minutes: it is the
                # last good answer, not a fresh one.
                self._fetched = 0.0
            return self._forecast
