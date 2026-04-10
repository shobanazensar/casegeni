from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


Layer = Literal["UI", "API", "Database", "ETL"]
ScenarioType = Literal["Positive", "Negative", "Edge Case", "Exception Handling"]
TestSuite = Literal["Smoke", "Functional", "EndToEnd", ""]
NonFunctionalType = Literal["Performance", "Security", "Accessibility", "Compatibility", ""]
Priority = Literal["P0", "P1", "P2", "P3"]
AutomationHint = Literal["Yes", "No", "Maybe"]


class AcceptanceCriterion(BaseModel):
    story_id: str
    story_title: str
    ac_id: str
    text: str


class ScenarioBlueprint(BaseModel):
    scenario_id: str
    story_id: str
    story_title: str
    ac_id: str
    ac_text: str
    domain: str
    module: str
    submodule: str = ""
    seed_type: str
    focus: str
    layer_candidates: List[str] = Field(default_factory=list)
    risk_tags: List[str] = Field(default_factory=list)


class TestCase(BaseModel):
    test_case_id: str
    story_id: str
    story_title: str
    ac_id: str
    ac_text: str
    title: str
    domain: str
    module: str
    submodule: str = ""
    test_case_layer: Layer
    scenario_type: ScenarioType
    test_suite: TestSuite = "Functional"
    execution_tags: List[str] = Field(default_factory=list)
    classification_rationale: str = ""
    non_functional_type: NonFunctionalType = ""
    priority: Priority = "P2"
    automation_hint: AutomationHint = "Maybe"
    automated: AutomationHint = "Maybe"
    preconditions: List[str]
    test_data: List[str]
    steps: List[str]
    expected_result: str
    tags: List[str] = Field(default_factory=list)
    reviewer_score: float = 0.0
    reviewer_grade: str = ""
    review_profile: str = ""
