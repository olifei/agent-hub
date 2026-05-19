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
Video generation functions.

This module provides:
- Veo prompt generation
- Video clip generation with Veo
- Video generation with evaluation-based retry loop
"""

import os

from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.gcs_service import gcs_service
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.log import log
from mcp_server.pipeline.user_context import get_output_base_dir, get_gcs_prefix

from mcp_server.pipeline.video_prompts import (
    get_veo_prompt_with_scene_script,
    get_veo_prompt_with_feedback,
)
from mcp_server.pipeline.evaluator import (
    DEFAULT_REQUIRED_VIDEO_CRITERIA,
    check_all_criteria_passed,
    get_failed_criteria_summary,
    log_evaluation_details,
)
from mcp_server.pipeline.video_evaluator import eval_single_video


# Default negative prompt for skin texture and lighting realism (max 5 items)
DEFAULT_NEGATIVE_PROMPT = "over-smoothed poreless skin, beauty filter or airbrushed effect, plastic wax-like skin appearance, harsh direct lighting on face, flat lighting that removes skin texture"


def generate_veo_prompt(reference_image_uri: str, scene_script: str) -> str:
    """Generate a single Veo prompt for video generation.
    
    Args:
        reference_image_uri: URI of the reference image (starting frame)
        scene_script: The scene script for video generation
        
    Returns:
        str: The generated Veo prompt, or False if failed
    """
    prompt = get_veo_prompt_with_scene_script()
    prompt = prompt.replace("{{SCENE_SCRIPT}}", scene_script)
    
    reference_image = [{"uri": reference_image_uri, "mime_type": "image/png"}]
    
    veo_prompt_result = vertex_ai.invoke_gemini(
        prompt=prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        multimodal_input=reference_image,
    )
    
    veo_prompt = veo_prompt_result.get("video_prompt", "")
    if not veo_prompt:
        print("Failed to make veo prompt!")
        return False
    
    # Ensure negative prompt is included for realistic character rendering
    negative_prompt = veo_prompt_result.get("negative_prompt", "")
    
    if "negative prompt" not in veo_prompt.lower():
        if negative_prompt:
            log.info(f"[Veo Prompt] Using LLM-generated negative prompt: {negative_prompt[:80]}...")
            veo_prompt = f"{veo_prompt}\n\nWith negative prompt - {negative_prompt}."
        else:
            log.info("[Veo Prompt] LLM did not return negative prompt, using default fallback")
            veo_prompt = f"{veo_prompt}\n\nWith negative prompt - {DEFAULT_NEGATIVE_PROMPT}."
    else:
        log.info("[Veo Prompt] Negative prompt already included in video prompt")
    
    print(f"Veo prompt generated: {veo_prompt}")
    return veo_prompt


def regenerate_veo_prompt_with_feedback(
    reference_image_uri: str,
    scene_script: str,
    original_prompt: str,
    failed_criteria: list
) -> str:
    """Regenerate a Veo prompt with feedback from failed evaluation.
    
    Args:
        reference_image_uri: URI of the reference image (starting frame)
        scene_script: The scene script for video generation
        original_prompt: The original prompt that failed
        failed_criteria: List of failed criteria from evaluation
        
    Returns:
        str: The improved Veo prompt, or False if failed
    """
    prompt = get_veo_prompt_with_feedback(scene_script, original_prompt, failed_criteria)
    
    reference_image = [{"uri": reference_image_uri, "mime_type": "image/png"}]
    
    veo_prompt_result = vertex_ai.invoke_gemini(
        prompt=prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        multimodal_input=reference_image,
    )
    
    veo_prompt = veo_prompt_result.get("video_prompt", "")
    if not veo_prompt:
        print("Failed to regenerate veo prompt!")
        return False
    
    # For feedback-based regeneration, always update the negative prompt
    negative_prompt = veo_prompt_result.get("negative_prompt", "")
    
    # Remove existing negative prompt if present (case-insensitive)
    if "with negative prompt" in veo_prompt.lower():
        # Split and keep only the part before "with negative prompt"
        lower_prompt = veo_prompt.lower()
        split_idx = lower_prompt.find("with negative prompt")
        veo_prompt = veo_prompt[:split_idx].strip()
        log.info("[Veo Prompt Feedback] Removed existing negative prompt for update")
    
    # Add new negative prompt (from LLM or default)
    if negative_prompt:
        log.info(f"[Veo Prompt Feedback] Using LLM-generated negative prompt: {negative_prompt[:80]}...")
        veo_prompt = f"{veo_prompt}\n\nWith negative prompt - {negative_prompt}."
    else:
        log.info("[Veo Prompt Feedback] LLM did not return negative prompt, using default fallback")
        veo_prompt = f"{veo_prompt}\n\nWith negative prompt - {DEFAULT_NEGATIVE_PROMPT}."
    
    print(f"Improved Veo prompt generated: {veo_prompt}")
    return veo_prompt


def generate_video_clips(
    reference_image_uri: str,
    veo_prompts: list,
    product_directory: str,
    aspect_ratio: str = "16:9",
    sample_count_per_prompt: int = 1
) -> dict:
    """Generate video clips using Veo for each prompt.
    
    Args:
        reference_image_uri: URI of the reference image (starting frame)
        veo_prompts: List of Veo prompts for video generation
        product_directory: Product directory path for output
        aspect_ratio: Video aspect ratio (default: "16:9")
        sample_count_per_prompt: Number of videos per prompt (default: 1)
    
    Returns:
        dict: clips_info with video results on success
        dict: {"status": "CONTENT_POLICY_VIOLATION", ...} if any prompt was rejected
        False: on other failures
    """
    base_dir = get_output_base_dir()
    gcs_prefix = get_gcs_prefix()
    directory_prefix = product_directory.split("/")[-1]
    veo_output_uri = f"gs://{settings.GCS_BUCKET_NAME}/{gcs_prefix}/output/{directory_prefix}/veo"
    veo_dir_path = f"{base_dir}/{directory_prefix}/veo"
    os.makedirs(veo_dir_path, exist_ok=True)
    
    clips_info = {}
    veo_results = []
    all_prompts = []
    content_policy_violations = []
    
    try:
        for veo_prompt in veo_prompts:
            output_uris = vertex_ai.invoke_veo_generation_sync(
                prompt=veo_prompt,
                image_uri=reference_image_uri,
                gcs_uri=veo_output_uri,
                seed=42,
                sample_count=sample_count_per_prompt,
                aspect_ratio=aspect_ratio,
                resolution=settings.VEO_DEFAULT_RESOLUTION,
            )
            
            # Handle different return types
            if isinstance(output_uris, dict):
                # Error response from Veo
                if output_uris.get("status") == "CONTENT_POLICY_VIOLATION":
                    log.warning(f"[Veo] Prompt rejected due to content policy: {veo_prompt[:100]}...")
                    content_policy_violations.append({
                        "prompt": veo_prompt,
                        "error": output_uris.get("error", "Unknown")
                    })
                    continue  # Skip this prompt, try next one
                elif output_uris.get("status") == "ERROR":
                    log.error(f"[Veo] Error generating video: {output_uris.get('error', 'Unknown')}")
                    continue  # Skip this prompt, try next one
            elif isinstance(output_uris, list):
                # Success - list of video URIs
                veo_results.extend(output_uris)
                for _ in range(len(output_uris)):
                    all_prompts.append(veo_prompt)
            elif output_uris is False:
                log.error(f"[Veo] Unexpected False return for prompt: {veo_prompt[:100]}...")
                continue
        
        # If all prompts failed due to content policy, signal for retry
        if len(content_policy_violations) > 0 and len(veo_results) == 0:
            log.error(f"All {len(content_policy_violations)} prompts were rejected due to content policy")
            return {
                "status": "CONTENT_POLICY_VIOLATION",
                "violations": content_policy_violations,
                "error": "All prompts rejected by content policy"
            }
        
        # If no videos were generated at all
        if len(veo_results) == 0:
            log.error("No videos were generated from any prompt")
            return False

        clips_info["veo_results"] = veo_results
        video_local_path_list = []
        
        for idx, veo_result in enumerate(veo_results):
            if veo_result:
                clip_key = gcs_service.extract_key_from_full_uri(veo_result)
                file_path = f"{veo_dir_path}/clip_{idx:02d}.mp4"
                video_local_path_list.append(file_path)
                gcs_service.download_file(clip_key, file_path)
                print(f"Veo video downloaded: {file_path}")
                
        clips_info["veo_local_path"] = video_local_path_list
        clips_info["prompts"] = all_prompts
        clips_info["content_policy_violations"] = content_policy_violations  # Track any partial failures
        print(f"Generated {len(video_local_path_list)} video clips")
        return clips_info
    except Exception as e:
        print(f"Error generating video clips: {e}")
        log.error(f"Exception in generate_video_clips: {e}")
        return False


def generate_video_with_evaluation_loop(
    reference_image_uri: str,
    scene_script: str,
    product_directory: str,
    max_sample_counts: int = 3,
    aspect_ratio: str = "16:9",
    original_product_image_uri: str = None
) -> dict:
    """Generate videos with evaluation-based retry loop.
    
    Generates videos one at a time, evaluates each, and stops early if all criteria pass.
    If criteria fail, regenerates prompt with feedback.
    
    Args:
        reference_image_uri: URI of the reference image (starting frame) - used for video generation
        scene_script: The scene script for video generation
        product_directory: Product directory path for output
        max_sample_counts: Maximum number of generation attempts (default: 3)
        aspect_ratio: Aspect ratio for video generation
        original_product_image_uri: URI of the original product image - used for video evaluation.
                                    If None, falls back to reference_image_uri.
        
    Returns:
        dict: clips_info with best video on success
        None: If all attempts fail evaluation criteria
    """
    base_dir = get_output_base_dir()
    gcs_prefix = get_gcs_prefix()
    directory_prefix = product_directory.split("/")[-1]
    veo_output_uri = f"gs://{settings.GCS_BUCKET_NAME}/{gcs_prefix}/output/{directory_prefix}/veo"
    veo_dir_path = f"{base_dir}/{directory_prefix}/veo"
    os.makedirs(veo_dir_path, exist_ok=True)
    
    clips_info = {
        "veo_results": [],
        "veo_local_path": [],
        "prompts": [],
        "evaluation_results": [],
        "all_passed": False,
    }
    
    last_failed_prompt = None
    last_failed_criteria = None
    reuse_prompt = None  # Track prompt to reuse for HIGH_LOAD errors
    
    for attempt in range(max_sample_counts):
        log.info(f"Video generation attempt {attempt + 1}/{max_sample_counts}")
        print(f"  🔄 Attempt {attempt + 1}/{max_sample_counts}...")
        
        # Step 1: Generate the Veo prompt (or reuse if HIGH_LOAD error occurred)
        if reuse_prompt is not None:
            # Reuse prompt from previous attempt (HIGH_LOAD error - don't regenerate)
            log.info("Reusing previous Veo prompt (HIGH_LOAD retry)...")
            veo_prompt = reuse_prompt
            reuse_prompt = None  # Clear after use
        elif attempt == 0 or last_failed_criteria is None:
            # First attempt - use original prompt generation
            log.info("Generating initial Veo prompt...")
            veo_prompt = generate_veo_prompt(reference_image_uri, scene_script)
        else:
            # Subsequent attempt with feedback - use feedback-enhanced prompt
            log.info("Generating improved Veo prompt based on evaluation feedback...")
            veo_prompt = regenerate_veo_prompt_with_feedback(
                reference_image_uri, scene_script, last_failed_prompt, last_failed_criteria
            )
        
        if not veo_prompt:
            log.error(f"Failed to generate Veo prompt on attempt {attempt + 1}")
            continue
        
        clips_info['prompts'].append(veo_prompt)
        log.info(f"Attempt {attempt + 1} Veo prompt: {veo_prompt[:200]}...")
        
        # Step 2: Generate the video
        log.info("Generating video with Veo...")
        output_uris = vertex_ai.invoke_veo_generation_sync(
            prompt=veo_prompt,
            image_uri=reference_image_uri,
            gcs_uri=veo_output_uri,
            seed=42,
            sample_count=1,
            aspect_ratio=aspect_ratio,
            resolution=settings.VEO_DEFAULT_RESOLUTION,
        )
        
        # Handle content policy violations and other errors
        if isinstance(output_uris, dict):
            if output_uris.get("status") == "CONTENT_POLICY_VIOLATION":
                log.warning(f"[Veo] Prompt rejected due to content policy on attempt {attempt + 1}")
                print(f"  ⚠️ Content policy violation, will retry with new prompt...")
                # Don't use this prompt's feedback, just regenerate
                last_failed_prompt = veo_prompt
                last_failed_criteria = [{"criterion": "content_policy", "reasoning": "Prompt was rejected by content policy"}]
                continue
            elif output_uris.get("status") == "HIGH_LOAD":
                log.warning(f"[Veo] High load error on attempt {attempt + 1}, will retry with same prompt")
                print(f"  ⏳ Service busy (high load), will retry with same prompt...")
                # Reuse the same prompt for next attempt
                reuse_prompt = veo_prompt
                continue
            elif output_uris.get("status") == "ERROR":
                log.error(f"[Veo] Error generating video: {output_uris.get('error', 'Unknown')}")
                continue
        elif not output_uris or not isinstance(output_uris, list) or len(output_uris) == 0:
            log.error(f"Failed to generate video on attempt {attempt + 1}")
            continue
        
        # Download the video
        video_uri = output_uris[0]
        clips_info['veo_results'].append(video_uri)
        
        clip_key = gcs_service.extract_key_from_full_uri(video_uri)
        file_path = f"{veo_dir_path}/clip_{attempt:02d}.mp4"
        gcs_service.download_file(clip_key, file_path)
        clips_info['veo_local_path'].append(file_path)
        log.info(f"Video saved to: {file_path}")
        
        # Step 3: Evaluate the video (latest clip only)
        log.info("Evaluating generated video...")
        # Use original product image for evaluation (to compare product consistency against the real product)
        eval_image_uri = original_product_image_uri if original_product_image_uri else reference_image_uri
        eval_result = eval_single_video(eval_image_uri, video_uri)
        
        if not eval_result:
            log.error(f"Failed to evaluate video on attempt {attempt + 1}")
            continue
        
        clips_info['evaluation_results'].append(eval_result)
        
        # Log full evaluation details
        log_evaluation_details(eval_result, attempt + 1, "video")
        
        # Step 4: Check if required criteria passed (video_technical_quality is optional)
        if check_all_criteria_passed(eval_result):
            # Check if video_technical_quality failed (for logging purposes)
            all_criteria = eval_result.get('criteria', {})
            video_quality_status = all_criteria.get('video_technical_quality', {}).get('status', 'UNKNOWN').upper()
            
            if video_quality_status != 'PASS':
                log.info(f"✅ Required criteria passed on attempt {attempt + 1} (video_technical_quality: {video_quality_status} - acceptable)")
                print(f"  ✅ Required criteria PASSED (video_technical_quality failed but acceptable)")
            else:
                log.info(f"✅ All criteria passed on attempt {attempt + 1}!")
                print(f"  ✅ All quality criteria PASSED!")
            
            clips_info['all_passed'] = True
            clips_info['init_best'] = len(clips_info['veo_results']) - 1
            return clips_info
        else:
            # Extract failed criteria for next attempt
            failed_criteria = get_failed_criteria_summary(eval_result)
            # Filter to only show required criteria that failed
            required_failed = [fc for fc in failed_criteria if fc['criterion'] in DEFAULT_REQUIRED_VIDEO_CRITERIA]
            log.info(f"❌ Some criteria failed on attempt {attempt + 1}: {[fc['criterion'] for fc in required_failed]}")
            last_failed_prompt = veo_prompt
            last_failed_criteria = failed_criteria
    
    # All attempts exhausted without passing required criteria - return partial results
    log.error(f"Video generation FAILED after {max_sample_counts} attempts - no video passed required criteria")
    print(f"  ❌ Failed to generate video passing required criteria after {max_sample_counts} attempts")
    clips_info['status'] = 'FAILED'
    clips_info['failure_reason'] = 'No video passed all quality criteria'
    # Set init_best to last attempt if we have any results (for post-processing)
    if clips_info['veo_results']:
        clips_info['init_best'] = len(clips_info['veo_results']) - 1
    else:
        clips_info['init_best'] = -1
    return clips_info
