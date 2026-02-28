"""
Debate Engine — orchestrates multi-round agent debate.

Round 1: All agents generate independently (parallel)
Round 2: Critic reviews → agents revise
Round 3: Final revision (if no consensus after round 2)

Fixed 2-3 rounds max — deterministic, no infinite loops.
"""

from __future__ import annotations

import asyncio
import logging

from backend.models.patient import PatientContext
from backend.models.agents import (
    ClinicalAgentOutput,
    CriticOutput,
    DebateState,
    LiteratureAgentOutput,
    SafetyAgentOutput,
)

logger = logging.getLogger(__name__)


async def run_debate(
    patient: PatientContext,
    max_rounds: int = 3,
) -> DebateState:
    """
    Run the full multi-agent debate.
    
    Returns: DebateState with all round outputs and consensus info.
    """
    state = DebateState()

    for round_num in range(1, max_rounds + 1):
        state.round_number = round_num
        logger.info(f"Debate Round {round_num}/{max_rounds}")

        if round_num == 1:
            # ── Round 1: Independent generation (parallel) ──
            clinical, literature, safety = await _round_1(patient)
        else:
            # ── Round 2+: Revision based on critique ──
            last_critic = state.critic_outputs[-1] if state.critic_outputs else None
            critique_text = _format_critique(last_critic) if last_critic else ""

            clinical, literature, safety = await _revision_round(
                patient, critique_text,
                prev_clinical=state.clinical_outputs[-1] if state.clinical_outputs else None,
            )

        state.clinical_outputs.append(clinical)
        state.literature_outputs.append(literature)
        state.safety_outputs.append(safety)

        # ── Critic Phase ──
        if round_num < max_rounds:
            from backend.agents.critic import run_critic_agent

            critic = await run_critic_agent(patient, clinical, literature, safety)
            state.critic_outputs.append(critic)

            if critic.consensus_reached:
                logger.info(f"Consensus reached after round {round_num}")
                state.final_consensus = True
                break
        else:
            # Final round — check consensus one more time
            from backend.agents.critic import run_critic_agent

            critic = await run_critic_agent(patient, clinical, literature, safety)
            state.critic_outputs.append(critic)
            state.final_consensus = critic.consensus_reached

            if not critic.consensus_reached:
                state.flagged_for_human = True
                logger.warning("No consensus after max rounds — flagging for human review")

    return state


async def _round_1(
    patient: PatientContext,
) -> tuple[ClinicalAgentOutput, LiteratureAgentOutput, SafetyAgentOutput]:
    """Round 1: All agents generate in parallel."""
    from backend.agents.clinical import run_clinical_agent
    from backend.agents.literature import run_literature_agent
    from backend.agents.safety import run_safety_agent

    # Clinical runs first (literature needs its output)
    clinical = await run_clinical_agent(patient)

    # Literature and Safety run in parallel
    literature, safety = await asyncio.gather(
        run_literature_agent(patient, clinical_output=clinical),
        run_safety_agent(patient, proposed_plan=clinical.soap_draft),
    )

    return clinical, literature, safety


async def _revision_round(
    patient: PatientContext,
    critique_text: str,
    prev_clinical: ClinicalAgentOutput | None = None,
) -> tuple[ClinicalAgentOutput, LiteratureAgentOutput, SafetyAgentOutput]:
    """Revision round: agents incorporate critique."""
    from backend.agents.clinical import run_clinical_agent
    from backend.agents.literature import run_literature_agent
    from backend.agents.safety import run_safety_agent

    # Clinical revises first
    clinical = await run_clinical_agent(patient, critique=critique_text)

    # Literature and Safety revise in parallel
    literature, safety = await asyncio.gather(
        run_literature_agent(
            patient, clinical_output=clinical, critique=critique_text
        ),
        run_safety_agent(
            patient, proposed_plan=clinical.soap_draft, critique=critique_text
        ),
    )

    return clinical, literature, safety


def _format_critique(critic: CriticOutput) -> str:
    """Format CriticOutput into a string for agent prompts."""
    parts = []

    if critic.ehr_contradictions:
        parts.append("EHR Contradictions:\n" + "\n".join(f"- {c}" for c in critic.ehr_contradictions))

    if critic.evidence_gaps:
        parts.append("Evidence Gaps:\n" + "\n".join(f"- {g}" for g in critic.evidence_gaps))

    if critic.safety_misses:
        parts.append("Safety Misses:\n" + "\n".join(f"- {m}" for m in critic.safety_misses))

    if critic.overall_assessment:
        parts.append(f"Overall Assessment: {critic.overall_assessment}")

    if critic.dissent_log:
        parts.append("Points of Dissent:\n" + "\n".join(f"- {d}" for d in critic.dissent_log))

    return "\n\n".join(parts)
