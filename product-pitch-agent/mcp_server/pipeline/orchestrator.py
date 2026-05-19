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
Pipeline orchestration functions.

This module provides:
- Single product processing (full pipeline and image-only)
- Batch processing with parallel execution
- Product directory discovery
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from mcp_server.pipeline.config import settings
from mcp_server.pipeline.log import log
from mcp_server.pipeline.user_context import get_output_base_dir, get_user_id, set_user_id, get_gcs_prefix
from mcp_server.pipeline.gcs_service import gcs_service

from mcp_server.pipeline.metadata import (
    load_product_metadata,
    save_metadata,
    load_existing_metadata,
    is_product_fully_processed,
    is_product_image_processed,
)
from mcp_server.pipeline.image_generator import generate_image_with_evaluation_loop
from mcp_server.pipeline.video_generator import generate_video_with_evaluation_loop
from mcp_server.pipeline.scene_script import generate_scene_script
from mcp_server.pipeline.video_postprocess import edit_video_with_best_end_frame


def get_all_product_directories(data_dir: str = None) -> list:
    """Discover all product subfolders under the data directory.

    GCS is the sole source of truth — local filesystem is never consulted.
    Cloud Run instances have ephemeral per-container disks, so a local-first
    lookup returns whatever happens to be cached on the instance answering
    the request and hides products uploaded elsewhere.

    Args:
        data_dir: The root data directory prefix (default: settings.DEFAULT_DATA_DIR)

    Returns:
        List of product directory paths (e.g., ["data/accessories_01", "data/bags_01"])
    """
    if data_dir is None:
        data_dir = settings.DEFAULT_DATA_DIR

    gcs_prefix = get_gcs_prefix()
    gcs_data_prefix = f"{gcs_prefix}/data/"
    all_blobs = gcs_service.list_blobs_with_prefix(gcs_data_prefix)
    metadata_blobs = [b for b in all_blobs if b.endswith("/metadata.json")]

    product_dirs = []
    for blob_name in sorted(metadata_blobs):
        relative = blob_name[len(gcs_data_prefix):]
        product_path = relative.rsplit("/metadata.json", 1)[0]
        synthetic_dir = os.path.join(data_dir, product_path)
        product_dirs.append(synthetic_dir)
        log.info(f"Found product in GCS: {synthetic_dir} (from {blob_name})")

    log.info(f"Found {len(product_dirs)} product directories in GCS data store")
    return product_dirs


