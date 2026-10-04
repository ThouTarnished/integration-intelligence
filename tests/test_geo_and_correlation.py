from datetime import datetime, timedelta

import pytest

from iip import geo
from iip.correlation import incident_title


@pytest.mark.parametrize("raw,expected", [("dubai", "Dubai, UAE"), ("  DUBAI,   uae ", "Dubai, UAE"),
                                          ("Singapore", "Singapore"), ("Atlantis", "Atlantis")])
def test_canonical_city_labels(raw, expected):
    assert geo.canonical(raw) == expected


def test_haversine_known_distance():
    assert geo.haversine_km(geo.CITIES["London, UK"], geo.CITIES["Paris, France"]) == pytest.approx(344, abs=5)


def test_travel_between():
    t0 = datetime(2026, 1, 1)
    trip = geo.travel_between("Dubai, UAE", t0, "London, UK", t0 + timedelta(hours=1))
    assert trip.distance_km == pytest.approx(5470, rel=0.01) and trip.speed_kmh == pytest.approx(trip.distance_km)
    unknown = geo.travel_between("Dubai, UAE", t0, "Atlantis", t0 + timedelta(hours=1)).as_dict()
    assert unknown["distance_km"] is None and unknown["speed_kmh"] is None


@pytest.mark.parametrize("signals,title", [
    (["Multiple failed login attempts", "Privileged resource access"], "Account takeover"),
    (["Rapid transactions", "Suspicious IP"], "Card testing"),
    (["Impossible travel"], "Impossible travel"),
    (["Multiple failed login attempts"], "Credential attack"),
    (["Password spray", "New device"], "Password spray"),
    (["Suspicious IP"], "Anomalous activity"),
    ([], "Anomalous activity"),
])
def test_incident_titles(signals, title):
    assert incident_title(signals) == title


def test_a_city_name_counts_only_when_the_country_agrees():
    assert geo.canonical("London, Ontario") == "London, Ontario" and geo.coords("London, Ontario") is None
    assert geo.canonical("dubai, united arab emirates") == "Dubai, UAE"
    assert geo.canonical("Singapore, Singapore") == "Singapore"
