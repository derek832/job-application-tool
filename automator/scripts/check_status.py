"""Quick DB status check — jobs by status."""
import asyncio
from sqlalchemy import select, func
from src.db.database import get_session
from src.db.models import JobRecord


async def main():
    async for session in get_session():
        # Count by status
        result = await session.execute(
            select(JobRecord.status, func.count())
            .group_by(JobRecord.status)
            .order_by(func.count().desc())
        )
        rows = result.all()
        print("\n=== Jobs by Status ===")
        total = 0
        needs_scoring = 0
        for status, count in rows:
            print(f"  {status}: {count}")
            total += count
            if status in ("extracted", "pre_filtered"):
                needs_scoring += count
        print(f"\n  TOTAL: {total}")
        print(f"  Awaiting scoring: {needs_scoring}")
        break


asyncio.run(main())
