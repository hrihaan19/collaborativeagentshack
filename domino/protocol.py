"""Domino wire protocol (pydantic, extra='forbid', bounded lengths).

Everything that crosses the Flower link is one of these models, serialized as
JSON bytes inside a ConfigRecord ("domino") of a RecordDict.

ONE egress class (`HospitalEgress`) describes everything that may leave a
hospital. It may contain only: opaque tokens, hospital id, donor ABO + marker,
screening result, availability, record versions, signatures (+ public key).
Never: names, recipient ABO, blocked sets, note text, prompts, model output,
exception text.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCHEMA_VERSION = "domino/0.1"
RECORD_KEY = "domino"  # ConfigRecord name inside the RecordDict
PAYLOAD_KEY = "json"  # key inside the ConfigRecord holding the JSON bytes

Token = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
HospitalId = Field(min_length=1, max_length=8, pattern=r"^[A-Z]$")


class MessageType(str, Enum):
    SCREEN_REQUEST = "SCREEN_REQUEST"
    SCREEN_RESPONSE = "SCREEN_RESPONSE"
    REVIEW_STATUS = "REVIEW_STATUS"
    PLAN_PREPARE = "PLAN_PREPARE"
    PLAN_ACK = "PLAN_ACK"
    PLAN_APPROVAL = "PLAN_APPROVAL"
    PLAN_FINALIZE = "PLAN_FINALIZE"
    REFUSAL = "REFUSAL"
    # Added beyond the original 8: the coordinator has no path to a hospital
    # except Flower, so the presenter/QR "add a fictional donor" beat needs a
    # message. The hospital ClientApp only ever activates the inactive fixture N0.
    DONOR_ACTIVATION = "DONOR_ACTIVATION"


class ScreenResult(str, Enum):
    TOY_CANDIDATE = "TOY_CANDIDATE"
    NOT_CANDIDATE = "NOT_CANDIDATE"
    UNKNOWN = "UNKNOWN"


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    HOLD = "HOLD"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(Strict):
    schema_version: Literal["domino/0.1"] = SCHEMA_VERSION
    run_id: str = Field(max_length=64)
    round_id: str = Field(max_length=64)
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=64)
    message_type: MessageType
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), max_length=40)
    record_version: int = Field(default=0, ge=0)


# ----------------------------------------------------------------- public atoms
class DonorDescriptor(Strict):
    """Public donor descriptor: token + ABO + software marker id. No names."""

    donor_token: str = Token
    vertex_token: str = Token
    hospital_id: str = HospitalId
    abo: Literal["O", "A", "B", "AB"]
    marker: str = Field(max_length=8, pattern=r"^K[0-9]$")
    kind: Literal["PAIRED", "NON_DIRECTED"]
    active: bool = True


class VertexStatus(Strict):
    """Public status of an exchange-graph vertex owned by a hospital."""

    vertex_token: str = Token
    hospital_id: str = HospitalId
    kind: Literal["PAIRED", "ENDPOINT_ONLY", "SOURCE_ONLY"]
    availability: Availability
    record_version: int = Field(ge=0)


class Evaluation(Strict):
    donor_token: str = Token
    recipient_vertex: str = Token
    result: ScreenResult


class PlanSignature(Strict):
    plan_id: str = Field(max_length=64)
    plan_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    hospital_id: str = HospitalId
    signature_hex: str = Field(min_length=128, max_length=128, pattern=r"^[0-9a-f]{128}$")
    record_versions: dict[str, int] = Field(default_factory=dict, max_length=16)
    signed_at: str = Field(max_length=40)


class PlanEdge(Strict):
    donor_vertex: str = Token
    recipient_vertex: str = Token


class PlanSummary(Strict):
    """What a hospital receives about a plan: tokens only."""

    plan_id: str = Field(max_length=64)
    plan_hash: str = Field(min_length=64, max_length=64)
    kind: Literal["CYCLE", "CHAIN"]
    edges: list[PlanEdge] = Field(max_length=8)
    roles: dict[str, str] = Field(default_factory=dict, max_length=16)
    hospitals: list[str] = Field(max_length=8)
    record_versions: dict[str, int] = Field(default_factory=dict, max_length=16)
    recipient_count: int = Field(ge=1, le=8)


# ----------------------------------------------------------- coordinator -> hosp
class CoordinatorRequest(Envelope):
    """All coordinator->hospital messages. Fields used depend on message_type."""

    donors: list[DonorDescriptor] = Field(default_factory=list, max_length=64)  # SCREEN_REQUEST
    plan: PlanSummary | None = None  # PLAN_PREPARE / PLAN_APPROVAL / PLAN_FINALIZE
    activate_token: str | None = Field(default=None, max_length=32)  # DONOR_ACTIVATION
    activation_nonce: str | None = Field(default=None, max_length=64)


# ----------------------------------------------------------- hosp -> coordinator
class HospitalEgress(Envelope):
    """THE ONLY thing a hospital ever sends. Tokens and public atoms only."""

    hospital_id: str = HospitalId
    public_key_hex: str | None = Field(default=None, min_length=64, max_length=64)
    donors: list[DonorDescriptor] = Field(default_factory=list, max_length=64)
    vertices: list[VertexStatus] = Field(default_factory=list, max_length=64)
    evaluations: list[Evaluation] = Field(default_factory=list, max_length=1024)
    signatures: list[PlanSignature] = Field(default_factory=list, max_length=8)
    ack_plan_id: str | None = Field(default=None, max_length=64)
    approval_status: Literal["PENDING", "APPROVED", "REFUSED", "N/A"] = "N/A"
    refusal_code: str | None = Field(default=None, max_length=64)
    # The public label of what produced the readiness flag at this hospital.
    # RULE-BASED FALLBACK / LOCAL_MODEL_SUGGESTED / RULE: strings, never model text.
    agent_mode: str | None = Field(default=None, max_length=32)


# --------------------------------------------------------------------- helpers
def dumps(model: BaseModel) -> bytes:
    return model.model_dump_json(exclude_none=False).encode("utf-8")


def parse_request(raw: bytes) -> CoordinatorRequest:
    return CoordinatorRequest.model_validate_json(raw)


def parse_egress(raw: bytes) -> HospitalEgress:
    return HospitalEgress.model_validate_json(raw)


def safe_parse_egress(raw: bytes) -> tuple[HospitalEgress | None, str | None]:
    """Parse; on failure return a *code*, never exception text."""
    try:
        return parse_egress(raw), None
    except ValidationError:
        return None, "SCHEMA_INVALID"
    except (ValueError, json.JSONDecodeError):
        return None, "PAYLOAD_INVALID"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
