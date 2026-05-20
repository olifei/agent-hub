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
Image-specific evaluation functions.

This module provides evaluation functions for generated images,
including starting frame evaluation and single image assessment.
"""

from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.image_prompts import get_image_eval_prompt


def eval_clip_starting_frame(starting_frame_info: dict) -> dict:
    """Evaluate all generated starting frames against quality criteria.
    
    Args:
        starting_frame_info: Dict containing input_uri, results, and product_desc
        
    Returns:
        dict: Updated starting_frame_info with evaluation results and best image index
    """
    multimodal_input = []
    for input_uri in starting_frame_info['input_uri']:
        multimodal_input.append({"uri": input_uri, "mime_type": "image/jpeg"})
    for output_uri in starting_frame_info['results']:
        multimodal_input.append({"uri": output_uri, "mime_type": "image/png"})
        
    image_eval_prompt = get_image_eval_prompt(
        starting_frame_info['product_desc'], 
        len(starting_frame_info['results'])
    )
    eval_result = vertex_ai.invoke_gemini(
        prompt=image_eval_prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.LOW,
        multimodal_input=multimodal_input
    )
    best_image_idx = eval_result.get("best", -1)
    starting_frame_info["init_best"] = best_image_idx
    starting_frame_info['evaluation_results'] = eval_result.get("evaluation_results", [])
    
    return starting_frame_info


def eval_single_image(input_uris: list, output_uri: str, product_desc: str) -> dict:
    """Evaluate a single generated image against quality criteria.
    
    Args:
        input_uris: List of reference product image URIs
        output_uri: The generated image URI to evaluate
        product_desc: Product description
        
    Returns:
        dict: Evaluation result with criteria and pass/fail status
    """
    multimodal_input = []
    for input_uri in input_uris:
        multimodal_input.append({"uri": input_uri, "mime_type": "image/jpeg"})
    multimodal_input.append({"uri": output_uri, "mime_type": "image/png"})
    
    image_eval_prompt = get_image_eval_prompt(product_desc, 1)
    eval_result = vertex_ai.invoke_gemini(
        prompt=image_eval_prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.LOW,
        multimodal_input=multimodal_input
    )
    
    evaluation_results = eval_result.get("evaluation_results", [])
    if evaluation_results:
        return evaluation_results[0]
    return None
