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
            select(JobRecord.id, JobRecord.job_title, JobRecord.company, JobRecord.fit_score, JobRecord.scored_at)
            .where(JobRecord.status == "extracted")
            .limit(10)
        )
        for row in result:
            print(f"{row.id} | {row.company} | {row.job_title} | score={row.fit_score} | scored_at={row.scored_at}")


asyncio.run(check())
