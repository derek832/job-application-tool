"""Validation script: Run process_external_apply against Lever target URL.

Task 4.1 - Iterative ATS Validation spec.
Target: https://jobs.lever.co/veeva/e31a2a3c-a508-459c-9f77-a2692a95f233
Platform: Lever (Veeva Systems - Associate Software Engineer)
"""

import asyncio
import json as json_mod
import os
import socket
import urllib.request

import structlog

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)

from src.agents.claude_client import ClaudeClient
from src.agents.vision_agent import process_external_apply
from src.api.schemas import UserProfile
from src.db.config_repo import get_config
from src.db.database import build_engine, get_session
from src.db.models import JobRecord

TARGET_URL = "https://jobs.lever.co/veeva/e31a2a3c-a508-459c-9f77-a2692a95f233"


async def main():
    build_engine()

    async for session in get_session():
        profile_data = await get_config(session, "user_profile")
        if not profile_data:
            print("ERROR: No user profile found in database")
            return

        profile = UserProfile(**profile_data)
        print(f"Profile loaded: {profile.full_name} ({profile.email})")

        job_record = JobRecord(
            id="lever_validation_test_2",
            job_title="Associate Software Engineer - Seeking 2025 & 2026 Grads",
            company="Veeva Systems",
            location="Remote, US",
            linkedin_url="https://www.linkedin.com/jobs/view/0",
            external_url=TARGET_URL,
            apply_type="external_apply",
            status="approved_for_apply",
            discovered_at="2025-01-20T00:00:00Z",
            updated_at="2025-01-20T00:00:00Z",
        )

        api_key = os.environ.get("CLAUDE_API_KEY", "")
        if not api_key:
            print("ERROR: CLAUDE_API_KEY not set")
            return
        claude_client = ClaudeClient(api_key=api_key)

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            cdp_host_ip = socket.gethostbyname("host.docker.internal")
            cdp_port = 9222

            try:
                resp = urllib.request.urlopen(f"http://{cdp_host_ip}:{cdp_port}/json/version")
                version_info = json_mod.loads(resp.read().decode())
                ws_url = version_info["webSocketDebuggerUrl"]
                print(f"Chrome WebSocket URL: {ws_url}")
            except Exception as exc:
                print(f"ERROR: Failed to get Chrome WebSocket URL: {exc}")
                return

            try:
                browser = await p.chromium.connect_over_cdp(ws_url)
                print(f"Connected to browser with {len(browser.contexts)} contexts")
            except Exception as exc:
                print(f"ERROR: Failed to connect to Chrome CDP: {exc}")
                return

            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = await browser.new_context()

            page = await context.new_page()

            try:
                result = await process_external_apply(
                    job_record=job_record,
                    profile=profile,
                    page=page,
                    claude_client=claude_client,
                    min_salary=None,
                    dry_run=False,
                    session=session,
                )

                print(f"\n{'='*60}")
                print(f"RESULT: ok={result.ok}")
                if result.error:
                    print(f"ERROR: {result.error}")
                if result.reason:
                    print(f"REASON: {result.reason}")
                if result.application_notes:
                    print(f"NOTES: {result.application_notes}")
                print(f"{'='*60}")

            except Exception as exc:
                print(f"EXCEPTION: {type(exc).__name__}: {exc}")
                import traceback
                traceback.print_exc()
            finally:
                await page.close()

        break


if __name__ == "__main__":
    asyncio.run(main())
