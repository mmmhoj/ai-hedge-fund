from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any

from langchain_core.messages import HumanMessage

from src.main import create_workflow
from src.utils.analysts import ANALYST_CONFIG

router = APIRouter(prefix="/committee")

DEFAULT_COMMITTEE_AGENTS = ["warren_buffett", "ben_graham", "peter_lynch"]


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


def _build_default_portfolio(tickers: list[str]) -> dict[str, Any]:
    return {
        "cash": 1_000_000,
        "margin_requirement": 0,
        "margin_used": 0,
        "positions": {
            ticker: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0,
                "short_cost_basis": 0,
                "short_margin_used": 0,
            }
            for ticker in tickers
        },
        "realized_gains": {
            ticker: {
                "long": 0,
                "short": 0,
            }
            for ticker in tickers
        },
    }


def _propagate_evidence_bundle_to_state(
    state: dict[str, Any],
    evidence_bundle: dict[str, Any] | None,
) -> None:
    # TODO: Agent tool calls do not read this state field yet; bridge it into
    # src/tools/api.py/api_kr.py via contextvars or pass it explicitly later.
    state.setdefault("data", {})["evidence_bundle"] = evidence_bundle


def _asset_canonical_id(ticker: str) -> str:
    if ticker.isdigit() and len(ticker) == 6:
        return f"{ticker}.KRX"
    return f"{ticker}.NASDAQ"


def _persona_id(agent_id: str) -> str:
    if agent_id.endswith("_agent"):
        return agent_id[: -len("_agent")]
    return agent_id


def _normalize_confidence(confidence: Any) -> float:
    try:
        normalized = float(confidence) / 100.0
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, normalized))


def _map_action(signal: Any) -> str:
    return {
        "bullish": "buy",
        "bearish": "trim",
        "neutral": "hold",
    }.get(str(signal).lower(), "hold")


def _transform_analyst_signals(
    analyst_signals: dict[str, Any],
    agent_set: list[str],
) -> list[CommitteeSignal]:
    transformed_signals: list[CommitteeSignal] = []
    allowed_agents = set(agent_set)

    for agent_id, ticker_signals in analyst_signals.items():
        persona_id = _persona_id(agent_id)
        if persona_id not in allowed_agents or not isinstance(ticker_signals, dict):
            continue

        for ticker, signal in ticker_signals.items():
            signal_data = signal if isinstance(signal, dict) else {}
            transformed_signals.append(
                CommitteeSignal(
                    asset_canonical_id=_asset_canonical_id(ticker),
                    persona_id=persona_id,
                    action=_map_action(signal_data.get("signal", "neutral")),
                    confidence=_normalize_confidence(signal_data.get("confidence", 0)),
                    rationale=str(signal_data.get("reasoning", "")),
                    claim_ids=[],
                )
            )

    return transformed_signals


def _zero_cost_breakdown(agent_set: list[str]) -> CostBreakdown:
    # TODO: Replace zero-cost placeholder with per-agent LangChain callback accounting.
    return CostBreakdown(
        total_usd=0.0,
        by_agent={agent: 0.0 for agent in agent_set},
        truncated=False,
    )


def _failed_response(
    agent_set: list[str],
    bundle_sha256: str | None,
    error_message: str,
) -> CommitteeResponse:
    return CommitteeResponse(
        run_status="failed_data",
        signals=[],
        risk_notes=[],
        tax_notes=[],
        cost_breakdown=_zero_cost_breakdown(agent_set),
        agents_run=agent_set,
        bundle_sha256=bundle_sha256,
        error_message=error_message,
    )


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

    agent_set = list(request.agent_set or DEFAULT_COMMITTEE_AGENTS)
    unknown_agents = [agent for agent in agent_set if agent not in ANALYST_CONFIG]
    if unknown_agents:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown committee agents: {', '.join(unknown_agents)}",
        )

    bundle_sha256 = (
        request.evidence_bundle.get("sha256")
        if request.evidence_bundle is not None
        else None
    )

    portfolio = (
        request.portfolio_state
        if request.portfolio_state is not None
        else _build_default_portfolio(request.tickers)
    )

    try:
        workflow = create_workflow(agent_set)
        agent = workflow.compile()
    except Exception as exc:
        return _failed_response(agent_set, bundle_sha256, str(exc))

    state: dict[str, Any] = {
        "messages": [
            HumanMessage(
                content="Make trading decisions based on the provided data.",
            )
        ],
        "data": {
            "tickers": request.tickers,
            "portfolio": portfolio,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "analyst_signals": {},
        },
        "metadata": {
            "show_reasoning": False,
            "model_name": request.model_name,
            "model_provider": request.model_provider,
        },
    }
    _propagate_evidence_bundle_to_state(state, request.evidence_bundle)

    try:
        final_state = agent.invoke(state)
        analyst_signals = final_state.get("data", {}).get("analyst_signals", {})
        signals = _transform_analyst_signals(analyst_signals, agent_set)
    except Exception as exc:
        return _failed_response(agent_set, bundle_sha256, str(exc))

    return CommitteeResponse(
        run_status="ok",
        signals=signals,
        risk_notes=[],
        tax_notes=[],
        cost_breakdown=_zero_cost_breakdown(agent_set),
        agents_run=agent_set,
        bundle_sha256=bundle_sha256,
    )
