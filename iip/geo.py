"""Geographic enrichment: canonical city labels, coordinates and travel velocity.

Locations arrive as free-text labels ("dubai", "Dubai, UAE"). Known cities are normalized
to one canonical label and given coordinates, so the risk engine can reason about
*physical* travel (distance / time) instead of just "the label changed".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

EARTH_RADIUS_KM = 6371.0088

CITIES: dict[str, tuple[float, float]] = {
    "Abu Dhabi, UAE": (24.4539, 54.3773),
    "Dubai, UAE": (25.2048, 55.2708),
    "Doha, Qatar": (25.2854, 51.5310),
    "Riyadh, Saudi Arabia": (24.7136, 46.6753),
    "Cairo, Egypt": (30.0444, 31.2357),
    "Istanbul, Turkey": (41.0082, 28.9784),
    "London, UK": (51.5074, -0.1278),
    "Paris, France": (48.8566, 2.3522),
    "Frankfurt, Germany": (50.1109, 8.6821),
    "Berlin, Germany": (52.5200, 13.4050),
    "Moscow, Russia": (55.7558, 37.6173),
    "Lagos, Nigeria": (6.5244, 3.3792),
    "Nairobi, Kenya": (-1.2921, 36.8219),
    "Mumbai, India": (19.0760, 72.8777),
    "Singapore": (1.3521, 103.8198),
    "Hong Kong": (22.3193, 114.1694),
    "Tokyo, Japan": (35.6762, 139.6503),
    "Sydney, Australia": (-33.8688, 151.2093),
    "New York, USA": (40.7128, -74.0060),
    "Toronto, Canada": (43.6532, -79.3832),
    "Sao Paulo, Brazil": (-23.5505, -46.6333),
}

# "dubai, uae" and "dubai" both resolve to the canonical "Dubai, UAE".
_ALIASES = {label.lower(): label for label in CITIES} | {label.split(",")[0].lower(): label for label in CITIES}


# Other names for the countries in CITIES, so "Dubai, United Arab Emirates" still resolves.
COUNTRY_ALIASES = {"united arab emirates": "uae", "emirates": "uae", "united kingdom": "uk", "great britain": "uk",
                   "britain": "uk", "england": "uk", "united states": "usa", "america": "usa", "us": "usa",
                   "saudi": "saudi arabia", "ksa": "saudi arabia", "turkiye": "turkey"}


def canonical(label: str) -> str:
    """Return the canonical label for a known city, or the trimmed input unchanged."""
    key = " ".join(label.split()).lower()
    if key in _ALIASES:
        return _ALIASES[key]
    city, _, country = (part.strip() for part in key.partition(","))
    match = _ALIASES.get(city)
    if match:  # the city alone is enough only when the country agrees: "London, Ontario" is not London, UK
        expected = match.partition(", ")[2].lower()  # "" for city-states such as Singapore
        if not country or not expected or COUNTRY_ALIASES.get(country, country) == expected:
            return match
    return label.strip()


def coords(label: str) -> tuple[float, float] | None:
    return CITIES.get(canonical(label))


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class Travel:
    origin: str
    destination: str
    minutes: float
    distance_km: float | None  # None when either city is unknown
    speed_kmh: float | None

    def as_dict(self) -> dict:
        return {
            "from": self.origin,
            "to": self.destination,
            "minutes": round(self.minutes, 1),
            "distance_km": None if self.distance_km is None else round(self.distance_km),
            "speed_kmh": None if self.speed_kmh is None or math.isinf(self.speed_kmh) else round(self.speed_kmh),
        }


def travel_between(origin: str, departed: datetime, destination: str, arrived: datetime) -> Travel:
    minutes = max((arrived - departed).total_seconds() / 60, 0.0)
    a, b = coords(origin), coords(destination)
    if a is None or b is None:
        return Travel(origin, destination, minutes, None, None)
    distance = haversine_km(a, b)
    speed = distance / (minutes / 60) if minutes > 0 else math.inf
    return Travel(origin, destination, minutes, distance, speed)
