"""Provider-neutral boundaries for Hymn's Dream Engine.

The Foundation implementation is deliberately local and deterministic.  These
protocols define the *suggestion* boundary for future AI interpretation,
authoritative public-web research, and plan synthesis without granting any
provider permission to read raw personal records or write Hymn domain data.

Provider output must always pass the Pydantic schemas here and the deterministic
validators in :mod:`dream_engine` before it can appear in a proposal.  Applying
a proposal remains a separate, authenticated Hymn operation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field


EvidenceKind = Literal[
    "user_fact",
    "hymn_owned_context",
    "deterministic_calculation",
    "ai_inference",
    "web_source",
    "assumption",
    "missing_data",
]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: EvidenceKind
    label: str
    summary: str
    source_record_type: Optional[str] = None
    source_record_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    publisher: Optional[str] = None
    retrieved_at: Optional[str] = None
    effective_date: Optional[str] = None
    expires_at: Optional[str] = None


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any
    value_type: Literal["text", "money", "date", "person", "choice", "list"]
    origin: Literal["inferred", "user_provided", "user_corrected"]
    evidence_ids: List[str] = Field(default_factory=list)
    uncertainty: Optional[str] = None


class InterpretationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journey_shape: str
    label: str
    reason: str
    confidence: Literal["clear", "likely", "ambiguous"]


class IntentInterpretationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(min_length=1, max_length=4000)
    reference_date: str
    user_selected_shape: Optional[str] = None
    locale_hint: Optional[str] = None


class IntentInterpretationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    provider_kind: Literal["deterministic", "external"]
    primary: InterpretationCandidate
    alternatives: List[InterpretationCandidate] = Field(default_factory=list)
    facts: List[ExtractedFact] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    why_needed: str
    preferred_publishers: List[str] = Field(default_factory=list)


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: List[ResearchQuestion]
    # Only public interpretation facts and user-approved derived summaries may
    # cross this boundary. Raw account, health, check-in, or profile rows do not.
    approved_public_context: Dict[str, Any] = Field(default_factory=dict)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    state: Literal[
        "research_ready",
        "research_stale",
        "research_failed",
        "manual_input_required",
    ]
    evidence: List[EvidenceItem] = Field(default_factory=list)
    message: str


class PlanNodeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["phase", "milestone", "task", "checkin_requirement"]
    parent_id: Optional[str] = None
    rank: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    timing: Optional[Dict[str, Any]] = None
    dependencies: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    checkin: Optional[Dict[str, Any]] = None


class PlanSynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpretation: IntentInterpretationResult
    # This is an explicitly minimized summary, never a dump of owned records.
    approved_context_summary: Dict[str, Any]
    approved_research_evidence: List[EvidenceItem] = Field(default_factory=list)
    user_plan_nodes: List[PlanNodeSuggestion] = Field(default_factory=list)


class PlanSynthesisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    provider_kind: Literal["deterministic", "external"]
    nodes: List[PlanNodeSuggestion] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class IntentInterpretationProvider(Protocol):
    """Interpret free text into typed, schema-valid suggestions."""

    async def interpret(
        self,
        request: IntentInterpretationRequest,
    ) -> IntentInterpretationResult: ...


class ResearchProvider(Protocol):
    """Answer approved public questions with cited, freshness-aware evidence."""

    async def research(self, request: ResearchRequest) -> ResearchResult: ...


class PlanSynthesisProvider(Protocol):
    """Suggest a stable-ID tree from confirmed, privacy-minimized inputs."""

    async def synthesize(self, request: PlanSynthesisRequest) -> PlanSynthesisResult: ...


class ProviderUnavailableError(RuntimeError):
    """Raised when an optional provider is unavailable.

    The Dream Engine converts this into a usable manual/deterministic fallback;
    it must never make proposal review or manual planning a dead end.
    """
