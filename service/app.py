from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from main import generate_hybrid


PAYMENT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "resolve_payee",
            "description": "Resolve recipient from spoken payee name",
            "parameters": {
                "type": "object",
                "properties": {"payee_name": {"type": "string"}},
                "required": ["payee_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_voice_match",
            "description": "Verify speaker against enrolled voice profile",
            "parameters": {
                "type": "object",
                "properties": {"speaker_id": {"type": "string"}, "confidence": {"type": "number"}},
                "required": ["speaker_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_biometric_status",
            "description": "Read biometric challenge status from mobile client",
            "parameters": {
                "type": "object",
                "properties": {"biometric_ok": {"type": "boolean"}},
                "required": ["biometric_ok"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "risk_assess_transaction",
            "description": "Assess fraud and transaction risk before payment",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "payee": {"type": "string"},
                    "biometric_ok": {"type": "boolean"},
                },
                "required": ["amount", "payee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_payment_intent",
            "description": "Create a payment intent in Stripe test mode",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                    "payee": {"type": "string"},
                },
                "required": ["amount", "currency", "payee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_payment",
            "description": "Confirm user approval before charging",
            "parameters": {
                "type": "object",
                "properties": {"confirm": {"type": "boolean"}},
                "required": ["confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "charge_payment_testmode",
            "description": "Charge saved payment method in Stripe test mode",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                    "payment_method_id": {"type": "string"},
                },
                "required": ["amount", "currency"],
            },
        },
    },
]


class TranscribeRequest(BaseModel):
    audio_base64: Optional[str] = None
    transcript_hint: Optional[str] = None


class PlanRequest(BaseModel):
    transcript: str
    payment_context: Dict[str, Any] = Field(default_factory=dict)


class ExecuteRequest(BaseModel):
    function_calls: List[Dict[str, Any]] = Field(default_factory=list)
    payment_context: Dict[str, Any] = Field(default_factory=dict)


def _response(success: bool, payload: Dict[str, Any], started: float, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "success": success,
        "error": error,
        "request_id": str(uuid.uuid4()),
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
        **payload,
    }


def _transcribe_with_cactus(req: TranscribeRequest) -> str:
    # Try to use cactus runtime if available, otherwise fall back to a deterministic mock.
    if req.transcript_hint:
        return req.transcript_hint

    cactus_module = os.getenv("CACTUS_TRANSCRIBE_MODULE")
    if cactus_module:
        try:
            mod = __import__(cactus_module, fromlist=["transcribe"])
            if hasattr(mod, "transcribe"):
                return str(mod.transcribe(req.audio_base64))
        except Exception:
            pass
    return "send $20 to Alice"


def _extract_amount_from_calls(function_calls: List[Dict[str, Any]]) -> float:
    for call in function_calls:
        args = call.get("arguments", {})
        if isinstance(args, dict) and "amount" in args:
            try:
                return float(args["amount"])
            except (TypeError, ValueError):
                continue
    return 20.0


def _execute_with_stripe_or_mock(function_calls: List[Dict[str, Any]], payment_context: Dict[str, Any]) -> Dict[str, Any]:
    amount = float(payment_context.get("amount", _extract_amount_from_calls(function_calls)))
    currency = str(payment_context.get("currency", "usd"))
    mock_result = {
        "executor": "mock",
        "status": "succeeded",
        "payment_id": f"mock_{uuid.uuid4().hex[:12]}",
        "amount": amount,
        "currency": currency,
    }

    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe_key.startswith("sk_test_"):
        return mock_result

    try:
        import stripe  # type: ignore

        stripe.api_key = stripe_key
        intent = stripe.PaymentIntent.create(
            amount=int(round(amount * 100)),
            currency=currency,
            payment_method=payment_context.get("payment_method_id", "pm_card_visa"),
            confirm=True,
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
        )
        return {
            "executor": "stripe-testmode",
            "status": intent.get("status", "unknown"),
            "payment_id": intent.get("id", ""),
            "amount": amount,
            "currency": currency,
        }
    except Exception as exc:
        fallback = dict(mock_result)
        fallback["status"] = "succeeded_with_mock_fallback"
        fallback["error"] = str(exc)
        return fallback


app = FastAPI(title="VoicePay service", version="0.1.0")


@app.post("/transcribe")
def transcribe(req: TranscribeRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    transcript = _transcribe_with_cactus(req)
    return _response(True, {"transcript": transcript, "engine": "cactus_transcribe_or_mock"}, started)


@app.post("/pay/plan")
def pay_plan(req: PlanRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    messages = [{"role": "user", "content": req.transcript}]
    plan = generate_hybrid(messages, PAYMENT_TOOLS, confidence_threshold=0.99)
    payload = {
        "transcript": req.transcript,
        "source": plan.get("source"),
        "route_reason": plan.get("route_reason"),
        "function_calls": plan.get("function_calls", []),
        "planner_latency_ms": plan.get("latency_ms", 0.0),
    }
    return _response(True, payload, started)


@app.post("/pay/execute")
def pay_execute(req: ExecuteRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    execution = _execute_with_stripe_or_mock(req.function_calls, req.payment_context)
    return _response(True, execution, started)
