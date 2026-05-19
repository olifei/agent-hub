# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Scene script generation functions.

This module provides:
- Dynamic scene script generation from product images
"""

from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.log import log

from mcp_server.pipeline.video_prompts import get_scene_script_generation_prompt


def generate_scene_script(
    reference_image_uri: str,
    company_name: str,
    product_desc: str,
    country: str,
    speech_language: str = "English"
) -> tuple:
    """Generate scene script dynamically from best starting frame image and product info.
    
    Note: Retry logic and JSON parsing are now handled in invoke_gemini().
    
    Args:
        reference_image_uri: URI of the reference image (starting frame)
        company_name: Company name for branding
        product_desc: Product description
        country: Target country for the advertisement
        speech_language: Language for the speech script (default: "English")
        
    Returns:
        tuple: (scene_script_text, scene_script_json) or (False, False) if failed
    """
    log.info(f"Generating scene script for product: {product_desc[:60]}...")
    log.info(f"Parameters - Company: {company_name}, Country: {country}, Language: {speech_language}")
    
    prompt = get_scene_script_generation_prompt(company_name, product_desc, country, speech_language)
    reference_image = [{"uri": reference_image_uri, "mime_type": "image/png"}]
    
    # invoke_gemini now handles retries and list/dict conversion internally
    result = vertex_ai.invoke_gemini(
        prompt=prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        multimodal_input=reference_image,
    )
    
    # Check if API call failed
    if result is False:
        log.error("Scene script generation failed after all retries")
        return False, False
    
    # Format the structured result into a scene script string
    scene = result.get("scene", "")
    visual = result.get("visual", "")
    character = result.get("character_description", "")
    camera = result.get("camera_motion", "")
    speech = result.get("speech", "")
    speech_lang = result.get("speech_language", speech_language)
    pacing = result.get("pacing", "")
    closing = result.get("closing", "")
    
    if not all([scene, visual, character, camera, speech]):
        log.error("Scene script generation returned incomplete result!")
        log.error(f"Result: {result}")
        return False, False
    
    # Format as complete scene script
    scene_script = f"""(Scene: {scene})

Visual: {visual}

KOL/KOC Character Description: {character}

Camera Motion: {camera}

Speech: "{speech}"

Speech language: {speech_lang}

Pacing: {pacing}

Closing: {closing}"""
    
    log.info("Scene script generated successfully")
    log.info(f"Generated scene script:\n{scene_script}")
    return scene_script, result
