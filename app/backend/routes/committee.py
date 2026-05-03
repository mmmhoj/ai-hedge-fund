from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any

router = APIRouter(prefix="/committee")


class CommitteeRequest(BaseModel):
    tickers: list[str]
    start_date: str
    end_date: str
    agent_set: list[str] = Field(default_factory=list)
    cost_cap_usd: float = 1.50
    evidence_bundle: dict[str, Any] | None = None
    portfolio_state: dict[str, Any] | None = None
    model_name: str = "gpt-4o"
    model_provider: str = "OpenAI"


class CommitteeSignal(BaseModel):
    asset_canonical_id: str
    persona_id: str
    action: str
    confidence: float
    rationale: str
    claim_ids: list[int] = Field(default_factory=list)


class CostBreakdown(BaseModel):
    total_usd: float
    by_agent: dict[str, float] = Field(default_factory=dict)
    truncated: bool = False
    truncation_reason: str | None = None


class CommitteeResponse(BaseModel):
    run_status: str
    signals: list[CommitteeSignal] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    tax_notes: list[str] = Field(default_factory=list)
    cost_breakdown: CostBreakdown
    agents_run: list[str] = Field(default_factory=list)
    bundle_sha256: str | None = None
    error_message: str | None = None


@router.post(
    "/run",
    response_model=CommitteeResponse,
    responses={
        200: {"description": "Committee signals (possibly partial under failed_budget)"},
        400: {"description": "Invalid request"},
        413: {"description": "EvidenceBundle exceeds size limit"},
        500: {"description": "Internal error"},
    },
)
async def run(request: CommitteeRequest) -> CommitteeResponse:
    if not request.tickers:
        raise HTTPException(status_code=400, detail="tickers must not be empty")

    bundle_sha256 = None
    if request.evidence_bundle is not None:
        bundle_sha256 = request.evidence_bundle.get("sha256")

    return CommitteeResponse(
        run_status="ok",
        signals=[],
        risk_notes=[
            "committee/run is a Step 6 stub — agent ensemble lands in Step 7."
        ],
        tax_notes=[],
        cost_breakdown=CostBreakdown(total_usd=0.0, by_agent={}, truncated=False),
        agents_run=list(request.agent_set),
        bundle_sha256=bundle_sha256,
    )
