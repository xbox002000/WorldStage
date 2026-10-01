"""Write contracts/schemas/*.json from the dataclasses.   python -m contracts.generate_schemas"""
from __future__ import annotations

import json
from pathlib import Path

from contracts.backends import ShotRequest
from contracts.base import schema_for
from contracts.capability import ProviderManifest, Selection
from contracts.character import CharacterProfile, CharacterRoster
from contracts.cognition import CognitiveChoice, CognitiveState
from contracts.director import DirectorPlan
from contracts.audience import AudienceClaim, AudienceExpectation, AudienceKnowledge
from contracts.episode_plan import EpisodePlan
from contracts.intervention import InterventionProposal, WorldIntervention
from contracts.opportunity import Forecast, Opportunity
from contracts.persona import CharacterGenome, PersonaEvidence, SimulationBranch
from contracts.mechanic import NarrativeMechanicPack
from contracts.packet import ProductionPacket
from contracts.performance import PerformancePlan
from contracts.runtime import RuntimeSnapshot, RuntimeTrace
from contracts.render_request import RenderRequest, Take
from contracts.repair import RepairRequest, VisualFailure
from contracts.scene_spec import SceneSpec
from contracts.seed import ExternalEvent, SeedCandidate
from contracts.spatial import SpatialPlan
from contracts.stylepack import StylePack
from contracts.tell import TellIntent
from contracts.thread import StoryThread

OUT = Path(__file__).with_name("schemas")
CONTRACTS = {"scene_spec": SceneSpec, "production_packet": ProductionPacket, "render_request": RenderRequest,
             "take": Take, "stylepack": StylePack, "tell_intent": TellIntent,
             "external_event": ExternalEvent, "seed_candidate": SeedCandidate, "story_thread": StoryThread,
             "spatial_plan": SpatialPlan, "narrative_mechanic_pack": NarrativeMechanicPack,
             "director_plan": DirectorPlan, "performance_plan": PerformancePlan,
             "runtime_trace": RuntimeTrace, "runtime_snapshot": RuntimeSnapshot,
             "provider_manifest": ProviderManifest, "provider_selection": Selection, "shot_request": ShotRequest,
             "visual_failure": VisualFailure, "repair_request": RepairRequest,
             "character_profile": CharacterProfile, "character_roster": CharacterRoster,
             "cognitive_state": CognitiveState, "cognitive_choice": CognitiveChoice,
             "character_genome": CharacterGenome, "simulation_branch": SimulationBranch, "persona_evidence": PersonaEvidence,
             "intervention_proposal": InterventionProposal, "world_intervention": WorldIntervention,
             "audience_knowledge": AudienceKnowledge, "opportunity": Opportunity, "forecast": Forecast, "episode_plan": EpisodePlan}


def render_all() -> dict[str, str]:
    return {name: json.dumps(schema_for(cls), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            for name, cls in CONTRACTS.items()}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, text in render_all().items():
        (OUT / f"{name}.schema.json").write_text(text, encoding="utf-8", newline="\n")
        print("wrote", OUT / f"{name}.schema.json")


if __name__ == "__main__":
    main()
