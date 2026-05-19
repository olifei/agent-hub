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
Image generation functions.

This module provides:
- GCS upload utilities for product images
- Starting frame creation
- Image generation with evaluation-based retry loop
"""

import os
from PIL import Image as PIL_Image

from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.gcs_service import gcs_service
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.log import log
from mcp_server.pipeline.user_context import get_output_base_dir, get_gcs_prefix

from mcp_server.pipeline.image_prompts import (
    get_image_generation_prompt_from_product,
    get_image_prompt_with_feedback,
)
from mcp_server.pipeline.evaluator import (
    DEFAULT_REQUIRED_IMAGE_CRITERIA,
    check_all_criteria_passed,
    get_failed_criteria_summary,
    log_evaluation_details,
)
from mcp_server.pipeline.image_evaluator import eval_single_image
from mcp_server.pipeline.common_utils import crop_to_aspect_ratio


def get_product_image_uris(input_image_directory: str) -> list:
    """Get GCS URIs for product images, uploading from local if needed.
    
    First checks if product images are already available in GCS data store
    (uploaded by upload_dataset). If not, falls back to uploading from local directory.
    
    Args:
        input_image_directory: Path to local directory containing images,
                               or the product directory identifier
        
    Returns:
        list: List of GCS URIs for product images
    """
    directory_prefix = input_image_directory.split("/")[-1]
    gcs_prefix = get_gcs_prefix()
    
    # First, check if images exist in GCS data store (uploaded by upload_dataset)
    # Try both flat and category-nested patterns
    gcs_data_uris = gcs_service.get_product_image_uris(f"{gcs_prefix}/data/")
    # Filter to only images under this product's prefix
    product_data_uris = [
        uri for uri in gcs_data_uris 
        if f"/{directory_prefix}/" in uri
    ]
    
    if product_data_uris:
        log.info(f"Found {len(product_data_uris)} product image(s) in GCS data store")
        return product_data_uris
    
    # Also check the legacy upload/ prefix (from previous runs)
    legacy_prefix = f"{gcs_prefix}/upload/{directory_prefix}/"
    legacy_uris = gcs_service.get_product_image_uris(legacy_prefix)
    if legacy_uris:
        log.info(f"Found {len(legacy_uris)} product image(s) in GCS upload prefix (legacy)")
        return legacy_uris
    
    # Fall back to uploading from local directory
    if os.path.isdir(input_image_directory):
        log.info(f"Uploading product images from local directory: {input_image_directory}")
        return _upload_directory_to_gcs(input_image_directory)
    
    log.error(f"No product images found in GCS or locally for: {input_image_directory}")
    return []


def _upload_directory_to_gcs(local_directory: str) -> list:
    """Upload only image files from directory to GCS, skip metadata.json and other non-image files.
    
    This is the fallback path for local development when images haven't been
    uploaded to GCS data store via upload_dataset.
    
    Args:
        local_directory: Path to local directory containing images
        
    Returns:
        list: List of GCS URIs for uploaded images
    """
    directory_prefix = local_directory.split("/")[-1]
    upload_files = sorted(os.listdir(local_directory))
    upload_uris = []
    gcs_prefix = get_gcs_prefix()
    
    # Valid image extensions
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    
    for upload_file in upload_files:
        # Skip metadata.json and non-image files
        file_ext = os.path.splitext(upload_file)[1].lower()
        if file_ext not in image_extensions:
            log.info(f"Skipping non-image file: {upload_file}")
            continue
            
        gcs_service.upload_file(
            local_file_path=local_directory + "/" + upload_file,
            remote_file_path=gcs_prefix + "/upload/" + directory_prefix + "/" + upload_file
        )
        upload_uris.append(
            "gs://" + settings.GCS_BUCKET_NAME + "/" + gcs_prefix + "/upload/" + directory_prefix + "/" + upload_file
        )
    
    log.info(f"Uploaded {len(upload_uris)} image(s) to GCS")
    return upload_uris


def create_clip_starting_frame(
    input_image_directory: str,
    country: str,
    product_desc: str,
    sub_output_dir: str = 'ref_image_gen',
    num_of_images: int = 2,
    aspect_ratio: str = '16:9'
) -> dict:
    """Create starting frame images for video clips.
    
    Generates multiple images using different prompts for variety.
    After generation, images are cropped to exact aspect ratio to prevent black bars in video.
    
    Args:
        input_image_directory: Directory containing reference product images
        country: Target country for the advertisement
        product_desc: Product description
        sub_output_dir: Subdirectory for output images
        num_of_images: Number of images to generate
        aspect_ratio: Target aspect ratio for generated images (default: "16:9")
                      Supports "16:9" (landscape) and "9:16" (portrait)
        
    Returns:
        dict: Starting frame info with input URIs, prompts, results, and local paths
    """
    base_dir = get_output_base_dir()
    gcs_prefix = get_gcs_prefix()
    directory_prefix = input_image_directory.split("/")[-1]
    upload_image_uris = get_product_image_uris(input_image_directory)
    log.info(upload_image_uris)
    
    multimodal_input = []
    for upload_image_uri in upload_image_uris:
        multimodal_input.append({"uri": upload_image_uri, "mime_type": "image/jpeg"})
    
    starting_frame_info = {
        "input_uri": upload_image_uris,
        "product_desc": product_desc,
        "country": country,
        "prompts": [],
        "results": [],
        "local_paths": [],
    }
    
    # Generate images - each iteration gets a different prompt for variety
    for image_idx in range(num_of_images):
        # Step 1: Get a new image editing prompt from Gemini (TEXT response)
        log.info(f"Generating edit prompt for image {image_idx+1}/{num_of_images}...")
        image_edit_prompt_response = vertex_ai.invoke_gemini(
            prompt=get_image_generation_prompt_from_product(country, product_desc),
            model_type=GeminiModelType.PRO,
            creativity=GeminiCreativityLevel.MEDIUM,
            multimodal_input=multimodal_input,
        )
        
        # Extract the actual image generation prompt from JSON
        image_edit_prompt = image_edit_prompt_response.get("Prompt for image editing", "")
        starting_frame_info['prompts'].append(image_edit_prompt)
        log.info(f"Image {image_idx+1} edit prompt: {image_edit_prompt}")
        
        # Step 2: Generate image using the extracted prompt
        log.info(f"Generating image {image_idx+1} with Gemini IMAGE model (target aspect ratio: {aspect_ratio})...")
        generated_image = vertex_ai.invoke_gemini(
            prompt=image_edit_prompt,
            model_type=GeminiModelType.IMAGE,
            creativity=GeminiCreativityLevel.MEDIUM,
            multimodal_input=multimodal_input,
            response_modalities=['IMAGE'],
            image_config_dict={'aspect_ratio': aspect_ratio, 'image_size': settings.IMAGE_RESOLUTION}
        )
        
        # Set up output paths
        output_dir = f"{base_dir}/{directory_prefix}/{sub_output_dir}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Save the raw/original image for logging purposes (before any corrections)
        # Note: generated_image is a Gemini Image object, save it first then reload as PIL
        raw_output_file = f"image_{image_idx+1:02d}_raw.png"
        raw_output_path = f"{output_dir}/{raw_output_file}"
        generated_image.save(raw_output_path)
        
        # Reload as PIL Image to get size and apply corrections
        pil_image = PIL_Image.open(raw_output_path)
        raw_width, raw_height = pil_image.size
        log.info(f"[RAW] Saved: {raw_output_path} | Size: {raw_width}x{raw_height} | Ratio: {raw_width/raw_height:.4f}")
        
        # Step 2.5: Apply aspect ratio correction to ensure exact ratio
        log.info(f"Applying aspect ratio correction to ensure exact {aspect_ratio} ratio...")
        corrected_image = crop_to_aspect_ratio(pil_image, target_aspect_ratio=aspect_ratio)
        
        output_file = f"image_{image_idx+1:02d}.png"
        output_path = f"{output_dir}/{output_file}"
        corrected_image.save(output_path)
        corr_width, corr_height = corrected_image.size
        log.info(f"[CORRECTED] Saved: {output_path} | Size: {corr_width}x{corr_height} | Ratio: {corr_width/corr_height:.4f}")
        remote_path = gcs_prefix + "/output/" + directory_prefix + "/" + sub_output_dir + "/" + output_file
        gcs_service.upload_file(output_path, remote_path, replace=True)
        
        starting_frame_info['results'].append("gs://" + settings.GCS_BUCKET_NAME + "/" + remote_path)
        starting_frame_info['local_paths'].append(output_path)
        log.info(f"Image {image_idx+1} saved to: {output_path}")
        
    return starting_frame_info


def generate_image_with_evaluation_loop(
    input_image_directory: str,
    country: str,
    product_desc: str,
    max_sample_counts: int = 3,
    sub_output_dir: str = 'ref_image_gen',
    aspect_ratio: str = '16:9'
) -> dict:
    """Generate images with evaluation-based retry loop.
    
    Generates images one at a time, evaluates each, and stops early if all criteria pass.
    If criteria fail, regenerates with feedback-enhanced prompts.
    After generation, images are cropped to exact aspect ratio to prevent black bars in video.
    
    Args:
        input_image_directory: Directory containing reference product images
        country: Target country for the advertisement
        product_desc: Product description
        max_sample_counts: Maximum number of generation attempts (default: 3)
        sub_output_dir: Subdirectory for output images
        aspect_ratio: Target aspect ratio for generated images (default: "16:9")
                      Supports "16:9" (landscape) and "9:16" (portrait)
        
    Returns:
        dict: starting_frame_info with best image on success
        None: If all attempts fail evaluation criteria
    """
    base_dir = get_output_base_dir()
    gcs_prefix = get_gcs_prefix()
    directory_prefix = input_image_directory.split("/")[-1]
    upload_image_uris = get_product_image_uris(input_image_directory)
    log.info(upload_image_uris)
    
    multimodal_input = []
    for upload_image_uri in upload_image_uris:
        multimodal_input.append({"uri": upload_image_uri, "mime_type": "image/jpeg"})
    
    starting_frame_info = {
        "input_uri": upload_image_uris,
        "product_desc": product_desc,
        "country": country,
        "prompts": [],
        "results": [],
        "local_paths": [],
        "evaluation_results": [],
        "all_passed": False,
    }
    
    last_failed_prompt = None
    last_failed_criteria = None
    
    for attempt in range(max_sample_counts):
        log.info(f"Image generation attempt {attempt + 1}/{max_sample_counts}")
        print(f"  🔄 Attempt {attempt + 1}/{max_sample_counts}...")
        
        # Step 1: Generate the image editing prompt
        if attempt == 0 or last_failed_criteria is None:
            # First attempt or no feedback - use original prompt
            log.info("Generating initial edit prompt...")
            image_edit_prompt_response = vertex_ai.invoke_gemini(
                prompt=get_image_generation_prompt_from_product(country, product_desc),
                model_type=GeminiModelType.PRO,
                creativity=GeminiCreativityLevel.MEDIUM,
                multimodal_input=multimodal_input,
            )
        else:
            # Subsequent attempt with feedback - use feedback-enhanced prompt
            log.info("Generating improved edit prompt based on evaluation feedback...")
            image_edit_prompt_response = vertex_ai.invoke_gemini(
                prompt=get_image_prompt_with_feedback(country, product_desc, last_failed_prompt, last_failed_criteria),
                model_type=GeminiModelType.PRO,
                creativity=GeminiCreativityLevel.MEDIUM,
                multimodal_input=multimodal_input,
            )
        
        if not image_edit_prompt_response:
            log.error(f"Failed to generate image edit prompt on attempt {attempt + 1}")
            continue
        
        image_edit_prompt = image_edit_prompt_response.get("Prompt for image editing", "")
        if not image_edit_prompt:
            log.error(f"Empty image edit prompt on attempt {attempt + 1}")
            continue
            
        starting_frame_info['prompts'].append(image_edit_prompt)
        log.info(f"Attempt {attempt + 1} edit prompt: {image_edit_prompt}")
        
        # Step 2: Generate the image
        log.info(f"Generating image with Gemini IMAGE model (target aspect ratio: {aspect_ratio})...")
        generated_image = vertex_ai.invoke_gemini(
            prompt=image_edit_prompt,
            model_type=GeminiModelType.IMAGE,
            creativity=GeminiCreativityLevel.MEDIUM,
            multimodal_input=multimodal_input,
            response_modalities=['IMAGE'],
            image_config_dict={'aspect_ratio': aspect_ratio, 'image_size': settings.IMAGE_RESOLUTION}
        )
        
        if not generated_image:
            log.error(f"Failed to generate image on attempt {attempt + 1}")
            continue
        
        # Set up output paths
        output_dir = f"{base_dir}/{directory_prefix}/{sub_output_dir}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Save the raw/original image for logging purposes (before any corrections)
        # Note: generated_image is a Gemini Image object, save it first then reload as PIL
        raw_output_file = f"image_{attempt:02d}_raw.png"
        raw_output_path = f"{output_dir}/{raw_output_file}"
        generated_image.save(raw_output_path)
        
        # Reload as PIL Image to get size and apply corrections
        pil_image = PIL_Image.open(raw_output_path)
        raw_width, raw_height = pil_image.size
        log.info(f"[RAW] Saved: {raw_output_path} | Size: {raw_width}x{raw_height} | Ratio: {raw_width/raw_height:.4f}")
        
        # Step 2.5: Apply aspect ratio correction to ensure exact ratio
        # This prevents black bars in the final video by center-cropping to exact ratio
        log.info(f"Applying aspect ratio correction to ensure exact {aspect_ratio} ratio...")
        corrected_image = crop_to_aspect_ratio(pil_image, target_aspect_ratio=aspect_ratio)
        
        # Save the corrected image (0-indexed naming: image_00, image_01, ...)
        output_file = f"image_{attempt:02d}.png"
        output_path = f"{output_dir}/{output_file}"
        corrected_image.save(output_path)
        corr_width, corr_height = corrected_image.size
        log.info(f"[CORRECTED] Saved: {output_path} | Size: {corr_width}x{corr_height} | Ratio: {corr_width/corr_height:.4f}")
        remote_path = gcs_prefix + "/output/" + directory_prefix + "/" + sub_output_dir + "/" + output_file
        gcs_service.upload_file(output_path, remote_path, replace=True)
        
        output_uri = "gs://" + settings.GCS_BUCKET_NAME + "/" + remote_path
        starting_frame_info['results'].append(output_uri)
        starting_frame_info['local_paths'].append(output_path)
        log.info(f"Image saved to: {output_path}")
        
        # Step 3: Evaluate the image
        log.info("Evaluating generated image...")
        eval_result = eval_single_image(upload_image_uris, output_uri, product_desc)
        
        if not eval_result:
            log.error(f"Failed to evaluate image on attempt {attempt + 1}")
            continue
        
        starting_frame_info['evaluation_results'].append(eval_result)
        
        # Log full evaluation details
        log_evaluation_details(eval_result, attempt + 1, "image")
        
        # Step 4: Check if all criteria passed (use image-specific criteria)
        if check_all_criteria_passed(eval_result, required_criteria=DEFAULT_REQUIRED_IMAGE_CRITERIA):
            log.info(f"✅ All image criteria passed on attempt {attempt + 1}!")
            print(f"  ✅ All quality criteria PASSED!")
            starting_frame_info['all_passed'] = True
            starting_frame_info['init_best'] = len(starting_frame_info['results']) - 1
            return starting_frame_info
        else:
            # Extract failed criteria for next attempt
            failed_criteria = get_failed_criteria_summary(eval_result)
            log.info(f"❌ Some criteria failed on attempt {attempt + 1}: {[fc['criterion'] for fc in failed_criteria]}")
            last_failed_prompt = image_edit_prompt
            last_failed_criteria = failed_criteria
    
    # All attempts exhausted without passing all criteria - return partial results
    log.error(f"Image generation FAILED after {max_sample_counts} attempts - no image passed all criteria")
    print(f"  ❌ Failed to generate image passing all criteria after {max_sample_counts} attempts")
    starting_frame_info['status'] = 'FAILED'
    starting_frame_info['failure_reason'] = 'No image passed all quality criteria'
    starting_frame_info['init_best'] = -1
    return starting_frame_info