def process_product_image_only(
    product_directory: str,
    company_name: str = None,
    max_sample_images: int = None,
    force: bool = False,
    aspect_ratio: str = "16:9"
) -> dict:
    """Process a single product directory to generate only the starting frame image.
    
    Uses dynamic evaluation-based retry loop for image generation only.
    Skips video generation and post-processing.
    Skips already processed products unless force=True.
    
    Args:
        product_directory: Path to the product folder (e.g., "data/accessories_01")
         company_name: Company name for branding. If None, reads from product
            metadata.json "company_name" field, falling back to settings default.
        max_sample_images: Maximum generation attempts for images (default: 3)
        force: If True, reprocess even if already completed (default: False)
        aspect_ratio: Target aspect ratio - "16:9" or "9:16" (default: "16:9")
        
    Returns:
        dict: Pipeline results including generated image paths, or None if failed
        dict with 'skipped': True if product was already processed and skipped
    """
    # Apply defaults from settings
    # company_name resolved after metadata load (per-product dynamic)
    if max_sample_images is None:
        max_sample_images = settings.MAX_SAMPLE_IMAGES
    
    directory_prefix = product_directory.split("/")[-1]
    output_dir = f"{get_output_base_dir()}/{directory_prefix}"
    
    # Check if already processed (unless force=True)
    if not force:
        is_processed, reason = is_product_image_processed(product_directory)
        if is_processed:
            print("\n" + "=" * 60)
            print(f"⏭️  SKIPPING (already processed): {product_directory}")
            print("=" * 60)
            print(f"   Reason: {reason}")
            print(f"   Use --force to reprocess")
            log.info(f"Skipping already processed product (image): {product_directory} - {reason}")
            return {
                "skipped": True,
                "product_directory": product_directory,
                "reason": reason
            }
    
    print("\n" + "=" * 60)
    print(f"🖼️  PROCESSING (IMAGE ONLY): {product_directory}")
    print("=" * 60)
    print(f"Max image attempts: {max_sample_images}")
    
    # Clean previous GCS output for this product before re-generating
    gcs_output_prefix = f"{get_gcs_prefix()}/output/{directory_prefix}/"
    log.info(f"Cleaning previous GCS output: {gcs_output_prefix}")
    gcs_service.delete_prefix(gcs_output_prefix)
    
    # Initialize variables for metadata saving
    starting_frame_info = None
    
    # Load metadata for this product
    try:
        metadata = load_product_metadata(product_directory)
        country = metadata['country']
        product_desc = metadata['product_desc']
        speech_language = metadata.get('language', 'English')
        # Dynamic company_name: parameter override > metadata > settings default
        if company_name is None:
            company_name = metadata.get('company_name', settings.DEFAULT_COMPANY_NAME)
    except Exception as e:
        log.error(f"Failed to load metadata for {product_directory}: {e}")
        return None
    
    input_config = {
        "company_name": company_name,
        "product_desc": product_desc,
        "country": country,
        "language": speech_language,
        "max_sample_images": max_sample_images,
        "mode": "image_only"
    }
    
    # Step 1: Generate Starting Frame Image with Evaluation Loop
    print("\n" + "-" * 40)
    print("STEP 1: Generating Starting Frame Image (with evaluation loop)")
    print("-" * 40)
    starting_frame_info = generate_image_with_evaluation_loop(
        input_image_directory=product_directory,
        country=country,
        product_desc=product_desc,
        max_sample_counts=max_sample_images,
        aspect_ratio=aspect_ratio
    )
    
    # Check if image generation failed completely
    if not starting_frame_info or not starting_frame_info.get('results'):
        log.error(f"❌ Image generation FAILED for {product_directory} - no images generated")
        print(f"\n❌ FAILED: Could not generate any images")
        # Save partial metadata
        save_metadata(output_dir, input_config, starting_frame_info, None, [], None, None)
        return None
    
    # Check if image passed all criteria or not
    if starting_frame_info.get('status') == 'FAILED':
        log.warning(f"⚠️ Image generation did not pass all criteria")
        print(f"  ⚠️ No image passed all criteria, using best available")
    
    best_image_idx = starting_frame_info.get("init_best", -1)
    print(f"✅ Best image index: {best_image_idx}")
    print(f"   Best image path: {starting_frame_info['local_paths'][best_image_idx]}")

    # Step 2: Save Metadata (image only mode)
    print("\n" + "-" * 40)
    print("STEP 2: Saving Metadata")
    print("-" * 40)
    save_metadata(
        output_dir=output_dir,
        input_config=input_config,
        starting_frame_info=starting_frame_info,
        scene_script_json=None,
        veo_prompts=[],
        clips_info=None,
        final_video_info=None
    )

    # Summary for this product
    print("\n" + "=" * 60)
    print(f"✅ COMPLETED (IMAGE ONLY): {product_directory}")
    print("=" * 60)
    print(f"  • Product: {product_desc[:50]}...")
    print(f"  • Country: {country}")
    print(f"  • Generated Images: {len(starting_frame_info['local_paths'])}")
    for i, path in enumerate(starting_frame_info['local_paths']):
        print(f"    - Image {i}: {path}")
    print(f"  • Best Image: {starting_frame_info['local_paths'][best_image_idx]}")
    
    return {
        "product_directory": product_directory,
        "product_desc": product_desc,
        "country": country,
        "best_image": starting_frame_info['local_paths'][best_image_idx],
        "all_images": starting_frame_info['local_paths'],
        "metadata_path": f"{output_dir}/metadata.json"
    }


