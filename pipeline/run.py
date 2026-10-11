"""Run the full chain. CLI: python -m pipeline.run "idea" [--save NAME]"""
import argparse
import json
import sys
from pathlib import Path

from pipeline import steps
from pipeline.config import settings
from pipeline.moderation import HarmfulContentError
from pipeline.schemas import Draft

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"

MAX_ROUNDS = 3

TEST_CASES = {
    "1_baseline": "We launched a new employee attendance feature.",
    "2_ultra_vague": "New update is out.",
    "3_linkedin_number": "Write a LinkedIn post: we cut payroll processing time by 40%.",
    "4_external_dark_mode": "Announce to customers that our app now supports dark mode.",
    "5_negative_news": "We're discontinuing the legacy reporting tool next month.",
}


def run_pipeline(idea: str) -> dict:
    idea = idea.strip()
    if not idea:
        raise ValueError("Idea is empty")
    if len(idea) > settings.max_idea_chars:
        raise ValueError(f"Idea longer than {settings.max_idea_chars} characters")

    brief = steps.understand(idea)
    plan = steps.outline(brief)
    first = steps.draft(brief, plan)
    first_review = steps.review(brief, first)

    # Review -> improve loop: re-review the final text (extra call, not one of the six
    # stages) and, while it doesn't beat the first score, run another improve -> final
    # round on the re-review's feedback.
    current, feedback = first, first_review
    scores = [first_review.score]
    for round_no in range(1, MAX_ROUNDS + 1):
        suffix = "" if round_no == 1 else f"#{round_no}"
        revised = steps.improve(brief, current, feedback, stage=f"improve{suffix}")
        final = steps.finalize(revised, feedback, stage=f"final{suffix}")
        current = Draft(title=final.title, body_markdown=final.final_markdown)
        rereview = steps.review(brief, current, stage=f"re-review{suffix}")
        scores.append(rereview.score)
        if rereview.score > first_review.score:
            break
        feedback = rereview

    return {
        "idea": idea,
        "brief": brief.model_dump(),
        "outline": plan.model_dump(),
        "draft": first.model_dump(),
        "review": first_review.model_dump(),
        "improved": revised.model_dump(),
        "final": final.model_dump(),
        "score_before": first_review.score,
        "score_after": rereview.score,
        "final_review": rereview.model_dump(),
        "rounds": round_no,
        "score_history": scores,
    }


def save(name: str, result: dict) -> Path:
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"{name}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser()
    parser.add_argument("idea", nargs="?")
    parser.add_argument("--save", help="write outputs/<NAME>.json")
    parser.add_argument("--all", action="store_true", help="run the 5 spec test cases into outputs/")
    args = parser.parse_args()

    if not args.all and not args.idea:
        parser.error("give an idea or --all")
    try:
        if args.all:
            for name, idea in TEST_CASES.items():
                print(f"\n[{name}] {idea}", flush=True)
                result = run_pipeline(idea)
                print(f"{save(name, result)}  score {result['score_before']} -> {result['score_after']}")
            return
        result = run_pipeline(args.idea)
    except (HarmfulContentError, ValueError, RuntimeError) as exc:
        print(f"\n{'BLOCKED' if isinstance(exc, HarmfulContentError) else 'ERROR'}: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.save:
        print(f"Saved {save(args.save, result)}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
