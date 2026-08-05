import asyncio
import httpx


async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8000") as c:
        r = await c.post(
            "/api/system/trigger",
            headers={"Authorization": "Bearer localdev_token_2024"},
            timeout=10,
        )
        print(f"{r.status_code}: {r.text}")


asyncio.run(main())
