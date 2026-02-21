# VoicePay Protocol v0.1 Implementation Plan

## 1. Objective
Build a **protocol-first voice payments system** powered by Cactus (local-first) with Gemini cloud fallback, and use a mobile app only as a demo client.

The deliverable has two tracks:
1. **Hackathon scoring track**: Improve `generate_hybrid` in `main.py` for better benchmark score and routing quality.
2. **Product demo track**: Show end-to-end voice payment authorization/execution using protocol APIs and a lightweight iPhone demo client.

---

## 2. Hackathon Alignment

### 2.1 Challenge Alignment
- The challenge requires designing strategies for when to stay on-device versus cloud.
- Objective scoring is based on correctness, speed, and on-device ratio.
- Top 10 objective performers are judged qualitatively.

### 2.2 Rubric Alignment
1. **Rubric 1: Hybrid routing depth and cleverness**
   - Implement multi-signal routing, not a single confidence threshold.
2. **Rubric 2: End-to-end real-world function-calling product**
   - Voice payment flow with auth + execution tools.
3. **Rubric 3: Low-latency voice-to-action with `cactus_transcribe`**
   - Real voice ingestion and action pipeline.

---

## 3. Feasibility and Technical Reality

### 3.1 What is feasible now
1. Cactus local tool-calling with FunctionGemma.
2. Cactus transcription + audio embeddings (`whisper-small`).
3. Cactus VAD (`silero-vad`).
4. Gemini cloud fallback for complex/ambiguous tool planning.
5. Stripe test-mode payment setup + execution flow.

### 3.2 Known constraints
1. Face ID is not fully demonstrable in plain Expo Go; development build may be required.
2. Native Cactus inference directly inside Expo Go is not the fastest path.

### 3.3 Practical architecture for timeline
- **Mobile demo app**: iPhone client for voice capture, status UI, local auth trigger.
- **Backend on Mac**: Cactus + Gemini + Stripe + protocol engine.

---

## 4. Product Definition

### 4.1 Product
**VoicePay Protocol (VPP)**: A platform-agnostic protocol for:
1. Voice enrollment and verification.
2. Risk-aware auth decisions.
3. Local-first tool-call routing with selective cloud fallback.
4. Payment execution against saved payment methods.

### 4.2 Demo app role
The app demonstrates protocol behavior; protocol itself is reusable across iOS and Android clients.

---

## 5. Model Stack and Runtime Plan

### 5.1 Local (Cactus)
1. `google/functiongemma-270m-it` for tool-call planning.
2. `openai/whisper-small` for transcription and audio embeddings.
3. `snakers4/silero-vad` for speech activity/quality gating.

### 5.2 Cloud fallback
1. `gemini-2.0-flash` as default cloud tool-call fallback.
2. Configurable via env var (`GEMINI_MODEL`) for experimentation.

### 5.3 Routing principle
Local-first by default. Cloud is invoked only on uncertainty, invalid calls, ambiguity, complexity, or high-risk contexts.

---

## 6. Benchmark Strategy

### 6.1 Score mechanics
Per difficulty level:
1. F1 accuracy contribution.
2. Time score contribution.
3. On-device ratio contribution.

Difficulty weighting prioritizes hard tasks most heavily.

### 6.2 Optimization targets
1. Improve tool-call validity and argument typing.
2. Reduce unnecessary cloud fallback.
3. Use a single local repair pass before cloud.
4. Keep interface compatibility with `benchmark.py` and `submit.py`.

---

## 7. Hybrid Routing Design (Implemented in `main.py`)

### 7.1 Signals
1. Local confidence.
2. Tool schema validity.
3. Required argument completeness.
4. Type coercion success.
5. Ambiguity cues in user text.
6. Intent complexity estimation.
7. Payment risk level (when payment context detected).

### 7.2 Decision flow
1. Run local attempt A.
2. Validate + normalize calls.
3. If valid and above dynamic threshold, accept local.
4. Else run local repair attempt B with strict repair prompt.
5. Compare candidate quality score between A and B.
6. If best local candidate is acceptable, return on-device.
7. Otherwise route to cloud fallback.
8. If cloud unavailable, return best local with explicit fallback reason.

### 7.3 Guardrails
1. Preserve benchmark output compatibility (`source`, `function_calls`, timing fields).
2. Normalize arguments to schema types for improved F1 matching.
3. Avoid multi-cloud retries to preserve latency.

---

## 8. Voice Authentication Protocol

