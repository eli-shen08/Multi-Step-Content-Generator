"""The six stages. Each receives only what the data-flow table says it needs."""
from pipeline import prompts
from pipeline.llm import call_llm
from pipeline.schemas import Brief, Draft, Final, Outline, Review


def _j(model) -> str:
    return model.model_dump_json(indent=2)


def understand(idea: str) -> Brief:
    return call_llm("understand", prompts.UNDERSTAND, f"<idea>{idea}</idea>", Brief, untrusted_input=True)


def outline(brief: Brief) -> Outline:
    return call_llm("outline", prompts.OUTLINE, f"BRIEF:\n{_j(brief)}", Outline)


def draft(brief: Brief, plan: Outline) -> Draft:
    user = f"BRIEF:\n{_j(brief)}\n\nOUTLINE:\n{_j(plan)}"
    return call_llm("draft", prompts.DRAFT, user, Draft)


def review(brief: Brief, text: Draft, stage: str = "review") -> Review:
    # Deliberately no outline: judge the draft against intent, not against the plan.
    user = f"BRIEF:\n{_j(brief)}\n\nDRAFT:\n{_j(text)}"
    return call_llm(stage, prompts.REVIEW, user, Review)


def improve(brief: Brief, text: Draft, feedback: Review, stage: str = "improve") -> Draft:
    user = f"BRIEF:\n{_j(brief)}\n\nDRAFT:\n{_j(text)}\n\nREVIEW:\n{_j(feedback)}"
    return call_llm(stage, prompts.IMPROVE, user, Draft)


def finalize(text: Draft, feedback: Review, stage: str = "final") -> Final:
    user = f"REVISED DRAFT:\n{_j(text)}\n\nREVIEW:\n{_j(feedback)}"
    return call_llm(stage, prompts.FINAL, user, Final)
