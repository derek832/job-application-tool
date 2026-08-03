"""One-time migration: map old job statuses to the new simplified set.

Mapping:
  approved_for_apply → tailored (if PDF exists) or scored (if not)
  applying           → tailored (if PDF exists) or scored (if not)
  manually_applied   → applied
  rejected_by_user   → declined
  apply_failed       → scored (reset for re-processing)
  resume_failed      → scored (reset for re-processing)

Run with: python -m scripts.migrate_statuses
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.database import build_engine


async def migrate() -> None:
    """Run the status migration."""
    from sqlalchemy import text

    engine = build_engine()

    async with engine.begin() as conn:
        # 1. manually_applied → applied
        result = await conn.execute(
            text("UPDATE job_records SET status = 'applied' WHERE status = 'manually_applied'")
        )
        print(f"manually_applied → applied: {result.rowcount} rows")

        # 2. rejected_by_user → declined
        result = await conn.execute(
            text("UPDATE job_records SET status = 'declined' WHERE status = 'rejected_by_user'")
        )
        print(f"rejected_by_user → declined: {result.rowcount} rows")

        # 3. approved_for_apply with PDF → tailored
        result = await conn.execute(
            text(
                "UPDATE job_records SET status = 'tailored' "
                "WHERE status = 'approved_for_apply' "
                "AND tailored_resume_pdf IS NOT NULL"
            )
        )
        print(f"approved_for_apply (with PDF) → tailored: {result.rowcount} rows")

        # 4. approved_for_apply without PDF → scored
        result = await conn.execute(
            text(
                "UPDATE job_records SET status = 'scored' "
                "WHERE status = 'approved_for_apply' "
                "AND tailored_resume_pdf IS NULL"
            )
        )
        print(f"approved_for_apply (no PDF) → scored: {result.rowcount} rows")

        # 5. applying with PDF → tailored
        result = await conn.execute(
            text(
                "UPDATE job_records SET status = 'tailored' "
                "WHERE status = 'applying' "
                "AND tailored_resume_pdf IS NOT NULL"
            )
        )
        print(f"applying (with PDF) → tailored: {result.rowcount} rows")

        # 6. applying without PDF → scored
        result = await conn.execute(
            text(
                "UPDATE job_records SET status = 'scored' "
                "WHERE status = 'applying' "
                "AND tailored_resume_pdf IS NULL"
            )
        )
        print(f"applying (no PDF) → scored: {result.rowcount} rows")

        # 7. apply_failed → scored (give them another chance)
        result = await conn.execute(
            text("UPDATE job_records SET status = 'scored' WHERE status = 'apply_failed'")
        )
        print(f"apply_failed → scored: {result.rowcount} rows")

        # 8. resume_failed → scored (give them another chance)
        result = await conn.execute(
            text("UPDATE job_records SET status = 'scored' WHERE status = 'resume_failed'")
        )
        print(f"resume_failed → scored: {result.rowcount} rows")

    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