def process_product(
    product_directory: str,
    company_name: str = None,
    max_sample_images: int = None,
    max_sample_clips: int = None,
    force: bool = False,
    aspect_ratio: str = "16:9"
) -> dict:
    """Process a single product directory through the entire video generation pipeline.
    
    Uses dynamic evaluation-based retry loops for both image and video generation.
    Always saves metadata even on failure.
    Supports resuming from video generation if images already exist and passed evaluation.
    Skips already fully processed products unless force=True.
    
    Args:
        product_directory: Path to the product folder (e.g., "data/accessories_01")
        company_name: Company name for branding. If None, reads from product
            metadata.json "company_name" field, falling back to settings default.
        max_sample_images: Maximum generation attempts for images (default: 3)
        max_sample_clips: Maximum generation attempts for video clips (default: 3)
        force: If True, reprocess even if already completed (default: False)
        aspect_ratio: Target aspect ratio for images and video (default: "16:9")
                      Supports "16:9" (landscape) and "9:16" (portrait)
        
    Returns:
        dict: Pipeline results including final video path, or None if failed
        dict with 'skipped': True if product was already processed and skipped
    """
    # Apply defaults from settings
    # company_name resolved after metadata load (per-product dynamic)
    if max_sample_images is None:
        max_sample_images = settings.MAX_SAMPLE_IMAGES
    if max_sample_clips is None:
        max_sample_clips = settings.MAX_SAMPLE_CLIPS
    
    directory_prefix = product_directory.split("/")[-1]
    output_dir = f"{get_output_base_dir()}/{directory_prefix}"
    
    # Check if already fully processed (unless force=True)
    if not force:
        is_processed, reason = is_product_fully_processed(product_directory)
        if is_processed:
            print("\n" + "=" * 60)
            print(f"⏭️  SKIPPING (already processed): {product_directory}")
            print("=" * 60)
            print(f"   Reason: {reason}")
            print(f"   Use --force to reprocess")
            log.info(f"Skipping already processed product: {product_directory} - {reason}")
            return {
                "skipped": True,
                "product_directory": product_directory,
                "reason": reason
            }
    
    print("\n" + "=" * 60)
    print(f"🚀 PROCESSING: {product_directory}")
    print("=" * 60)
    print(f"Max image attempts: {max_sample_images}, Max clip attempts: {max_sample_clips}")

    gcs_output_prefix = f"{get_gcs_prefix()}/output/{directory_prefix}/"

    # Initialize variables for metadata saving
    starting_frame_info = None
    scene_script_json = None
    clips_info = None
    final_video_info = None
    resume_from_video = False
    
    # Load metadata for this product
    try:
        metadata = load_product_metadata(product_directory)
        country = metadata['country']
        product_desc = metadata['product_desc']
        speech_language = metadata.get('language', 'English')
        # Dynamic company_name: parameter override > metadata > settings default
        if company_name is None:
            company_name = metadata.get('company_name', settings.DEFAULT_COMPANY_NAME)
    except Exception as e:
        log.error(f"Failed to load metadata for {product_directory}: {e}")
        return None
    
    input_config = {
        "company_name": company_name,
        "product_desc": product_desc,
        "country": country,
        "language": speech_language,
        "max_sample_images": max_sample_images,
        "max_sample_clips": max_sample_clips
    }
    
    # Check for existing metadata to potentially resume from video generation
    print("\n" + "-" * 40)
    print("Checking for existing images...")
    print("-" * 40)
    existing_metadata = load_existing_metadata(output_dir)
    
    if existing_metadata:
        existing_starting_frames = existing_metadata.get('starting_frames')
        
        # Check if images exist and all_passed == True
        if (existing_starting_frames 
            and existing_starting_frames.get('results') 
            and existing_starting_frames.get('all_passed') == True):
            
            # Try local files first, then GCS URIs
            local_paths = existing_starting_frames.get('local_paths', [])
            best_idx = existing_starting_frames.get('init_best', 0)
            results = existing_starting_frames.get('results', [])
            
            if local_paths and best_idx < len(local_paths) and os.path.exists(local_paths[best_idx]):
                # Local files exist - use them directly
                print(f"✅ Found existing images that passed evaluation!")
                print(f"   Best image: {local_paths[best_idx]}")
                print(f"   ⏭️  Skipping image generation, resuming from video generation...")
                
                starting_frame_info = existing_starting_frames
                resume_from_video = True
                log.info(f"Resuming from video generation - using existing local images from {output_dir}")
            elif results and best_idx < len(results) and results[best_idx].startswith("gs://"):
                # Local files missing but GCS URIs exist - can still resume
                # The image GCS URI is all we need for video generation (Gemini/Veo use GCS URIs)
                gcs_key = gcs_service.extract_key_from_full_uri(results[best_idx])
                if gcs_service.check_file_exists(gcs_key):
                    print(f"✅ Found existing images in GCS that passed evaluation!")
                    print(f"   Best image (GCS): {results[best_idx]}")
                    print(f"   ⏭️  Skipping image generation, resuming from video generation...")
                    
                    starting_frame_info = existing_starting_frames
                    resume_from_video = True
                    log.info(f"Resuming from video generation - using existing GCS images")
                else:
                    print(f"⚠️ GCS image not found either, regenerating images...")
                    log.warning(f"GCS image not found: {results[best_idx]}")
            else:
                print(f"⚠️ Existing image files not found locally or in GCS, regenerating...")
                log.warning(f"Image files missing locally and in GCS, will regenerate")
        else:
            if existing_starting_frames and not existing_starting_frames.get('all_passed'):
                print(f"⚠️ Previous images did not pass evaluation, regenerating...")
            else:
                print(f"⚠️ No valid existing images found, generating new images...")
    else:
        print("No existing metadata found, starting fresh...")
    
    # Step 1: Generate Starting Frame Image with Evaluation Loop (skip if resuming)
    if not resume_from_video:
        # Clean previous GCS output only when actually regenerating, so we don't
        # wipe the metadata.json that the resume path above depends on.
        log.info(f"Cleaning previous GCS output: {gcs_output_prefix}")
        gcs_service.delete_prefix(gcs_output_prefix)

        print("\n" + "-" * 40)
        print("STEP 1: Generating Starting Frame Image (with evaluation loop)")
        print("-" * 40)
        starting_frame_info = generate_image_with_evaluation_loop(
            input_image_directory=product_directory,
            country=country,
            product_desc=product_desc,
            max_sample_counts=max_sample_images,
            aspect_ratio=aspect_ratio
        )
        
        # Check if image generation failed completely
        if not starting_frame_info or not starting_frame_info.get('results'):
            log.error(f"❌ Image generation FAILED for {product_directory} - no images generated")
            print(f"\n❌ FAILED: Could not generate any images")
            # Save partial metadata and return
            save_metadata(output_dir, input_config, starting_frame_info, scene_script_json, [], clips_info, final_video_info)
            return None
        
        # Check if image passed all criteria or not
        if starting_frame_info.get('status') == 'FAILED':
            log.warning(f"⚠️ Image generation did not pass all criteria, continuing with best available")
            print(f"  ⚠️ No image passed all criteria, using best available")
    else:
        print("\n" + "-" * 40)
        print("STEP 1: ⏭️  Skipped (using existing images)")
        print("-" * 40)
    
    best_image_idx = starting_frame_info.get("init_best", 0)
    print(f"✅ Best image index: {best_image_idx}")
    print(f"   Best image path: {starting_frame_info['local_paths'][best_image_idx]}")

    # Step 2: Generate Scene Script Dynamically
    print("\n" + "-" * 40)
    print("STEP 2: Generating Scene Script from Best Image")
    print("-" * 40)
    best_image_uri = starting_frame_info['results'][best_image_idx]
    scene_script, scene_script_json = generate_scene_script(
        reference_image_uri=best_image_uri,
        company_name=company_name,
        product_desc=product_desc,
        country=country,
        speech_language=speech_language
    )
    if not scene_script:
        log.error(f"Failed to generate scene script for {product_directory}")
        # Save partial metadata and return
        save_metadata(output_dir, input_config, starting_frame_info, scene_script_json, [], clips_info, final_video_info)
        return None
    print(f"✅ Scene script generated successfully")

    # Step 3: Generate Video Clip with Evaluation Loop
    print("\n" + "-" * 40)
    print("STEP 3: Generating Video Clip (with evaluation loop)")
    print("-" * 40)
    print("This may take several minutes per attempt...")
    
    # Get the original product image URI for video evaluation
    # This ensures the video is evaluated against the real product, not the generated image
    original_product_image_uri = starting_frame_info['input_uri'][0] if starting_frame_info.get('input_uri') else None
    
    clips_info = generate_video_with_evaluation_loop(
        reference_image_uri=best_image_uri,
        scene_script=scene_script,
        product_directory=product_directory,
        max_sample_counts=max_sample_clips,
        aspect_ratio=aspect_ratio,
        original_product_image_uri=original_product_image_uri
    )
    
    # Check if video generation failed completely
    if not clips_info or not clips_info.get('veo_results'):
        log.error(f"❌ Video generation FAILED for {product_directory} - no videos generated")
        print(f"\n❌ FAILED: Could not generate any videos")
        # Save partial metadata and return
        save_metadata(output_dir, input_config, starting_frame_info, scene_script_json, 
                      clips_info.get('prompts', []) if clips_info else [], clips_info, final_video_info)
        return None
    
    # Check if video passed all criteria or not
    if clips_info.get('status') == 'FAILED':
        # All video attempts failed - still proceed with post-processing using the last clip
        log.warning(f"⚠️ All video attempts FAILED for {product_directory} - proceeding with post-processing using last clip")
        print(f"\n" + "-" * 40)
        print("⚠️ All video attempts failed evaluation - using last clip for post-processing")
        print("-" * 40)
        print(f"  ❌ No video passed all quality criteria after {max_sample_clips} attempts")
        print(f"  📁 Using last generated clip for post-processing...")
    
    best_video_idx = clips_info.get("init_best", -1)
    print(f"✅ Best video index: {best_video_idx}")

    # Step 4: Post-Process - End Frame Sharpening
    print("\n" + "-" * 40)
    print("STEP 4: Post-Processing - Selecting Best End Frame")
    print("-" * 40)
    best_video_path = clips_info['veo_local_path'][best_video_idx]
    final_video_info = edit_video_with_best_end_frame(
        clip_path=best_video_path,
        product_directory=product_directory,
        k_frames=12
    )
    if not final_video_info:
        log.error(f"Failed to post-process video for {product_directory}")
        # Save partial metadata and return
        save_metadata(output_dir, input_config, starting_frame_info, scene_script_json, 
                      clips_info.get('prompts', []), clips_info, final_video_info)
        return None
    print(f"Final video: {final_video_info['local_path']}")

    # Step 5: Save Metadata (success case)
    print("\n" + "-" * 40)
    print("STEP 5: Saving Metadata")
    print("-" * 40)
    save_metadata(
        output_dir=output_dir,
        input_config=input_config,
        starting_frame_info=starting_frame_info,
        scene_script_json=scene_script_json,
        veo_prompts=clips_info.get('prompts', []),
        clips_info=clips_info,
        final_video_info=final_video_info
    )

    # Summary for this product
    print("\n" + "=" * 60)
    print(f"✅ COMPLETED: {product_directory}")
    print("=" * 60)
    print(f"  • Product: {product_desc[:50]}...")
    print(f"  • Country: {country}")
    print(f"  • Final Video: {final_video_info['local_path']}")
    
    return {
        "product_directory": product_directory,
        "product_desc": product_desc,
        "country": country,
        "final_video": final_video_info['local_path'],
        "metadata_path": f"{output_dir}/metadata.json"
    }


