"""End-to-end smoke harness — drives the agent via ADK Runner, no SSE in between.

Usage:  uv run python scripts/smoke.py path1
        uv run python scripts/smoke.py path2
"""

import asyncio
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from google.adk.artifacts import InMemoryArtifactService  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import app  # noqa: E402

PATH1_PROMPT = """Smoke test — single existing product, end-to-end, no confirmation needed.

1. prepare_dataset(source_uri='gs://jingyiwa-product-pitch-flow/test/test_dataset.xlsx')
2. upload_dataset using the resulting excel_uri, into data_dir='data'
3. list_products(data_dir='data/luggage_bags_cases')
4. batch_generate(mode='image_only', data_dir='data/luggage_bags_cases', \
product_ids=['1600907870863'], aspect_ratio='16:9', max_sample_images=1)
5. report_job_progress on the returned job_id
6. wait_for_job on the same job_id
7. get_product_assets(product_id='1600907870863')
8. Read evaluation_results.criteria from metadata.starting_frames; \
report each criterion's status
9. fetch_image_bytes for the first generated image gcs_uri
10. Final summary: criteria pass/fail counts, image gcs_uri, total elapsed
"""

PATH2_PROMPT = """Smoke test — conversational entry, single new product, end-to-end.

Add this single product:
- product_id: SMOKE-002
- product_name: Cozy Knit Reusable Shopping Tote Bag
- country: United States
- language: English
- company_name: Smoke Test Co
- image_url: https://s.alicdn.com/@sc04/kf/H032f9dfef6ba4d12b6bce93c52d0bd70E.jpg?avif=close&webp=close
- _category: smoke_tote_bags

Steps (no confirmation needed, just execute):
1. prepare_dataset(products=[<the dict above>])
2. upload_dataset using the resulting excel_uri, into data_dir='data'
3. list_products(data_dir='data/smoke_tote_bags')
4. batch_generate(mode='image_only', data_dir='data/smoke_tote_bags', \
product_ids=['SMOKE-002'], aspect_ratio='16:9', max_sample_images=1)
5. report_job_progress on the job_id
6. wait_for_job on the job_id
7. get_product_assets(product_id='SMOKE-002')
8. Report criteria, image gcs_uri, total elapsed
"""


async def run(prompt: str, label: str) -> None:
    started = datetime.now()
    print(f"\n{'=' * 70}\n  {label}  start {started:%H:%M:%S}\n{'=' * 70}\n")

    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    runner = Runner(
        app=app,
        session_service=session_service,
        artifact_service=artifact_service,
    )
    session = await session_service.create_session(
        app_name=app.name, user_id="smoke", session_id=label
    )

    new_message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id="smoke", session_id=session.id, new_message=new_message
    ):
        author = event.author or "?"
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_call:
                fc = part.function_call
                args = {
                    k: (str(v)[:140] + "…" if len(str(v)) > 140 else v)
                    for k, v in (fc.args or {}).items()
                }
                print(f"  >>> [{author}] tool_call: {fc.name}({args})")
            elif part.function_response:
                fr = part.function_response
                resp_text = str(fr.response)[:600]
                print(f"  <<< [{author}] tool_resp: {fr.name} -> {resp_text}")
            elif part.text:
                txt = part.text.strip()
                if txt:
                    print(f"\n[{author}]: {txt}\n")

    elapsed = datetime.now() - started
    print(
        f"\n{'=' * 70}\n  {label}  done in {elapsed.total_seconds():.0f}s\n{'=' * 70}"
    )


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "path1"
    if which == "path1":
        asyncio.run(run(PATH1_PROMPT, "path1"))
    elif which == "path2":
        asyncio.run(run(PATH2_PROMPT, "path2"))
    else:
        print(f"Unknown path: {which} (use path1 or path2)")
        sys.exit(2)
