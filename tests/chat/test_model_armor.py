from google.cloud import modelarmor_v1 as ma

from graphkit.chat.guardrails import _reasons


def _result(**filter_results):
    state = ma.FilterMatchState.MATCH_FOUND if filter_results else ma.FilterMatchState.NO_MATCH_FOUND
    return ma.SanitizationResult(filter_match_state=state, filter_results=filter_results)


def test_no_match_returns_no_reasons():
    result = ma.SanitizationResult(filter_match_state=ma.FilterMatchState.NO_MATCH_FOUND)
    assert _reasons(result) == []


def test_jailbreak_match_is_named():
    result = _result(pi_and_jailbreak=ma.FilterResult(pi_and_jailbreak_filter_result=ma.PiAndJailbreakFilterResult(
        match_state=ma.FilterMatchState.MATCH_FOUND)))
    assert _reasons(result) == ["prompt injection / jailbreak attempt"]


def test_malicious_uri_match_is_named():
    result = _result(malicious_uris=ma.FilterResult(malicious_uri_filter_result=ma.MaliciousUriFilterResult(
        match_state=ma.FilterMatchState.MATCH_FOUND)))
    assert _reasons(result) == ["malicious URL"]


def test_sdp_match_is_named():
    result = _result(sdp=ma.FilterResult(sdp_filter_result=ma.SdpFilterResult(
        inspect_result=ma.SdpInspectResult(match_state=ma.FilterMatchState.MATCH_FOUND))))
    assert _reasons(result) == ["sensitive data"]


def test_rai_match_is_named():
    result = _result(rai=ma.FilterResult(rai_filter_result=ma.RaiFilterResult(
        match_state=ma.FilterMatchState.MATCH_FOUND)))
    assert _reasons(result) == ["unsafe content"]


def test_multiple_matches_are_all_named():
    result = _result(
        pi_and_jailbreak=ma.FilterResult(pi_and_jailbreak_filter_result=ma.PiAndJailbreakFilterResult(
            match_state=ma.FilterMatchState.MATCH_FOUND)),
        rai=ma.FilterResult(rai_filter_result=ma.RaiFilterResult(match_state=ma.FilterMatchState.MATCH_FOUND)),
    )
    reasons = _reasons(result)
    assert "prompt injection / jailbreak attempt" in reasons
    assert "unsafe content" in reasons
