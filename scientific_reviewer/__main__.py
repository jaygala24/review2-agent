from __future__ import annotations

import argparse
import json

from scientific_reviewer.agent import ReviewOptions, ScientificReviewAgent
from scientific_reviewer.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coalescence-reviewer",
        description="Hierarchical scientific paper reviewer for Coalescence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser(
        "review", help="Review a paper by Coalescence paper ID."
    )
    review.add_argument("paper_id", help="Coalescence paper ID")
    review.add_argument(
        "--post-comment", action="store_true", help="Post the main comment"
    )
    review.add_argument(
        "--engage-discussion",
        action="store_true",
        help="Reply to selected comments and cast votes",
    )
    review.add_argument(
        "--post-verdict",
        action="store_true",
        help="Post a verdict if confidence and prerequisites allow it",
    )

    review_feed = subparsers.add_parser(
        "review-feed",
        help="Cron-friendly unattended review loop over feed candidates.",
    )
    review_feed.add_argument(
        "--sort",
        default="new",
        choices=["new", "hot", "top", "controversial"],
        help="Paper feed sort order",
    )
    review_feed.add_argument(
        "--domain",
        default=None,
        help="Optional domain filter such as d/NLP",
    )
    review_feed.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many feed candidates to inspect",
    )
    review_feed.add_argument(
        "--max-reviews",
        type=int,
        default=1,
        help="Maximum number of papers to process in this run",
    )
    review_feed.add_argument(
        "--post-comment", action="store_true", help="Post the main comment"
    )
    review_feed.add_argument(
        "--engage-discussion",
        action="store_true",
        help="Reply to selected comments and cast votes",
    )
    review_feed.add_argument(
        "--post-verdict",
        action="store_true",
        help="Post a verdict if confidence and prerequisites allow it",
    )

    subparsers.add_parser(
        "sync-profile",
        help="Update the Coalescence profile with the transparency repo URL.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()
    agent = ScientificReviewAgent(settings)

    if args.command == "sync-profile":
        result = agent.sync_profile()
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return

    if args.command == "review":
        result = agent.review(
            args.paper_id,
            ReviewOptions(
                post_comment=args.post_comment,
                engage_discussion=args.engage_discussion,
                post_verdict=args.post_verdict,
            ),
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return

    if args.command == "review-feed":
        result = agent.review_feed(
            sort=args.sort,
            domain=args.domain,
            limit=args.limit,
            max_reviews=args.max_reviews,
            options=ReviewOptions(
                post_comment=args.post_comment,
                engage_discussion=args.engage_discussion,
                post_verdict=args.post_verdict,
            ),
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return


if __name__ == "__main__":
    main()
