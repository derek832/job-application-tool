# Feature: local-scoring-trial, Property 7: Metrics computation correctness
"""
Property-based tests for metrics computation.

Uses Hypothesis to verify that `compute_metrics` correctly computes
MAE, recall_at_cutoff, and false_positive_count for any combination
of ScoringComparison records and cutoff values.

Properties tested:
- Property 7: Metrics computation correctness
  - mean_absolute_error = arithmetic mean of |claude_score - local_score| across valid records
  - recall_at_cutoff = count(local_score >= cutoff AND claude_score >= 65) / count(claude_score >= 65)
    (or 1.0 if no claude_score >= 65 exists)
  - false_positive_count = count(local_score < cutoff AND claude_score >= 65)
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from src.db.models import ScoringComparison
from src.scoring.metrics import compute_metrics


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Scores are integers 0-100
score_strategy = st.integers(min_value=0, max_value=100)

# Cutoff threshold is an integer 0-100
cutoff_strategy = st.integers(min_value=0, max_value=100)


def _make_comparison(local_score: int | None, claude_score: int) -> ScoringComparison:
    """Create a minimal ScoringComparison object with only the fields needed for metrics."""
    record = ScoringComparison(
        id=1,
        job_id="test_job",
        local_score=local_score,
        claude_score=claude_score,
        score_difference=None,
        would_skip=0,
        model_version="v1_test",
        scored_at="2024-01-01T00:00:00Z",
    )
    return record


# Strategy for a single comparison record with non-null local_score
valid_comparison_strategy = st.builds(
    _make_comparison,
    local_score=score_strategy,
    claude_score=score_strategy,
)

# Strategy for a comparison record with nullable local_score (some None)
nullable_comparison_strategy = st.builds(
    _make_comparison,
    local_score=st.one_of(st.none(), score_strategy),
    claude_score=score_strategy,
)

# Strategy for a list of comparisons that always contains at least one valid record
# Mix of valid (non-null local_score) and nullable records
comparison_list_strategy = st.lists(
    nullable_comparison_strategy,
    min_size=1,
    max_size=50,
).filter(lambda records: any(r.local_score is not None for r in records))


# ---------------------------------------------------------------------------
# Property 7: Metrics computation correctness
# ---------------------------------------------------------------------------


@given(
    comparisons=comparison_list_strategy,
    cutoff=cutoff_strategy,
)
@settings(max_examples=200)
def test_metrics_mean_absolute_error(
    comparisons: list[ScoringComparison],
    cutoff: int,
) -> None:
    """
    For any non-empty set of ScoringComparison records (with non-null local_score)
    and any cutoff value in [0, 100]:
    mean_absolute_error SHALL equal the arithmetic mean of |claude_score - local_score|
    across all records with non-null local_score.

    **Validates: Requirements 5.3, 6.2, 6.3**
    """
    result = compute_metrics(comparisons, cutoff=cutoff)

    # Independently compute expected MAE
    valid = [c for c in comparisons if c.local_score is not None]
    expected_mae = sum(abs(c.claude_score - c.local_score) for c in valid) / len(valid)

    assert math.isclose(result.mean_absolute_error, expected_mae, rel_tol=1e-9), (
        f"Expected MAE={expected_mae}, got {result.mean_absolute_error} "
        f"(valid_count={len(valid)}, cutoff={cutoff})"
    )


@given(
    comparisons=comparison_list_strategy,
    cutoff=cutoff_strategy,
)
@settings(max_examples=200)
def test_metrics_recall_at_cutoff(
    comparisons: list[ScoringComparison],
    cutoff: int,
) -> None:
    """
    For any non-empty set of ScoringComparison records (with non-null local_score)
    and any cutoff value in [0, 100]:
    recall_at_cutoff SHALL equal count(local_score >= cutoff AND claude_score >= 65)
    / count(claude_score >= 65) (or 1.0 if no claude_score >= 65 exists).

    **Validates: Requirements 5.3, 6.2, 6.3**
    """
    result = compute_metrics(comparisons, cutoff=cutoff)

    # Independently compute expected recall
    valid = [c for c in comparisons if c.local_score is not None]
    claude_high = [c for c in valid if c.claude_score >= 65]

    if not claude_high:
        expected_recall = 1.0
    else:
        local_also_high = sum(1 for c in claude_high if c.local_score >= cutoff)
        expected_recall = local_also_high / len(claude_high)

    assert math.isclose(result.recall_at_cutoff, expected_recall, rel_tol=1e-9), (
        f"Expected recall={expected_recall}, got {result.recall_at_cutoff} "
        f"(claude_high_count={len(claude_high)}, cutoff={cutoff})"
    )


@given(
    comparisons=comparison_list_strategy,
    cutoff=cutoff_strategy,
)
@settings(max_examples=200)
def test_metrics_false_positive_count(
    comparisons: list[ScoringComparison],
    cutoff: int,
) -> None:
    """
    For any non-empty set of ScoringComparison records (with non-null local_score)
    and any cutoff value in [0, 100]:
    false_positive_count SHALL equal count(local_score < cutoff AND claude_score >= 65).

    **Validates: Requirements 5.3, 6.2, 6.3**
    """
    result = compute_metrics(comparisons, cutoff=cutoff)

    # Independently compute expected false_positive_count
    valid = [c for c in comparisons if c.local_score is not None]
    claude_high = [c for c in valid if c.claude_score >= 65]
    expected_fp = sum(1 for c in claude_high if c.local_score < cutoff)

    assert result.false_positive_count == expected_fp, (
        f"Expected false_positive_count={expected_fp}, got {result.false_positive_count} "
        f"(claude_high_count={len(claude_high)}, cutoff={cutoff})"
    )


@given(
    comparisons=st.lists(nullable_comparison_strategy, min_size=1, max_size=30),
    cutoff=cutoff_strategy,
)
@settings(max_examples=100)
def test_metrics_excludes_null_local_scores(
    comparisons: list[ScoringComparison],
    cutoff: int,
) -> None:
    """
    Records with None local_score SHALL be excluded from all metric computations.
    total_compared SHALL equal the count of records with non-null local_score.

    **Validates: Requirements 5.3, 6.2, 6.3**
    """
    result = compute_metrics(comparisons, cutoff=cutoff)

    valid_count = sum(1 for c in comparisons if c.local_score is not None)
    assert result.total_compared == valid_count, (
        f"Expected total_compared={valid_count}, got {result.total_compared}"
    )
