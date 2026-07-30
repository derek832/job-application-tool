"""Metrics computation for the local scoring trial.

Pure functions for computing aggregate accuracy metrics from
ScoringComparison records. No database access or side effects.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.db.models import ScoringComparison


@dataclass
class TrialMetrics:
    """Aggregate accuracy metrics for the local scoring trial."""

    total_compared: int
    mean_absolute_error: float
    recall_at_cutoff: float  # proportion of claude>=65 that local>=cutoff
    false_positive_count: int  # local < cutoff but claude >= 65
    cutoff: int


def compute_metrics(
    comparisons: list[ScoringComparison],
    cutoff: int = 40,
) -> TrialMetrics:
    """Compute aggregate accuracy metrics from comparison records.

    Pure function — deterministic for same inputs.
    Excludes records where local_score is None.

    Args:
        comparisons: List of ScoringComparison records to analyze.
        cutoff: The local score threshold for skip decisions.

    Returns:
        TrialMetrics with MAE, recall, and false positive data.
    """
    # Filter to records with non-null local_score
    valid: list[ScoringComparison] = [c for c in comparisons if c.local_score is not None]

    if not valid:
        return TrialMetrics(
            total_compared=0,
            mean_absolute_error=0.0,
            recall_at_cutoff=1.0,
            false_positive_count=0,
            cutoff=cutoff,
        )

    # MAE = mean of |claude_score - local_score|
    total_abs_error: float = sum(
        abs(c.claude_score - c.local_score)
        for c in valid  # type: ignore[operator]
    )
    mae: float = total_abs_error / len(valid)

    # Records where claude scored >= 65 (the "good fit" threshold)
    claude_high: list[ScoringComparison] = [c for c in valid if c.claude_score >= 65]

    if not claude_high:
        # No claude >= 65 records means recall is trivially 1.0
        recall: float = 1.0
        false_positives: int = 0
    else:
        # recall = count(local >= cutoff AND claude >= 65) / count(claude >= 65)
        local_also_high: int = sum(
            1 for c in claude_high if c.local_score is not None and c.local_score >= cutoff
        )
        recall = local_also_high / len(claude_high)

        # false_positive_count = count(local < cutoff AND claude >= 65)
        false_positives = sum(
            1 for c in claude_high if c.local_score is not None and c.local_score < cutoff
        )

    return TrialMetrics(
        total_compared=len(valid),
        mean_absolute_error=mae,
        recall_at_cutoff=recall,
        false_positive_count=false_positives,
        cutoff=cutoff,
    )