### 8.1 Enrollment (one-time)
1. Capture 3-5 voice samples.
2. VAD quality check for each sample.
3. Extract audio embeddings.
4. Store profile centroid and dispersion metadata.

### 8.2 Verification (per transaction)
1. Capture new voice command.
2. Run VAD check.
3. Transcribe speech.
4. Extract embedding and compare to enrolled profile.
5. Generate bucket: `strong`, `borderline`, `weak`.

### 8.3 Auth policy
Risk-based step-up:
1. Strong + low risk => quick path.
2. Borderline/medium risk => biometric challenge.
3. Weak/high risk => challenge + stricter fallback path or reject.

---

## 9. Payment Flow

### 9.1 Onboarding
1. Create Stripe setup session.
2. User adds card once using Stripe-hosted secure flow.
3. Save payment method token on customer profile.

### 9.2 Daily usage
1. User speaks payment request.
2. Protocol resolves intent and verifies speaker.
3. Apply step-up auth if required.
4. Execute payment using saved payment method.

No repeated card typing during normal usage.

---

## 10. API Contract (Protocol)

### 10.1 Enrollment
1. `POST /v1/enroll/start`
2. `POST /v1/enroll/sample`
3. `POST /v1/enroll/complete`

### 10.2 Payments
1. `POST /v1/payments/setup-session`
2. `POST /v1/payments/authorize`
3. `POST /v1/payments/execute`
4. `GET /v1/payments/{id}/status`

### 10.3 Core response envelope
Each response should include:
1. `success`
2. `error`
3. `request_id`
4. `latency_ms`

`/authorize` additionally returns:
1. `route_source` (`on-device` or `cloud (fallback)`)
2. `route_reason`
3. `auth_decision`
4. `planned_function_calls`

---

## 11. Implementation Breakdown

### 11.1 Completed in this repository
1. Upgraded hybrid router in `main.py`.
2. Added this detailed plan document (`PLAN.md`).
3. Added protocol scaffolding and tests.

### 11.2 Next coding tasks
1. Wire real backend endpoints and persistence.
2. Connect Stripe execution path to protocol server.
3. Build mobile reference client end-to-end.
4. Add metrics dashboard for route reasons and latency.

---

## 12. Project Structure

```
.
├── main.py
├── benchmark.py
├── submit.py
├── PLAN.md
├── protocol/
│   ├── __init__.py
│   ├── models.py
│   ├── voice_auth.py
│   ├── tool_validation.py
│   ├── routing.py
│   ├── payments_stripe.py
│   └── server.py
├── tests/
│   ├── test_voice_auth.py
│   ├── test_tool_validation.py
│   └── test_routing.py
└── docs/
    └── VOICEPAY_PROTOCOL.md
```

---

## 13. Testing and Validation Plan

### 13.1 Unit tests
1. Voice embedding similarity and buckets.
2. Tool-call schema validation and normalization.
3. Routing decision matrix.

### 13.2 Integration checks
1. Local benchmark execution.
2. Fallback behavior with cloud disabled/enabled.
3. End-to-end protocol simulation (authorize -> execute).

### 13.3 Demo readiness checks
1. Onboarding payment method save.
2. Simple low-risk voice payment.
3. Ambiguous command fallback behavior.
4. High-risk step-up behavior.

---

## 14. Risk Register

### 14.1 High risk
1. Cloud dependency not configured (`google-genai` missing or API key absent).
2. Face ID demo limitations in Expo Go.
3. Over-fallback to cloud hurting on-device ratio.

### 14.2 Mitigations
1. Lazy cloud imports and graceful fallback handling.
2. Prefer on-device acceptance when valid.
3. Keep fallback decision explicit and auditable.

---

## 15. Acceptance Criteria

1. `generate_hybrid` remains interface-compatible.
2. Benchmark runs without interface breakage.
3. Hybrid decision uses more than confidence alone.
4. Protocol artifacts (models, routing, voice auth, docs, tests) exist and are runnable.
5. Handoff document is decision-complete for engineering implementation.

---

## 16. Handoff Notes for Engineer

1. Start with `main.py` benchmark improvements and measure score deltas first.
2. Keep all protocol logic deterministic and traceable (`route_reason`, `auth_reason`).
3. Do not ship raw card data handling; keep Stripe-hosted/tokenized flow only.
4. Treat cloud as selective fallback, not default path.
5. For judge demo, emphasize why each routing decision happened.
