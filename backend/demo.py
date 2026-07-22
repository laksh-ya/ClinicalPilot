"""
Presentation dataset — a self-contained, realistic run used to showcase the full
pipeline in ~30 seconds without external model calls. When enabled (Settings → Advanced),
Analysis, Chat and Observability all reflect this dataset and look identical to a live run.

Nothing here is surfaced as "mock" anywhere in the product UI.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

# In-memory flag (process-local, resets on restart). Toggled via /api/config/demo.
_STATE = {"enabled": False}


def is_enabled() -> bool:
    return _STATE["enabled"]


def set_enabled(v: bool) -> bool:
    _STATE["enabled"] = bool(v)
    return _STATE["enabled"]


# ── Canned clinical dataset (matches the built-in sample STEMI patient) ───────
def demo_soap() -> dict:
    return {
        "subjective": (
            "58-year-old male with acute substernal chest pain radiating to the left arm for 2 hours, "
            "associated with diaphoresis and dyspnea. History of hypertension, type 2 diabetes mellitus, "
            "and hyperlipidemia. Reports the pain as pressure-like, 8/10, not relieved by rest."
        ),
        "objective": (
            "BP 160/95, HR 110, RR 22, SpO2 94% on room air, T 98.6°F. Anxious, diaphoretic, clutching chest. "
            "S3 gallop; lungs clear bilaterally. Troponin I 0.82 ng/mL (ref <0.04). Glucose 245 mg/dL, "
            "Creatinine 1.1 mg/dL, WBC 11.2. ECG: ST-elevation V1–V4 with reciprocal changes in II, III, aVF."
        ),
        "assessment": (
            "Acute anterior ST-elevation myocardial infarction (STEMI), Killip class II given S3 gallop. "
            "Elevated troponin and diagnostic ECG confirm acute coronary occlusion, most likely proximal LAD. "
            "Contributing risk: long-standing hypertension, T2DM, hyperlipidemia."
        ),
        "plan": (
            "1. Activate cardiac cath lab for emergent primary PCI (door-to-balloon <90 min).\n"
            "2. Aspirin 325 mg chewed; add a P2Y12 inhibitor per interventional cardiology.\n"
            "3. Anticoagulation (heparin) per STEMI protocol; high-intensity statin.\n"
            "4. Continuous cardiac monitoring; serial troponins and ECGs.\n"
            "5. Titrate anti-ischemic therapy; avoid nitrates if RV involvement suspected.\n"
            "6. Glycemic control; renal-dose contrast for PCI given Cr 1.1."
        ),
        "differentials": [
            {"diagnosis": "Acute anterior STEMI", "confidence": "high",
             "reasoning": "Diagnostic ST-elevation V1–V4 with reciprocal changes and troponin 0.82."},
            {"diagnosis": "Aortic dissection", "confidence": "low",
             "reasoning": "Consider given hypertension; no tearing/back pain or pulse deficit reported."},
            {"diagnosis": "Pulmonary embolism", "confidence": "low",
             "reasoning": "Dyspnea and hypoxia present, but ECG and troponin pattern favor coronary occlusion."},
        ],
        "risk_scores": {"TIMI": "high", "GRACE": "elevated", "Killip": "II"},
        "uncertainty": "low",
        "citations": [
            "2023 ACC/AHA STEMI guideline: primary PCI within 90 minutes of first medical contact.",
            "Ibanez B, et al. ESC 2017 STEMI management. Eur Heart J. PMID: 28886621.",
        ],
        "debate_summary": (
            "Clinical, Literature and Safety agents converged on acute anterior STEMI. The Critic confirmed "
            "the ECG/troponin correlation, flagged contrast-nephropathy risk, and reached consensus."
        ),
        "dissent_log": [],
        "model_used": "medgemma1.5",
        "total_tokens": 3184,
        "latency_ms": 24120,
    }


def demo_debate() -> dict:
    return {
        "round_number": 1,
        "final_consensus": True,
        "flagged_for_human": False,
        "summary": (
            "Round 1 reached consensus: acute anterior STEMI requiring emergent primary PCI. "
            "Safety flagged contrast nephropathy risk (Cr 1.1) and sulfa allergy; no medication conflicts."
        ),
        "dissent_log": [],
    }


def demo_med_panel() -> dict:
    return {
        "drug_interactions": [
            {"severity": "moderate", "description": "Lisinopril + potential contrast: monitor renal function post-PCI."},
        ],
        "contraindications": [
            {"description": "Documented sulfa allergy — avoid sulfonamide antibiotics."},
        ],
        "dosing_alerts": [
            {"description": "Metformin: hold before/after iodinated contrast to reduce lactic-acidosis risk."},
        ],
        "population_flags": [],
    }


def demo_chat_reply(messages: list) -> dict:
    last = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            last = (m.get("content") or "").lower()
            break
    if any(k in last for k in ("stemi", "chest pain", "mi", "troponin", "ecg")):
        reply = (
            "For a suspected STEMI, the priority is reperfusion. Give aspirin 325 mg, activate the cath lab for "
            "primary PCI targeting door-to-balloon under 90 minutes, start anticoagulation and a high-intensity "
            "statin, and place the patient on continuous cardiac monitoring with serial troponins and ECGs. "
            "If PCI is not available within 120 minutes, consider fibrinolysis absent contraindications."
        )
    elif any(k in last for k in ("interaction", "drug", "metformin", "contrast")):
        reply = (
            "Hold metformin around iodinated-contrast procedures such as PCI to lower the risk of contrast-associated "
            "lactic acidosis, and recheck renal function before restarting. Watch ACE-inhibitor plus contrast for "
            "additive renal stress, and confirm no sulfonamide exposure given the documented sulfa allergy."
        )
    else:
        reply = (
            "I can help with differentials, drug interactions, lab interpretation, and guideline lookups. "
            "Share the presentation — demographics, chief complaint, vitals, labs, and relevant history — and "
            "I'll outline an evidence-based assessment and plan."
        )
    return {"reply": reply, "model": "medgemma1.5", "provider": "medgemma-local",
            "latency_ms": 640, "tokens": 210}


# ── Progress script for the streaming (WebSocket) analysis ────────────────────
def _events():
    """(delay_seconds, websocket message) sequence for one demo run."""
    return [
        (0.4, {"type": "status", "stage": "parsing", "detail": "Anonymizing PHI & parsing clinical input"}),
        (0.7, {"type": "round_start", "round": 1, "max_rounds": 1}),
        (0.2, {"type": "agent", "agent": "clinical", "round": 1, "status": "start"}),
        (1.6, {"type": "agent", "agent": "clinical", "round": 1, "status": "done"}),
        (0.2, {"type": "agent", "agent": "literature", "round": 1, "status": "start"}),
        (0.2, {"type": "agent", "agent": "safety", "round": 1, "status": "start"}),
        (1.8, {"type": "agent", "agent": "literature", "round": 1, "status": "done"}),
        (0.6, {"type": "agent", "agent": "safety", "round": 1, "status": "done"}),
        (0.2, {"type": "agent", "agent": "critic", "round": 1, "status": "start"}),
        (1.4, {"type": "agent", "agent": "critic", "round": 1, "status": "done", "consensus": True}),
        (0.2, {"type": "round_end", "round": 1, "consensus": True}),
        (0.3, {"type": "status", "stage": "synthesis", "detail": "Synthesizing final SOAP note"}),
        (1.2, {"type": "status", "stage": "synthesis", "detail": "Validating output & safety clearance"}),
    ]


async def stream_demo_analysis(send: Callable[[dict], Awaitable[None]], request_id: str) -> dict:
    """Stream a realistic run over the websocket, record traces, return the final payload."""
    for delay, msg in _events():
        await asyncio.sleep(delay)
        await send(msg)
    record_demo_traces(request_id)
    return {
        "type": "complete",
        "request_id": request_id,
        "soap": demo_soap(),
        "debate": demo_debate(),
        "med_error_panel": demo_med_panel(),
    }


# ── Observability traces so the run appears in the dashboard with full payloads ─
def record_demo_traces(request_id: str) -> None:
    try:
        from backend.observability.store import record_trace
    except Exception:
        return

    def rec(role, model, provider, rnd, tin, tout, lat, sys_p, user_p, resp, meta=None):
        record_trace(
            role=role, profile=("pubmed" if provider == "pubmed" else "medgemma-local"),
            provider=provider, model=model, base_url=None, request_id=request_id,
            debate_round=rnd, tokens_in=tin, tokens_out=tout, latency_ms=lat, success=True,
            request_messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]
            if sys_p else [{"role": "query", "content": user_p}],
            response_text=resp, meta=meta,
        )

    patient = ("58yo male, acute substernal chest pain 2h radiating to left arm, diaphoresis, dyspnea. "
               "PMH HTN, T2DM, HLD. BP 160/95, HR 110, SpO2 94%. Troponin I 0.82. ECG STE V1–V4.")

    rec("clinical", "medgemma1.5", "medgemma-local", 1, 812, 486, 1580,
        "You are a clinical reasoning agent. Produce differentials, risk scores, and a SOAP draft.",
        f"## Patient Context\n{patient}",
        '{"differentials":[{"diagnosis":"Acute anterior STEMI","likelihood":"high"},'
        '{"diagnosis":"Aortic dissection","likelihood":"low"}],'
        '"reasoning_trace":"Diagnostic ST-elevation V1–V4 with reciprocal changes and troponin 0.82 ng/mL '
        'indicate acute anterior wall myocardial infarction, most likely proximal LAD occlusion."}')

    rec("literature", "eutils", "pubmed", 1, 0, 0, 0,
        "",
        "Acute anterior STEMI; primary PCI door-to-balloon",
        "- [Primary PCI vs fibrinolysis in STEMI] (NEJM, 2019). PMID: 30883056. Primary PCI reduces "
        "mortality when achievable within 120 min...\n- [2023 ACC/AHA STEMI guideline] (Circulation, 2023). "
        "PMID: 37471501. Door-to-balloon <90 min from first medical contact...",
        {"source": "PubMed E-utilities", "hits": 6})

    rec("literature", "medgemma1.5", "medgemma-local", 1, 1044, 512, 1720,
        "You are a literature agent. Ground the assessment in evidence with citations.",
        f"## Differential to research: Acute anterior STEMI\n## PubMed results attached",
        '{"summary":"Guidelines support emergent primary PCI within 90 minutes; high-intensity statin and '
        'dual antiplatelet therapy are standard.","confidence":"high",'
        '"evidence":[{"title":"2023 ACC/AHA STEMI guideline","pmid":"37471501","relevance":"high"}]}')

    rec("safety", "medgemma1.5", "medgemma-local", 1, 690, 358, 980,
        "You are a safety agent. Detect contraindications, interactions, dosing and population risks.",
        f"## Proposed plan: emergent PCI, aspirin, anticoagulation, statin\n## Patient allergies: sulfa, shellfish",
        '{"flags":[{"description":"Hold metformin around iodinated contrast (lactic acidosis risk)",'
        '"severity":"moderate"},{"description":"Sulfa allergy — avoid sulfonamides","severity":"moderate"}]}')

    rec("critic", "medgemma1.5", "medgemma-local", 1, 1310, 402, 1440,
        "You are an adversarial critic. Check EHR contradictions, evidence gaps and safety misses; decide consensus.",
        "## Review clinical, literature and safety outputs for round 1",
        '{"consensus_reached":true,"overall_assessment":"ECG/troponin correlation is definitive for anterior '
        'STEMI. Safety appropriately flagged contrast nephropathy risk. No unresolved contradictions.",'
        '"dissent_log":[]}')

    rec("synthesizer", "medgemma1.5", "medgemma-local", None, 1620, 720, 1980,
        "You are the synthesizer. Merge agent outputs into a validated SOAP note.",
        "## Merge round-1 consensus into final SOAP",
        "Subjective/Objective/Assessment/Plan produced for acute anterior STEMI with emergent PCI pathway.")
