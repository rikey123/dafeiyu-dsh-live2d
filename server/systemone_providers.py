"""Provider-specific System One wire contracts; never share credentials/routes.

Ark contract checked against the official page on 2026-11-14:
https://docs.volcengine.com/docs/ark/system-one-api?lang=zh
"""
from dataclasses import dataclass, field

ARK_MODEL = "doubao-seed-2-1-lite-260915"
CLEF_MODEL = "clef-omni"


@dataclass(frozen=True)
class DecisionProvider:
    name: str
    base_url: str
    model: str
    key: str = field(repr=False)
    source: str

    @property
    def can_poll(self):
        # Ark documents synchronous JSON only, not TokenToSea's results API.
        return self.name == "tokentosea"

    @property
    def response_models(self):
        # An Ark endpoint can resolve to the supported underlying model ID.
        return {self.model, ARK_MODEL} if self.name == "ark" else {CLEF_MODEL}

    def headers(self, request_key):
        if self.name == "ark":
            return {"ark-beta-systemone-api": "true"}
        return {"Idempotency-Key": request_key}

    def payload(self, state, questions, audio=None, image=None):
        if self.name == "ark" and audio:
            state = [{"type": "text", "text": state},
                     {"type": "audio", "audio_url": f"data:{audio['content_type']};base64,{audio['base64']}"}]
        if image and self.name == "ark":
            state = [{"type": "text", "text": state},
                     {"type": "image", "image_url": f"data:image/jpeg;base64,{image}"}]
        payload = {"model": self.model, "state": state, "questions": questions}
        if image and self.name == "tokentosea":
            payload["images"] = [{"content_type": "image/jpeg", "base64": image}]
        if self.name == "tokentosea" and audio:
            payload["audio"] = [audio]
        return payload


def provider_for(settings):
    # Legacy direct callers predate the persisted provider setting.
    name = settings.get("systemone_provider", "tokentosea")
    if name == "ark":
        return DecisionProvider(name, "https://ark.cn-beijing.volces.com/api/v1",
                                settings.get("systemone_ark_model", ARK_MODEL),
                                settings.get("systemone_ark_api_key", ""), "doubao-systemone")
    if name == "tokentosea":
        return DecisionProvider(name, "https://api.tokentosea.com/v1", CLEF_MODEL,
                                settings.get("systemone_api_key", ""), "clef-omni")
    raise ValueError("Unsupported System One provider")


def error_reason(status, payload):
    """Only allowlisted reason codes leave the backend, never provider messages."""
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    reasons = {
        "model_not_supported_in_region": "region_restricted",
        "ModelNotOpen": "model_not_open",
        "ModelNotSupported": "model_not_supported",
        "EndpointNotFound": "endpoint_not_found",
        "InvalidEndpointOrModel.NotFound": "endpoint_not_found",
        "AccountOverdue": "billing",
        "InsufficientBalance": "billing",
    }
    if isinstance(code, str) and code in reasons:
        return reasons[code]
    return {401: "authentication", 403: "permission_denied", 402: "billing",
            429: "rate_limit", 400: "invalid_request", 422: "invalid_request"}.get(status, "http_error")
