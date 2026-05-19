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
Common evaluation helpers and criteria checking functions.

This module provides shared utilities for evaluating both images and videos,
including criteria validation, failure summarization, and logging.
"""

from mcp_server.pipeline.log import log


# Default required criteria for image evaluation (all 5 criteria required)
DEFAULT_REQUIRED_IMAGE_CRITERIA = [
    'product_detail_preservation',
    'character_product_alignment',
    'adherence_to_physical_laws',
    'character_realism_normality',
    'environment_context_match'
]

# Default required criteria for video evaluation (6 criteria - character_realism is critical for natural appearance)
DEFAULT_REQUIRED_VIDEO_CRITERIA = [
    'product_appearance_consistency',
    'adherence_to_physical_laws',
    'character_realism',  # NEW: Evaluates skin texture quality and lighting on face
    'environment_context_match',
    'video_technical_quality'
]


def check_all_criteria_passed(evaluation_result: dict, required_criteria: list = None) -> bool:
    """Check if all required evaluation criteria have PASS status.
    
    Args:
        evaluation_result: A single evaluation result dict containing 'criteria' field
        required_criteria: List of criterion names that must pass. 
                          If None, defaults to first 4 video criteria (excludes video_technical_quality).
                          This means videos are accepted even if only video_technical_quality fails.
        
    Returns:
        bool: True if all required criteria passed, False otherwise
    """
    if not evaluation_result or 'criteria' not in evaluation_result:
        return False
    
    if required_criteria is None:
        required_criteria = DEFAULT_REQUIRED_VIDEO_CRITERIA
    
    criteria = evaluation_result['criteria']
    for criterion_name, criterion_data in criteria.items():
        # Only check criteria that are in the required list
        if criterion_name in required_criteria:
            if criterion_data.get('status', '').upper() != 'PASS':
                return False
    return True


def get_failed_criteria_summary(evaluation_result: dict) -> list:
    """Extract a summary of failed criteria from an evaluation result.
    
    Args:
        evaluation_result: A single evaluation result dict containing 'criteria' field
        
    Returns:
        list: List of dicts with failed criterion name and reasoning
    """
    if not evaluation_result or 'criteria' not in evaluation_result:
        return []
    
    failed = []
    criteria = evaluation_result['criteria']
    for criterion_name, criterion_data in criteria.items():
        if criterion_data.get('status', '').upper() != 'PASS':
            failed.append({
                'criterion': criterion_name,
                'reasoning': criterion_data.get('reasoning', 'No reasoning provided')
            })
    return failed


def format_failed_criteria_for_prompt(failed_criteria: list) -> str:
    """Format failed criteria into a string for inclusion in regeneration prompts.
    
    Args:
        failed_criteria: List of dicts with 'criterion' and 'reasoning' keys
        
    Returns:
        str: Formatted string describing what needs to be fixed
    """
    if not failed_criteria:
        return ""
    
    lines = ["The previous generation attempt FAILED the following quality criteria:"]
    for i, fc in enumerate(failed_criteria, 1):
        criterion = fc['criterion'].replace('_', ' ').title()
        reasoning = fc['reasoning']
        lines.append(f"{i}. {criterion}: {reasoning}")
    
    lines.append("\nYou MUST address these issues in your new prompt to ensure the generated image/video passes all criteria.")
    return "\n".join(lines)


def log_evaluation_details(evaluation_result: dict, attempt_num: int, artifact_type: str = "image") -> None:
    """Log detailed evaluation results for an image or video.
    
    Args:
        evaluation_result: Dict containing 'criteria' field with evaluation details
        attempt_num: The attempt number (1-indexed)
        artifact_type: "image" or "video"
    """
    if not evaluation_result or 'criteria' not in evaluation_result:
        log.warning(f"No evaluation criteria found for {artifact_type} attempt {attempt_num}")
        return
    
    log.info(f"{'='*50}")
    log.info(f"📊 EVALUATION RESULTS - {artifact_type.upper()} Attempt {attempt_num}")
    log.info(f"{'='*50}")
    
    criteria = evaluation_result['criteria']
    all_passed = True
    
    for criterion_name, criterion_data in criteria.items():
        status = criterion_data.get('status', 'UNKNOWN').upper()
        reasoning = criterion_data.get('reasoning', 'No reasoning provided')
        
        # Format criterion name for display
        display_name = criterion_name.replace('_', ' ').title()
        
        if status == 'PASS':
            status_icon = "✅"
        else:
            status_icon = "❌"
            all_passed = False
        
        log.info(f"{status_icon} {display_name}: {status}")
        log.info(f"   → {reasoning}")
    
    overall_status = "ALL PASSED ✅" if all_passed else "SOME FAILED ❌"
    log.info(f"{'='*50}")
    log.info(f"Overall: {overall_status}")
    log.info(f"{'='*50}")
    
    # Also print to console for visibility
    print(f"\n  📊 Evaluation Details (Attempt {attempt_num}):")
    for criterion_name, criterion_data in criteria.items():
        status = criterion_data.get('status', 'UNKNOWN').upper()
        display_name = criterion_name.replace('_', ' ').title()
        status_icon = "✅" if status == 'PASS' else "❌"
        print(f"     {status_icon} {display_name}: {status}")
