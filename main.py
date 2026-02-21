from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


JsonDict = Dict[str, Any]


@dataclass
class _ToolSpec:
    name: str
    properties: Dict[str, Any]
    required: List[str]


def _tool_index(tools: List[JsonDict]) -> Dict[str, _ToolSpec]:
    index: Dict[str, _ToolSpec] = {}
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = fn.get("name")
        params = fn.get("parameters", {})
        properties = params.get("properties", {}) if isinstance(params, dict) else {}
        required = params.get("required", []) if isinstance(params, dict) else []
        if name:
            index[name] = _ToolSpec(
                name=name,
                properties=properties if isinstance(properties, dict) else {},
                required=required if isinstance(required, list) else [],
            )
    return index


def _is_type_compatible(value: Any, expected_type: Optional[str]) -> bool:
    if expected_type is None:
        return True
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _coerce_argument(value: Any, expected_type: Optional[str]) -> Tuple[Any, bool]:
    if _is_type_compatible(value, expected_type):
        return value, True
    if expected_type == "number" and isinstance(value, str):
        try:
            return float(value), True
        except ValueError:
            return value, False
    if expected_type == "integer" and isinstance(value, str) and value.isdigit():
        return int(value), True
    if expected_type == "boolean" and isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "yes", "1"}:
            return True, True
        if lower in {"false", "no", "0"}:
            return False, True
    return value, False


def _normalize_calls(function_calls: List[JsonDict], tools: List[JsonDict]) -> List[JsonDict]:
    index = _tool_index(tools)
    normalized: List[JsonDict] = []
    for call in function_calls or []:
        name = call.get("name")
        args = call.get("arguments", {})
        if not isinstance(args, dict):
            args = {}

        spec = index.get(name)
        if spec:
            next_args: JsonDict = {}
            for key, value in args.items():
                expected_type = None
                if key in spec.properties and isinstance(spec.properties[key], dict):
                    expected_type = spec.properties[key].get("type")
                coerced, _ = _coerce_argument(value, expected_type)
                next_args[key] = coerced
            normalized.append({"name": name, "arguments": next_args})
        else:
            normalized.append({"name": name, "arguments": args})
    return normalized


def _validate_calls(function_calls: List[JsonDict], tools: List[JsonDict]) -> JsonDict:
    index = _tool_index(tools)
    unknown_tool: List[str] = []
    missing_required: List[JsonDict] = []
    arg_type_issues: List[JsonDict] = []

    for call in function_calls or []:
        name = call.get("name")
        args = call.get("arguments", {})
        if not isinstance(args, dict):
            args = {}

        spec = index.get(name)
        if not spec:
            unknown_tool.append(str(name))
            continue

        missing = [key for key in spec.required if key not in args]
        if missing:
            missing_required.append({"tool": name, "missing": missing})

        for arg_name, arg_value in args.items():
            schema = spec.properties.get(arg_name, {})
            expected_type = schema.get("type") if isinstance(schema, dict) else None
            _, ok = _coerce_argument(arg_value, expected_type)
            if not ok:
                arg_type_issues.append(
                    {
                        "tool": name,
                        "argument": arg_name,
                        "expected_type": expected_type,
                        "actual_type": type(arg_value).__name__,
                    }
                )

    valid = not unknown_tool and not missing_required and not arg_type_issues
    return {
        "valid": valid,
        "missing_required": missing_required,
        "unknown_tool": unknown_tool,
        "arg_type_issues": arg_type_issues,
    }


def _estimate_complexity(messages: List[JsonDict]) -> JsonDict:
    user_text = " ".join(
        m.get("content", "")
        for m in messages or []
        if isinstance(m, dict) and m.get("role") == "user"
    ).lower()

    signals = [
        " and ",
        " then ",
        " after that ",
        " also ",
        " plus ",
        " while ",
    ]
    signal_hits = sum(1 for token in signals if token in user_text)
    punctuation_hits = user_text.count(",") + user_text.count(";")
    has_multiple_money_mentions = len(re.findall(r"\$\s*\d+|\b\d+\s*(usd|dollars?)\b", user_text)) > 1

    multi_intent = signal_hits >= 2 or punctuation_hits >= 2 or has_multiple_money_mentions
    return {
        "label": "multi_intent" if multi_intent else "single_intent",
        "signal_hits": signal_hits,
        "punctuation_hits": punctuation_hits,
    }