def batch_process_image_only(
    data_dir: str = None,
    company_name: str = None,
    max_workers: int = None,
    max_sample_images: int = None,
    force: bool = False
) -> dict:
    """Process all product folders under the data directory using parallel processing (IMAGE ONLY mode).
    
    Only generates starting frame images, skips video generation and post-processing.
    Automatically skips products that have already been processed (have passing images),
    unless force=True is specified.
    
    Args:
        data_dir: The root data directory containing product subfolders
        company_name: Company name for branding
        max_workers: Maximum number of parallel workers. If None, defaults to min(5, num_products)
        max_sample_images: Maximum generation attempts for images (default: 3)
        force: If True, reprocess all products even if already completed (default: False)
        
    Returns:
        dict: Summary of batch processing results including skipped products
    """
    print("\n" + "=" * 60)
    print("🖼️  BATCH PROCESSING MODE - IMAGE ONLY (PARALLEL)")
    print("=" * 60)
    print(f"Max image attempts: {max_sample_images}")
    if force:
        print(f"⚠️  Force mode enabled - will reprocess all products")
    
    product_dirs = get_all_product_directories(data_dir)
    
    if not product_dirs:
        print(f"❌ No valid product directories found in {data_dir}")
        return {"success": [], "failed": [], "skipped": [], "total": 0}
    
    # Determine number of workers
    num_workers = max_workers if max_workers else min(5, len(product_dirs))
    
    print(f"\n📦 Found {len(product_dirs)} products to process:")
    for i, pd in enumerate(product_dirs, 1):
        print(f"  {i}. {pd}")
    print(f"\n⚡ Using {num_workers} parallel worker(s)")
    
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
        "total": len(product_dirs)
    }
    
    # Capture current user_id to propagate to worker threads
    current_user_id = get_user_id()
    
    def _process_image_only_with_context(product_dir, company_name, max_sample_images, force):
        """Wrapper that propagates user context to worker thread."""
        set_user_id(current_user_id)
        return process_product_image_only(product_dir, company_name, max_sample_images, force)
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks with force parameter
        future_to_product = {
            executor.submit(_process_image_only_with_context, product_dir, company_name, max_sample_images, force): product_dir 
            for product_dir in product_dirs
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_product):
            product_dir = future_to_product[future]
            try:
                result = future.result()
                if result:
                    # Check if it was skipped
                    if result.get('skipped'):
                        results["skipped"].append(result)
                        log.info(f"Skipped (already processed): {product_dir}")
                        print(f"\n⏭️  Skipped: {product_dir}")
                    else:
                        results["success"].append(result)
                        log.info(f"Successfully processed (image only): {product_dir}")
                        print(f"\n✅ Completed: {product_dir}")
                else:
                    results["failed"].append({"product_directory": product_dir, "error": "Image generation returned None"})
                    log.error(f"Failed to process (image only): {product_dir}")
                    print(f"\n❌ Failed: {product_dir} - Image generation returned None")
            except Exception as e:
                log.error(f"Exception while processing (image only) {product_dir}: {e}")
                results["failed"].append({"product_directory": product_dir, "error": str(e)})
                print(f"\n❌ Error processing {product_dir}: {e}")
    
    # Final Summary
    print("\n" + "=" * 60)
    print("📊 BATCH PROCESSING COMPLETE (IMAGE ONLY)")
    print("=" * 60)
    
    if results["skipped"]:
        print(f"\n⏭️  Skipped (already processed): {len(results['skipped'])}/{results['total']}")
        for r in results["skipped"]:
            print(f"   • {r['product_directory']}")
    
    print(f"\n✅ Successful: {len(results['success'])}/{results['total']}")
    for r in results["success"]:
        print(f"   • {r['product_directory']} -> {r['best_image']}")
    
    if results["failed"]:
        print(f"\n❌ Failed: {len(results['failed'])}/{results['total']}")
        for r in results["failed"]:
            print(f"   • {r['product_directory']}: {r['error']}")
    
    return results


