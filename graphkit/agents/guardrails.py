"""Guardrails via Google Cloud Model Armor: screens chat input and output for
prompt injection/jailbreak, malicious URLs, sensitive data and unsafe content.

Uses the `graphkit-chat-guardrail` template in the project (filterConfig: prompt
injection/jailbreak at MEDIUM_AND_ABOVE, malicious URIs, basic SDP, and RAI filters
for dangerous/harassment/hate/sexually-explicit content, all MEDIUM_AND_ABOVE).
Template management (creating/editing it) is a one-time infra step done via the
Model Armor API, not part of this module - this module only calls sanitize*.
"""
from __future__ import annotations

import os

LOCATION = os.getenv("MODEL_ARMOR_LOCATION", "us-central1")
TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "graphkit-chat-guardrail")


class Blocked(Exception):
    """Raised when Model Armor finds a match (prompt injection, unsafe content, etc.)."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Blocked by guardrails: " + ", ".join(reasons))


def _client():
    from google.cloud import modelarmor_v1
    return modelarmor_v1.ModelArmorClient(
        client_options={"api_endpoint": f"modelarmor.{LOCATION}.rep.googleapis.com"})


def _template_name(project: str) -> str:
    return f"projects/{project}/locations/{LOCATION}/templates/{TEMPLATE}"


def _reasons(result) -> list[str]:
    from google.cloud import modelarmor_v1
    MATCH = modelarmor_v1.FilterMatchState.MATCH_FOUND
    if result.filter_match_state != MATCH:
        return []
    out = []
    fr = result.filter_results
    if "pi_and_jailbreak" in fr and fr["pi_and_jailbreak"].pi_and_jailbreak_filter_result.match_state == MATCH:
        out.append("prompt injection / jailbreak attempt")
    if "malicious_uris" in fr and fr["malicious_uris"].malicious_uri_filter_result.match_state == MATCH:
        out.append("malicious URL")
    if "sdp" in fr and fr["sdp"].sdp_filter_result.inspect_result.match_state == MATCH:
        out.append("sensitive data")
    if "rai" in fr and fr["rai"].rai_filter_result.match_state == MATCH:
        out.append("unsafe content")
    return out or ["content policy"]


def check_prompt(text: str, project: str) -> None:
    """Raise Blocked if the user's message trips a guardrail."""
    from google.cloud import modelarmor_v1
    client = _client()
    result = client.sanitize_user_prompt(request=modelarmor_v1.SanitizeUserPromptRequest(
        name=_template_name(project),
        user_prompt_data=modelarmor_v1.DataItem(text=text),
    )).sanitization_result
    reasons = _reasons(result)
    if reasons:
        raise Blocked(reasons)


def check_response(text: str, project: str) -> None:
    """Raise Blocked if the model's reply trips a guardrail."""
    from google.cloud import modelarmor_v1
    client = _client()
    result = client.sanitize_model_response(request=modelarmor_v1.SanitizeModelResponseRequest(
        name=_template_name(project),
        model_response_data=modelarmor_v1.DataItem(text=text),
    )).sanitization_result
    reasons = _reasons(result)
    if reasons:
        raise Blocked(reasons)