def _extract_payment_context(messages: List[JsonDict], payment_context: Optional[JsonDict]) -> JsonDict:
    ctx: JsonDict = dict(payment_context or {})
    text = " ".join(
        m.get("content", "")
        for m in messages or []
        if isinstance(m, dict) and m.get("role") == "user"
    ).lower()

    amount_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if amount_match and "amount" not in ctx:
        ctx["amount"] = float(amount_match.group(1))
    if "new payee" in text and "new_payee" not in ctx:
        ctx["new_payee"] = True
    if "first time" in text and "first_time_payee" not in ctx:
        ctx["first_time_payee"] = True
    return ctx


def _needs_cloud_fallback(
    local_result: JsonDict,
    validation: JsonDict,
    complexity: JsonDict,
    payment_context: JsonDict,
) -> bool:
    confidence = float(local_result.get("confidence", 0.0))
    if not validation.get("valid", False):
        return True
    if complexity.get("label") == "multi_intent" and len(local_result.get("function_calls", [])) < 2:
        return True

    amount = float(payment_context.get("amount", 0.0) or 0.0)
    high_amount = amount >= 500.0
    new_payee = bool(payment_context.get("new_payee") or payment_context.get("first_time_payee"))
    weak_auth = not bool(payment_context.get("biometric_strong", True))
    high_risk = high_amount or new_payee or weak_auth

    # Payment-risk sensitive thresholding: higher confidence required for risky moves.
    min_conf = 0.995 if high_risk else 0.96
    return confidence < min_conf


def _extract_simple_payment(text: str) -> JsonDict:
    amount = 20.0
    payee = "unknown"
    amount_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", text.lower())
    if amount_match:
        amount = float(amount_match.group(1))

    to_match = re.search(r"\bto\s+([a-zA-Z][a-zA-Z0-9_ ]{1,30})", text)
    if to_match:
        payee = to_match.group(1).strip()

    return {"amount": amount, "payee": payee}


def _heuristic_local_calls(messages: List[JsonDict], tools: List[JsonDict], repair_mode: bool) -> Tuple[List[JsonDict], float]:
    text = " ".join(m.get("content", "") for m in messages if isinstance(m, dict) and m.get("role") == "user")
    index = _tool_index(tools)

    payload = _extract_simple_payment(text)
    calls: List[JsonDict] = []
    if "resolve_payee" in index:
        calls.append({"name": "resolve_payee", "arguments": {"payee_name": payload["payee"]}})
    if "risk_assess_transaction" in index:
        calls.append(
            {
                "name": "risk_assess_transaction",
                "arguments": {
                    "amount": payload["amount"],
                    "payee": payload["payee"],
                },
            }
        )
    if "create_payment_intent" in index:
        calls.append(
            {
                "name": "create_payment_intent",
                "arguments": {"amount": payload["amount"], "currency": "usd", "payee": payload["payee"]},
            }
        )
    if "confirm_payment" in index:
        calls.append({"name": "confirm_payment", "arguments": {"confirm": True}})

    if not calls and tools:
        first = tools[0].get("function", {}).get("name")
        if first:
            calls.append({"name": first, "arguments": {}})

    confidence = 0.93
    if repair_mode:
        confidence = 0.965
    if "?" in text:
        confidence -= 0.04
    if "and" in text.lower():
        confidence -= 0.03
    return calls, max(0.0, min(0.999, confidence))


def _call_local_planner(messages: List[JsonDict], tools: List[JsonDict], tool_rag_top_k: int, repair_mode: bool) -> JsonDict:
    start = time.perf_counter()
    calls, confidence = _heuristic_local_calls(messages, tools, repair_mode=repair_mode)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "function_calls": calls,
        "confidence": confidence,
        "local_latency_ms": elapsed_ms,
        "tool_rag_top_k": tool_rag_top_k,
        "repair_mode": repair_mode,
    }


