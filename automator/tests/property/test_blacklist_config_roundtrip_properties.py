"""
Property-based tests for blacklist configuration round-trip.

Uses Hypothesis to verify that for any set of company names and title patterns
written via the blacklist repo (add_entry), a subsequent build_blacklist_config
returns exactly the same entries. The round-trip preserves all values.

Properties tested:
- Property 12: Blacklist Configuration Round-Trip

**Validates: Requirements 4.1, 4.2, 4.10**
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.blacklist_repo import add_entry, build_blacklist_config, get_all_entries
from src.db.models import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_session() -> AsyncSession:
    """Create a fresh in-memory SQLite database and return a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    return session


async def _roundtrip_companies_and_patterns(
    companies: list[str],
    title_patterns: list[str],
) -> tuple[list[str], list[str]]:
    """Add entries to the database and read them back via build_blacklist_config.

    Returns:
        Tuple of (retrieved_companies, retrieved_title_patterns) from the config.
    """
    session = await _create_session()
    try:
        # Write all company entries
        for company in companies:
            await add_entry(session, "company", company)

        # Write all title pattern entries
        for pattern in title_patterns:
            await add_entry(session, "title_pattern", pattern)

        await session.commit()

        # Read back via build_blacklist_config
        config = await build_blacklist_config(session)
        return config.companies, config.title_patterns
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# ASCII alphabet for generating realistic company names and title patterns.
# Avoids Unicode edge cases that aren't relevant to the blacklist feature.
_ascii_alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_&.,"

# Strategy for company names — non-empty ASCII text
company_name_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip())

# Strategy for title patterns — non-empty ASCII text
title_pattern_strategy = st.text(
    alphabet=_ascii_alphabet,
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip())

# Strategy for unique lists of companies (no duplicates since DB has unique constraint)
unique_companies_strategy = st.lists(
    company_name_strategy,
    min_size=0,
    max_size=10,
    unique=True,
)

# Strategy for unique lists of title patterns
unique_title_patterns_strategy = st.lists(
    title_pattern_strategy,
    min_size=0,
    max_size=10,
    unique=True,
)


# ---------------------------------------------------------------------------
# Property 12: Blacklist Configuration Round-Trip
# ---------------------------------------------------------------------------


@given(
    companies=unique_companies_strategy,
    title_patterns=unique_title_patterns_strategy,
)
@settings(max_examples=150)
def test_blacklist_config_roundtrip_preserves_all_companies(
    companies: list[str],
    title_patterns: list[str],
) -> None:
    """
    For any set of company names written via add_entry, a subsequent
    build_blacklist_config returns exactly the same company entries.
    The round-trip preserves all values.

    **Validates: Requirements 4.1, 4.2, 4.10**
    """
    retrieved_companies, _ = asyncio.run(
        _roundtrip_companies_and_patterns(companies, title_patterns)
    )

    assert set(retrieved_companies) == set(companies), (
        f"Round-trip failed for companies.\n"
        f"  Written: {companies}\n"
        f"  Retrieved: {retrieved_companies}"
    )
    assert len(retrieved_companies) == len(companies), (
        f"Company count mismatch.\n"
        f"  Written: {len(companies)}\n"
        f"  Retrieved: {len(retrieved_companies)}"
    )


@given(
    companies=unique_companies_strategy,
    title_patterns=unique_title_patterns_strategy,
)
@settings(max_examples=150)
def test_blacklist_config_roundtrip_preserves_all_title_patterns(
    companies: list[str],
    title_patterns: list[str],
) -> None:
    """
    For any set of title patterns written via add_entry, a subsequent
    build_blacklist_config returns exactly the same title pattern entries.
    The round-trip preserves all values.

    **Validates: Requirements 4.1, 4.2, 4.10**
    """
    _, retrieved_patterns = asyncio.run(
        _roundtrip_companies_and_patterns(companies, title_patterns)
    )

    assert set(retrieved_patterns) == set(title_patterns), (
        f"Round-trip failed for title patterns.\n"
        f"  Written: {title_patterns}\n"
        f"  Retrieved: {retrieved_patterns}"
    )
    assert len(retrieved_patterns) == len(title_patterns), (
        f"Title pattern count mismatch.\n"
        f"  Written: {len(title_patterns)}\n"
        f"  Retrieved: {len(retrieved_patterns)}"
    )


@given(
    companies=unique_companies_strategy,
    title_patterns=unique_title_patterns_strategy,
)
@settings(max_examples=150)
def test_blacklist_config_roundtrip_total_entry_count(
    companies: list[str],
    title_patterns: list[str],
) -> None:
    """
    For any set of company names and title patterns written via add_entry,
    the total number of entries in the database equals the sum of companies
    and title patterns written. No entries are lost or duplicated.

    **Validates: Requirements 4.1, 4.2, 4.10**
    """

    async def _check_total_count() -> int:
        session = await _create_session()
        try:
            for company in companies:
                await add_entry(session, "company", company)
            for pattern in title_patterns:
                await add_entry(session, "title_pattern", pattern)
            await session.commit()

            all_entries = await get_all_entries(session)
            return len(all_entries)
        finally:
            await session.close()

    total = asyncio.run(_check_total_count())
    expected = len(companies) + len(title_patterns)

    assert total == expected, (
        f"Total entry count mismatch.\n"
        f"  Expected: {expected} (companies={len(companies)}, patterns={len(title_patterns)})\n"
        f"  Got: {total}"
    )


@given(
    companies=st.lists(company_name_strategy, min_size=1, max_size=8, unique=True),
    title_patterns=st.lists(title_pattern_strategy, min_size=1, max_size=8, unique=True),
)
@settings(max_examples=150)
def test_blacklist_config_roundtrip_no_type_crossover(
    companies: list[str],
    title_patterns: list[str],
) -> None:
    """
    For any set of company names and title patterns written via add_entry,
    build_blacklist_config returns each entry under the correct type.
    Every company written is in the companies list, every title pattern
    written is in the title_patterns list. Types are preserved through
    the round-trip.

    **Validates: Requirements 4.1, 4.2, 4.10**
    """
    retrieved_companies, retrieved_patterns = asyncio.run(
        _roundtrip_companies_and_patterns(companies, title_patterns)
    )

    # Every company we wrote must appear in retrieved companies
    for company in companies:
        assert company in retrieved_companies, (
            f"Company '{company}' was written but not found in retrieved companies: "
            f"{retrieved_companies}"
        )

    # Every title pattern we wrote must appear in retrieved patterns
    for pattern in title_patterns:
        assert pattern in retrieved_patterns, (
            f"Title pattern '{pattern}' was written but not found in retrieved patterns: "
            f"{retrieved_patterns}"
        )

    # Retrieved companies must only contain values we wrote as companies
    for company in retrieved_companies:
        assert company in companies, (
            f"Retrieved company '{company}' was never written as a company entry"
        )

    # Retrieved patterns must only contain values we wrote as title patterns
    for pattern in retrieved_patterns:
        assert pattern in title_patterns, (
            f"Retrieved pattern '{pattern}' was never written as a title_pattern entry"
        )
