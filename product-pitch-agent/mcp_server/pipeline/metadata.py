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
Metadata management functions.

This module provides:
- Product metadata loading
- Pipeline metadata saving
- Processing status checks for resumability
"""

import os
import json
from datetime import datetime

from mcp_server.pipeline.config import settings
from mcp_server.pipeline.log import log
from mcp_server.pipeline.user_context import get_output_base_dir, get_gcs_prefix
from mcp_server.pipeline.gcs_service import gcs_service


def load_product_metadata(product_directory: str) -> dict:
    """Load product metadata from metadata.json file.
    
    Tries local file first, then falls back to GCS data store.
    
    Args:
        product_directory: Path to the product directory
        
    Returns:
        dict: Product metadata including country, language, product_desc
        
    Raises:
        FileNotFoundError: If metadata.json is not found locally or in GCS
        json.JSONDecodeError: If metadata.json is invalid JSON
    """
    metadata_path = f"{product_directory}/metadata.json"
    
    # Try local file first
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
                log.info(f"Loaded metadata from local: {metadata_path}")
                log.info(f"Country: {metadata.get('country')}")
                log.info(f"Language: {metadata.get('language', 'English')}")
                log.info(f"Product: {metadata.get('product_desc', '')[:60]}...")
                return metadata
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON in {metadata_path}: {e}")
            raise
    
    # Fall back to GCS data store
    directory_prefix = product_directory.split("/")[-1]
    gcs_prefix = get_gcs_prefix()
    
    # Search for metadata.json in GCS data store (may be nested under category)
    gcs_blobs = gcs_service.list_blobs_with_prefix(f"{gcs_prefix}/data/")
    metadata_blobs = [b for b in gcs_blobs if b.endswith(f"/{directory_prefix}/metadata.json")]
    
    if metadata_blobs:
        metadata = gcs_service.download_json(metadata_blobs[0])
        if metadata:
            log.info(f"Loaded metadata from GCS: {metadata_blobs[0]}")
            log.info(f"Country: {metadata.get('country')}")
            log.info(f"Language: {metadata.get('language', 'English')}")
            log.info(f"Product: {metadata.get('product_desc', '')[:60]}...")
            return metadata
    
    log.error(f"metadata.json not found locally or in GCS for {product_directory}")
    raise FileNotFoundError(f"metadata.json not found in {product_directory}")


def save_metadata(
    output_dir: str,
    input_config: dict,
    starting_frame_info: dict,
    scene_script_json: dict,
    veo_prompts: list,
    clips_info: dict,
    final_video_info: dict
) -> str:
    """Save all intermediate results to metadata.json in the output directory.
    
    Args:
        output_dir: The output directory path (e.g., temp/accessories_01/)
        input_config: Dict with company_name, product_desc, country, language
        starting_frame_info: Starting frame generation and evaluation results
        scene_script_json: Raw JSON output from scene script generation
        veo_prompts: List of video generation prompts
        clips_info: Video clips generation and evaluation results
        final_video_info: Final video post-processing results
        
    Returns:
        str: Path to saved metadata file
    """
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "input": input_config,
        "starting_frames": starting_frame_info,
        "scene_script": scene_script_json,
        "veo_prompts": veo_prompts,
        "video_clips": clips_info,
        "final_video": final_video_info
    }
    
    os.makedirs(output_dir, exist_ok=True)
    metadata_path = os.path.join(output_dir, "metadata.json")
    
    metadata_json_str = json.dumps(metadata, indent=4, ensure_ascii=False)
    
    with open(metadata_path, 'w', encoding='utf-8') as f:
        f.write(metadata_json_str)
    
    # Also upload to GCS for persistence across Cloud Run Job runs
    directory_prefix = os.path.basename(output_dir)
    gcs_prefix = get_gcs_prefix()
    gcs_metadata_key = f"{gcs_prefix}/output/{directory_prefix}/metadata.json"
    gcs_service.upload_from_string(gcs_metadata_key, metadata_json_str)
    
    log.info(f"Metadata saved to: {metadata_path} and GCS: {gcs_metadata_key}")
    print(f"\n📄 Metadata saved to: {metadata_path}")
    return metadata_path


def load_existing_metadata(output_dir: str) -> dict:
    """Load existing metadata from output directory if available.
    
    Used to check for resumable pipeline runs - if images already exist and passed
    evaluation, we can skip image generation and resume from video generation.
    
    Tries local file first, then falls back to GCS output store.
    
    Args:
        output_dir: The output directory path (e.g., output/1601442859214/)
        
    Returns:
        dict: The loaded metadata if found and valid, None otherwise
    """
    # Try local file first
    metadata_path = os.path.join(output_dir, "metadata.json")
    
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                log.info(f"Loaded existing metadata from local: {metadata_path}")
                return metadata
        except json.JSONDecodeError as e:
            log.warning(f"Failed to parse local metadata.json: {e}")
        except Exception as e:
            log.warning(f"Failed to load local metadata.json: {e}")
    
    # Fall back to GCS output store
    directory_prefix = os.path.basename(output_dir)
    gcs_prefix = get_gcs_prefix()
    gcs_metadata_key = f"{gcs_prefix}/output/{directory_prefix}/metadata.json"
    
    metadata = gcs_service.download_json(gcs_metadata_key)
    if metadata:
        log.info(f"Loaded existing metadata from GCS: {gcs_metadata_key}")
        return metadata
    
    log.info(f"No existing metadata found locally or in GCS for: {output_dir}")
    return None


def is_product_fully_processed(product_directory: str, output_base_dir: str = None) -> tuple:
    """Check if a product has already been fully processed with a final video.
    
    A product is considered fully processed when:
    1. metadata.json exists with a 'final_video' field
    2. The final video exists locally OR the GCS URI exists in metadata
    
    Checks local first, then GCS metadata.
    
    Args:
        product_directory: Path to the product folder (e.g., "data/accessories_01")
        output_base_dir: Base output directory (default: settings.TEMP_OUTPUT_DIR)
        
    Returns:
        tuple: (is_processed: bool, reason: str)
    """
    if output_base_dir is None:
        output_base_dir = get_output_base_dir()
    
    directory_prefix = product_directory.split("/")[-1]
    output_dir = os.path.join(output_base_dir, directory_prefix)
    
    # Load metadata (local → GCS fallback)
    metadata = load_existing_metadata(output_dir)
    if not metadata:
        return False, "No metadata found"
    
    # Check if final_video field exists
    final_video = metadata.get('final_video')
    if not final_video:
        return False, "No final_video in metadata"
    
    # Check local file first
    final_video_path = final_video.get('local_path')
    if final_video_path and os.path.exists(final_video_path):
        return True, f"Already processed: {final_video_path}"
    
    # Check GCS URI (for cloud runs where local files don't persist)
    gcs_uri = final_video.get('result') or final_video.get('gcs_uri')
    if gcs_uri and gcs_uri.startswith("gs://"):
        gcs_key = gcs_service.extract_key_from_full_uri(gcs_uri)
        if gcs_service.check_file_exists(gcs_key):
            return True, f"Already processed (GCS): {gcs_uri}"
    
    return False, "Final video not found locally or in GCS"


def is_product_image_processed(product_directory: str, output_base_dir: str = None) -> tuple:
    """Check if a product has already been processed with images that passed evaluation.
    
    A product's images are considered processed when:
    1. metadata.json exists with 'starting_frames' field
    2. starting_frames has 'all_passed' == True
    3. The best image exists locally OR the GCS URI exists in metadata
    
    Checks local first, then GCS metadata.
    
    Args:
        product_directory: Path to the product folder (e.g., "data/accessories_01")
        output_base_dir: Base output directory (default: settings.TEMP_OUTPUT_DIR)
        
    Returns:
        tuple: (is_processed: bool, reason: str)
    """
    if output_base_dir is None:
        output_base_dir = get_output_base_dir()
    
    directory_prefix = product_directory.split("/")[-1]
    output_dir = os.path.join(output_base_dir, directory_prefix)
    
    # Load metadata (local → GCS fallback)
    metadata = load_existing_metadata(output_dir)
    if not metadata:
        return False, "No metadata found"
    
    # Check if starting_frames field exists
    starting_frames = metadata.get('starting_frames')
    if not starting_frames:
        return False, "No starting_frames in metadata"
    
    # Check if images passed evaluation
    if not starting_frames.get('all_passed'):
        return False, "Images did not pass all evaluation criteria"
    
    # Check best image exists locally
    local_paths = starting_frames.get('local_paths', [])
    best_idx = starting_frames.get('init_best', 0)
    
    if local_paths and best_idx < len(local_paths):
        best_image_path = local_paths[best_idx]
        if os.path.exists(best_image_path):
            return True, f"Already processed: {best_image_path}"
    
    # Check GCS URIs (for cloud runs where local files don't persist)
    results = starting_frames.get('results', [])
    if results and best_idx < len(results):
        gcs_uri = results[best_idx]
        if gcs_uri and gcs_uri.startswith("gs://"):
            gcs_key = gcs_service.extract_key_from_full_uri(gcs_uri)
            if gcs_service.check_file_exists(gcs_key):
                return True, f"Already processed (GCS): {gcs_uri}"
    
    return False, "Best image not found locally or in GCS"
