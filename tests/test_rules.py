"""The rulebook is pure, so every rule is tested without a database."""
from datetime import datetime, timedelta

import pytest

from iip import rules
from iip.rules import History, classify, compute_score, detect

T0 = datetime(2026, 1, 1, 12, 0)


def event(**overrides) -> dict:
    base = {"user_id": "USR-1", "event_type": "login", "timestamp": T0, "ip_address": "203.0.113.1",
            "location": "Dubai, UAE", "device_id": "DEV-1", "device_new": False, "failed_attempts": 0,
            "ip_reputation": "clean", "status": "success", "transaction_amount": None, "resource_accessed": None}
    return {**base, **overrides}


def signals_for(ev: dict, **history) -> list[str]:
    findings, _ = detect(ev, History(home_location="Dubai, UAE", trusted_device=False, **history))
    return [f.signal for f in findings]


def test_scoring_is_additive_and_clamped():
    assert compute_score(["New device", "Suspicious IP"]) == 45
    assert compute_score(["Trusted device"]) == 0
    assert compute_score([s for s, w in rules.WEIGHTS.items() if w > 0]) == 100


@pytest.mark.parametrize("score,level", [(0, "LOW"), (29, "LOW"), (30, "MEDIUM"), (59, "MEDIUM"),
                                         (60, "HIGH"), (79, "HIGH"), (80, "CRITICAL"), (100, "CRITICAL")])
def test_classification_boundaries(score, level):
    assert classify(score) == level


def test_baseline_event_is_clean():
    assert signals_for(event()) == []


def test_trusted_device_reduces_risk():
    findings, _ = detect(event(), History(home_location="Dubai, UAE", trusted_device=True))
    assert [f.signal for f in findings] == ["Trusted device"]


def test_identity_signals():
    found = signals_for(event(device_new=True, location="London, UK", ip_reputation="malicious", failed_attempts=3))
    assert set(found) == {"New device", "Unusual location", "Suspicious IP", "Multiple failed login attempts"}


def test_impossible_travel_uses_distance_and_speed():
    later = event(location="London, UK", timestamp=T0 + timedelta(minutes=20))
    assert "Impossible travel" in signals_for(later, baseline_location="Dubai, UAE", baseline_timestamp=T0)


def test_short_hops_are_not_impossible():
    """Abu Dhabi -> Dubai is ~120 km: inside geo-IP noise, never flagged (the old rule flagged it)."""
    later = event(location="Abu Dhabi, UAE", timestamp=T0 + timedelta(minutes=20))
    assert "Impossible travel" not in signals_for(later, baseline_location="Dubai, UAE", baseline_timestamp=T0)


def test_plausible_flight_is_not_impossible():
    later = event(location="London, UK", timestamp=T0 + timedelta(hours=8))
    findings, context = detect(later, History("Dubai, UAE", False, "Dubai, UAE", T0))
    assert "Impossible travel" not in [f.signal for f in findings]
    assert context["travel"]["impossible"] is False and context["travel"]["speed_kmh"] < rules.IMPOSSIBLE_SPEED_KMH


def test_unknown_city_falls_back_to_time_window():
    later = event(location="Atlantis", timestamp=T0 + timedelta(minutes=30))
    assert "Impossible travel" in signals_for(later, baseline_location="Dubai, UAE", baseline_timestamp=T0)


@pytest.mark.parametrize("overrides", [{"ip_reputation": "suspicious"}, {"status": "failure"}])
def test_travel_is_not_judged_on_unreliable_events(overrides):
    later = event(location="London, UK", timestamp=T0 + timedelta(minutes=20), **overrides)
    findings, context = detect(later, History("Dubai, UAE", False, "Dubai, UAE", T0))
    assert "Impossible travel" not in [f.signal for f in findings]
    assert context["travel"]["assessed"] is False


@pytest.mark.parametrize("amount,risky,expected", [(12_000, False, True), (2_500, True, True),
                                                   (2_500, False, False), (500, True, False)])
def test_suspicious_transaction(amount, risky, expected):
    ev = event(event_type="transaction", transaction_amount=amount, device_new=risky)
    assert ("Suspicious transaction" in signals_for(ev)) is expected


def test_rapid_transactions_need_three_in_window():
    ev = event(event_type="transaction", transaction_amount=5)
    assert "Rapid transactions" not in signals_for(ev, recent_transactions=1)
    assert "Rapid transactions" in signals_for(ev, recent_transactions=2)


def test_password_reset_after_failures():
    ev = event(event_type="password_reset")
    assert "Password reset after failures" not in signals_for(ev, recent_failures=2)
    assert "Password reset after failures" in signals_for(ev, recent_failures=3)


def test_password_spray_counts_other_accounts():
    ev = event(status="failure", failed_attempts=1)
    assert "Password spray" not in signals_for(ev, spray_accounts=3)
    assert "Password spray" in signals_for(ev, spray_accounts=4)
    assert "Password spray" not in signals_for(event(), spray_accounts=10)  # successes never count


def test_privileged_resource():
    assert "Privileged resource access" in signals_for(event(event_type="resource_access",
                                                             resource_accessed="admin-console"))


def test_assess_orders_contributions_and_explains():
    findings, _ = detect(event(device_new=True, ip_reputation="suspicious"), History("Dubai, UAE", False))
    result = rules.assess(findings)
    assert result["risk_score"] == 45 and result["risk_level"] == "MEDIUM"
    assert [c["weight"] for c in result["contributions"]] == [30, 15]
    assert result["recommended_action"] == rules.ACTIONS["MEDIUM"]
    assert "Suspicious IP" in result["explanation"]


def test_what_if_and_rulebook():
    assert rules.what_if(["Impossible travel", "Suspicious IP", "Suspicious IP"])["risk_score"] == 70
    with pytest.raises(KeyError):
        rules.what_if(["Not a signal"])
    book = rules.rulebook()
    assert len(book["signals"]) == len(rules.SIGNALS)
    assert [lvl["level"] for lvl in book["levels"]] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def test_mitre_links_handle_sub_techniques():
    assert rules.SIGNALS["Password spray"].mitre["url"] == "https://attack.mitre.org/techniques/T1110/003/"
    assert rules.SIGNALS["Trusted device"].mitre is None
