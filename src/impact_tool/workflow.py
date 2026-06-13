from __future__ import annotations

from dataclasses import dataclass

from src.impact_tool.models import ImpactToolState, WIZARD_STEPS


@dataclass(frozen=True)
class WorkflowStep:
    number: int
    label: str
    complete: bool
    active: bool


def workflow_steps(state: ImpactToolState) -> list[WorkflowStep]:
    completed = (
        bool(state.county_name),
        bool(state.county_name),
        state.before_scene is not None and state.after_scene is not None,
        state.comparison_ready,
        state.analysis_complete,
        state.can_download_report,
    )
    first_incomplete = next((index for index, done in enumerate(completed) if not done), len(completed) - 1)
    return [
        WorkflowStep(
            number=index + 1,
            label=label,
            complete=completed[index],
            active=index == first_incomplete,
        )
        for index, label in enumerate(WIZARD_STEPS)
    ]