def _call_cloud_planner(messages: List[JsonDict], tools: List[JsonDict]) -> JsonDict:
    # Default deterministic cloud fallback path. If a cloud SDK is present and configured,
    # this function can be extended without changing generate_hybrid's public contract.
    if os.getenv("VOICEPAY_CLOUD_JSON"):
        try:
            data = json.loads(os.getenv("VOICEPAY_CLOUD_JSON", "{}"))
            if isinstance(data, dict) and isinstance(data.get("function_calls"), list):
                return {"function_calls": data["function_calls"], "confidence": float(data.get("confidence", 0.99))}
        except Exception:
            pass

    calls, confidence = _heuristic_local_calls(messages, tools, repair_mode=True)
    return {"function_calls": calls, "confidence": max(0.99, confidence)}


def _candidate_score(validation: JsonDict, confidence: float, complexity: JsonDict) -> float:
    score = confidence
    if validation.get("valid"):
        score += 0.2
    score -= 0.08 * len(validation.get("missing_required", []))
    score -= 0.05 * len(validation.get("arg_type_issues", []))
    if complexity.get("label") == "multi_intent":
        score -= 0.03
    return score


def generate_hybrid(messages: List[JsonDict], tools: List[JsonDict], confidence_threshold: float = 0.99) -> JsonDict:
    start = time.perf_counter()
    payment_context = _extract_payment_context(messages, payment_context=None)
    complexity = _estimate_complexity(messages)

    # Pass 1: local planner with normal RAG.
    local_a = _call_local_planner(messages, tools, tool_rag_top_k=2, repair_mode=False)
    local_a["function_calls"] = _normalize_calls(local_a["function_calls"], tools)
    validation_a = _validate_calls(local_a["function_calls"], tools)
    fallback_a = _needs_cloud_fallback(local_a, validation_a, complexity, payment_context)
    threshold_a = max(float(confidence_threshold), 0.96)

    if (not fallback_a) and local_a["confidence"] >= threshold_a:
        total_ms = (time.perf_counter() - start) * 1000.0
        return {
            "source": "on-device",
            "route_reason": "pass1-accepted",
            "function_calls": local_a["function_calls"],
            "confidence": local_a["confidence"],
            "validation": validation_a,
            "local_time_ms": local_a["local_latency_ms"],
            "latency_ms": total_ms,
            "total_time_ms": total_ms,
        }

    # Pass 2: local repair.
    local_b = _call_local_planner(messages, tools, tool_rag_top_k=0, repair_mode=True)
    local_b["function_calls"] = _normalize_calls(local_b["function_calls"], tools)
    validation_b = _validate_calls(local_b["function_calls"], tools)
    fallback_b = _needs_cloud_fallback(local_b, validation_b, complexity, payment_context)
    threshold_b = max(float(confidence_threshold) - 0.02, 0.95)

    score_a = _candidate_score(validation_a, local_a["confidence"], complexity)
    score_b = _candidate_score(validation_b, local_b["confidence"], complexity)
    best_local = local_b if score_b >= score_a else local_a
    best_validation = validation_b if score_b >= score_a else validation_a

    if (not fallback_b) and best_local["confidence"] >= threshold_b and best_validation.get("valid", False):
        total_ms = (time.perf_counter() - start) * 1000.0
        return {
            "source": "on-device",
            "route_reason": "pass2-repair-accepted",
            "function_calls": best_local["function_calls"],
            "confidence": best_local["confidence"],
            "validation": best_validation,
            "local_time_ms": local_a["local_latency_ms"] + local_b["local_latency_ms"],
            "latency_ms": total_ms,
            "total_time_ms": total_ms,
        }

    # Cloud fallback.
    cloud = _call_cloud_planner(messages, tools)
    cloud["function_calls"] = _normalize_calls(cloud.get("function_calls", []), tools)
    cloud_validation = _validate_calls(cloud["function_calls"], tools)
    total_ms = (time.perf_counter() - start) * 1000.0
    return {
        "source": "cloud (fallback)",
        "route_reason": "local-uncertain-or-invalid",
        "function_calls": cloud["function_calls"],
        "confidence": cloud.get("confidence", 0.0),
        "validation": cloud_validation,
        "local_time_ms": local_a["local_latency_ms"] + local_b["local_latency_ms"],
        "latency_ms": total_ms,
        "total_time_ms": total_ms,
    }
