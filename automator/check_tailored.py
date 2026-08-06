import asyncio
from sqlalchemy import select
from src.db.database import build_engine
from src.db.models import JobRecord
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession


async def check():
    engine = build_engine()
    factory = async_sessionmaker(bind=engine, class_=AsyncSession)
    async with factory() as session:
        result = await session.execute(
            select(JobRecord.id, JobRecord.company, JobRecord.status, JobRecord.tailored_resume_text)
            .where(JobRecord.tailored_resume_text.isnot(None))
            .order_by(JobRecord.updated_at.desc())
            .limit(1)
        )
        row = result.first()
        if row:
            print(f"Job: {row.id} ({row.company}) status={row.status}")
            print(row.tailored_resume_text[:3000])
        else:
            print("No tailored jobs found")


asyncio.run(check())