def batch_process(
    data_dir: str = None,
    company_name: str = None,
    max_workers: int = None,
    max_sample_images: int = None,
    max_sample_clips: int = None,
    force: bool = False
) -> dict:
    """Process all product folders under the data directory using parallel processing.
    
    Automatically skips products that have already been fully processed (have final video),
    unless force=True is specified.
    
    Args:
        data_dir: The root data directory containing product subfolders
        company_name: Company name for branding
        max_workers: Maximum number of parallel workers. If None, defaults to min(4, num_products)
        max_sample_images: Maximum generation attempts for images (default: 3)
        max_sample_clips: Maximum generation attempts for video clips (default: 3)
        force: If True, reprocess all products even if already completed (default: False)
        
    Returns:
        dict: Summary of batch processing results including skipped products
    """
    print("\n" + "=" * 60)
    print("🔄 BATCH PROCESSING MODE (PARALLEL)")
    print("=" * 60)
    print(f"Max image attempts: {max_sample_images}, Max clip attempts: {max_sample_clips}")
    if force:
        print(f"⚠️  Force mode enabled - will reprocess all products")
    
    product_dirs = get_all_product_directories(data_dir)
    
    if not product_dirs:
        print(f"❌ No valid product directories found in {data_dir}")
        return {"success": [], "failed": [], "skipped": [], "total": 0}
    
    # Determine number of workers
    num_workers = max_workers if max_workers else min(5, len(product_dirs))
    
    print(f"\n📦 Found {len(product_dirs)} products to process:")
    for i, pd in enumerate(product_dirs, 1):
        print(f"  {i}. {pd}")
    print(f"\n⚡ Using {num_workers} parallel worker(s)")
    
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
        "total": len(product_dirs)
    }
    
    # Capture current user_id to propagate to worker threads
    current_user_id = get_user_id()
    
    def _process_product_with_context(product_dir, company_name, max_sample_images, max_sample_clips, force):
        """Wrapper that propagates user context to worker thread."""
        set_user_id(current_user_id)
        return process_product(product_dir, company_name, max_sample_images, max_sample_clips, force)
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks with force parameter
        future_to_product = {
            executor.submit(_process_product_with_context, product_dir, company_name, max_sample_images, max_sample_clips, force): product_dir 
            for product_dir in product_dirs
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_product):
            product_dir = future_to_product[future]
            try:
                result = future.result()
                if result:
                    # Check if it was skipped
                    if result.get('skipped'):
                        results["skipped"].append(result)
                        log.info(f"Skipped (already processed): {product_dir}")
                        print(f"\n⏭️  Skipped: {product_dir}")
                    else:
                        results["success"].append(result)
                        log.info(f"Successfully processed: {product_dir}")
                        print(f"\n✅ Completed: {product_dir}")
                else:
                    results["failed"].append({"product_directory": product_dir, "error": "Pipeline returned None"})
                    log.error(f"Failed to process: {product_dir}")
                    print(f"\n❌ Failed: {product_dir} - Pipeline returned None")
            except Exception as e:
                log.error(f"Exception while processing {product_dir}: {e}")
                results["failed"].append({"product_directory": product_dir, "error": str(e)})
                print(f"\n❌ Error processing {product_dir}: {e}")
    
    # Final Summary
    print("\n" + "=" * 60)
    print("📊 BATCH PROCESSING COMPLETE")
    print("=" * 60)
    
    if results["skipped"]:
        print(f"\n⏭️  Skipped (already processed): {len(results['skipped'])}/{results['total']}")
        for r in results["skipped"]:
            print(f"   • {r['product_directory']}")
    
    print(f"\n✅ Successful: {len(results['success'])}/{results['total']}")
    for r in results["success"]:
        print(f"   • {r['product_directory']} -> {r['final_video']}")
    
    if results["failed"]:
        print(f"\n❌ Failed: {len(results['failed'])}/{results['total']}")
        for r in results["failed"]:
            print(f"   • {r['product_directory']}: {r['error']}")
    
    return results
