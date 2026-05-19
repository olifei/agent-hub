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
Video-specific evaluation functions.

This module provides evaluation functions for generated videos,
including multi-video evaluation and single video assessment.
"""

from typing import Optional
from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.video_prompts import get_video_eval_prompt


def eval_video(
    reference_image_uri: str, 
    clips_info: dict,
    video_fps: Optional[int] = None
) -> dict:
    """Evaluate all generated video clips against quality criteria.
    
    Args:
        reference_image_uri: URI of the reference image (product image or starting frame)
        clips_info: Dict containing veo_results list of video URIs
        video_fps: Optional FPS for video sampling (default: settings.VIDEO_EVAL_FPS). 
                   Lower values reduce token usage. Set to None to use full video.
        
    Returns:
        dict: Updated clips_info with evaluation results and best video index
        False: If evaluation fails
    """
    # Apply default from settings
    if video_fps is None:
        video_fps = settings.VIDEO_EVAL_FPS
    try:
        # Detect mime type based on file extension
        ref_ext = reference_image_uri.lower().split('.')[-1]
        ref_mime_type = "image/jpeg" if ref_ext in ['jpg', 'jpeg'] else "image/png"
        
        multimodal_list = [{"uri": reference_image_uri, "mime_type": ref_mime_type}]
        veo_results = clips_info["veo_results"]
        
        for clip_uri in veo_results:
            if clip_uri:
                video_input = {"uri": clip_uri, "mime_type": "video/mp4"}
                if video_fps is not None:
                    video_input["fps"] = video_fps
                multimodal_list.append(video_input)
        
        if multimodal_list:
            clips_eval_result = vertex_ai.invoke_gemini(
                prompt=get_video_eval_prompt(len(veo_results)),
                model_type=GeminiModelType.PRO,
                creativity=GeminiCreativityLevel.MEDIUM,
                multimodal_input=multimodal_list,
            )
        
        print("Video evaluation complete")
        best_clip_idx = clips_eval_result.get("best", -1)
        clips_info["init_best"] = best_clip_idx
        clips_info["evaluation_results"] = clips_eval_result.get("evaluation_results", [])
        
        return clips_info
    except Exception as e:
        print(f"Error evaluating videos: {e}")
        return False


def eval_single_video(
    reference_image_uri: str, 
    video_uri: str,
    video_fps: Optional[int] = None
) -> dict:
    """Evaluate a single generated video against quality criteria.
    
    Args:
        reference_image_uri: The reference image URI (starting frame or original product image)
        video_uri: The generated video URI to evaluate
        video_fps: Optional FPS for video sampling (default: settings.VIDEO_EVAL_FPS). 
                   Lower values reduce token usage. Set to None to use full video.
        
    Returns:
        dict: Evaluation result with criteria and pass/fail status
        None: If evaluation fails
    """
    # Apply default from settings
    if video_fps is None:
        video_fps = settings.VIDEO_EVAL_FPS
    
    # Detect mime type based on file extension
    ref_ext = reference_image_uri.lower().split('.')[-1]
    ref_mime_type = "image/jpeg" if ref_ext in ['jpg', 'jpeg'] else "image/png"
    
    video_input = {"uri": video_uri, "mime_type": "video/mp4"}
    if video_fps is not None:
        video_input["fps"] = video_fps
    
    multimodal_list = [
        {"uri": reference_image_uri, "mime_type": ref_mime_type},
        video_input
    ]
    
    eval_result = vertex_ai.invoke_gemini(
        prompt=get_video_eval_prompt(1),
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        multimodal_input=multimodal_list,
    )
    
    evaluation_results = eval_result.get("evaluation_results", [])
    if evaluation_results:
        return evaluation_results[0]
    return None
