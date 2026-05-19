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
Video post-processing functions.

This module provides:
- End frame sharpening and selection
- Video trimming based on best end frame
- Post-processing only mode for existing clips
"""

import os
import json
from datetime import datetime

from PIL import Image as PIL_Image
from moviepy import VideoFileClip

from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.gcs_service import gcs_service
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.log import log
from mcp_server.pipeline.user_context import get_output_base_dir, get_gcs_prefix

from mcp_server.pipeline.video_prompts import get_end_frame_select_prompt
from mcp_server.pipeline.metadata import load_existing_metadata


def _ensure_local_video(clip_path: str) -> str:
    """Ensure the video clip exists locally, downloading from GCS if needed.
    
    In Cloud Run, local files from previous job runs are ephemeral.
    If the clip_path is a local path that doesn't exist, we try to find
    the corresponding GCS URI and download it to a temp location.
    
    Args:
        clip_path: Local path or GCS URI of the video clip
        
    Returns:
        str: Local path to the video file (original or downloaded)
        
    Raises:
        FileNotFoundError: If the video cannot be found locally or in GCS
    """
    # If it's already a GCS URI, download it
    if clip_path.startswith("gs://"):
        gcs_key = gcs_service.extract_key_from_full_uri(clip_path)
        local_dir = os.path.dirname(clip_path.replace("gs://", "/tmp/gcs_cache/"))
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, os.path.basename(clip_path))
        if not os.path.exists(local_path):
            log.info(f"Downloading video from GCS: {clip_path}")
            success = gcs_service.download_file(gcs_key, local_path)
            if not success:
                raise FileNotFoundError(f"Failed to download video from GCS: {clip_path}")
        return local_path
    
    # If local file exists, use it directly
    if os.path.exists(clip_path):
        return clip_path
    
    # Local file missing — try to find it in GCS output store
    gcs_prefix = get_gcs_prefix()
    # clip_path is typically like: output_mcp/user/product_id/veo_clip_0.mp4
    # We need to search GCS for the corresponding file
    filename = os.path.basename(clip_path)
    # Try to extract product directory from the path
    path_parts = clip_path.replace("\\", "/").split("/")
    # Look for the product_id part (usually second-to-last directory)
    product_id = None
    for i, part in enumerate(path_parts):
        if part in ("veo_clip_0.mp4", "veo_clip_1.mp4", "veo_clip_2.mp4") or filename == part:
            if i > 0:
                product_id = path_parts[i - 1]
            break
    
    if product_id:
        # Search in GCS output for this product
        gcs_search_prefix = f"{gcs_prefix}/output/{product_id}/"
        blobs = gcs_service.list_blobs_with_prefix(gcs_search_prefix)
        matching = [b for b in blobs if b.endswith(f"/{filename}")]
        if matching:
            gcs_key = matching[0]
            local_dir = os.path.dirname(clip_path)
            os.makedirs(local_dir, exist_ok=True)
            log.info(f"Downloading video from GCS: gs://{settings.GCS_BUCKET_NAME}/{gcs_key}")
            success = gcs_service.download_file(gcs_key, clip_path)
            if success:
                return clip_path
    
    raise FileNotFoundError(f"Video not found locally or in GCS: {clip_path}")


def edit_video_with_best_end_frame(clip_path: str, product_directory: str, k_frames: int = None) -> dict:
    """Select and trim video to best end frame using AI evaluation.
    
    Extracts the last k frames from the video, uses Gemini to select the best
    ending frame, and trims the video to end at that frame.
    
    If the clip_path doesn't exist locally (e.g. in Cloud Run), attempts to
    download the video from GCS first.
    
    Args:
        clip_path: Path to the video clip to process (local path or GCS URI)
        product_directory: Product directory path for output organization
        k_frames: Number of ending frames to evaluate (default: settings.POSTPROCESS_K_FRAMES)
        
    Returns:
        dict: Output info with result URI, local_path, and reasoning
        False: If processing fails
    """
    # Apply defaults from settings
    if k_frames is None:
        k_frames = settings.POSTPROCESS_K_FRAMES
    fps = settings.POSTPROCESS_FPS
    base_dir = get_output_base_dir()
    gcs_prefix = get_gcs_prefix()
    directory_prefix = product_directory.split("/")[-1]
    postprocess_output_uri = f"gs://{settings.GCS_BUCKET_NAME}/{gcs_prefix}/output/{directory_prefix}/postprocess"
    postprocess_dir_path = f"{base_dir}/{directory_prefix}/postprocess"
    os.makedirs(postprocess_dir_path, exist_ok=True)
    
    # Ensure video is available locally (download from GCS if needed)
    try:
        clip_path = _ensure_local_video(clip_path)
    except FileNotFoundError as e:
        log.error(f"Cannot post-process video: {e}")
        print(f"❌ Video file not available: {e}")
        return False
    
    # Extract last k frames
    image_uris = []
    with VideoFileClip(clip_path) as shot:
        frames = list(shot.iter_frames())[-k_frames:]
        for i in range(len(frames)):
            pil_img = PIL_Image.fromarray(frames[i])
            filename = f"{clip_path.split('/')[-1].replace('.mp4', '')}_last_{k_frames-i:02d}_frame.png"
            img_path = postprocess_dir_path + "/" + filename
            pil_img.save(img_path)
            gcs_service.upload_file(
                img_path, 
                postprocess_output_uri.replace(f"gs://{settings.GCS_BUCKET_NAME}/", "") + "/" + filename, 
                replace=True
            )
            image_uris.append(postprocess_output_uri + "/" + filename)
    
    # Evaluate frames
    multimodal_input = []
    for image_uri in image_uris:
        multimodal_input.append({"uri": image_uri, "mime_type": "image/png"})
    
    eval_result = vertex_ai.invoke_gemini(
        prompt=get_end_frame_select_prompt(k_frames),
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        multimodal_input=multimodal_input,
    )
    
    frame_idx = eval_result.get("best", -1)
    reasoning = eval_result.get("reasoning", "")
    
    if frame_idx == -1:
        print("Failed to select the end frame!")
        return False
    
    print(f"Selected end frame {frame_idx}: {reasoning}")
    
    cnt_trimmed_frames = k_frames - frame_idx - 1
    
    # Use context manager to ensure proper resource cleanup (prevents audio loss)
    with VideoFileClip(clip_path) as shot:
        end_time = shot.duration - cnt_trimmed_frames/fps
        trimmed_video = shot.subclipped(0, end_time)
        output_path = postprocess_dir_path + "/final_video_trimmed.mp4"
        output_uri = postprocess_output_uri + "/final_video_trimmed.mp4"
        trimmed_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
    
    gcs_service.upload_file(output_path, output_uri.replace(f"gs://{settings.GCS_BUCKET_NAME}/", ""), replace=True)
    
    output_info = {
        "result": output_uri,
        "local_path": output_path,
        "reasoning": reasoning
    }
    
    print(f"Final video saved to: {output_path}")
    return output_info


def process_postprocess_only(product_id: str, output_dir: str = None, clip_index: int = None) -> dict:
    """Run post-processing only on an existing video clip.
    
    Loads metadata from a previous run to get the video clips info,
    then runs post-processing on the best clip (or specified clip index).
    
    This is useful for:
    - Resuming a failed pipeline from post-processing stage
    - Re-running post-processing on a different clip
    - Processing videos that were generated but not post-processed
    
    Args:
        product_id: The product ID (folder name in output directory)
        output_dir: Base output directory (default: settings.TEMP_OUTPUT_DIR)
        clip_index: Optional specific clip index to post-process. 
                    If None, uses init_best from metadata.
        
    Returns:
        dict: Results including final video path, or None if failed
    """
    if output_dir is None:
        output_dir = get_output_base_dir()
    
    product_output_dir = os.path.join(output_dir, product_id)
    
    print("\n" + "=" * 60)
    print(f"🔄 POST-PROCESSING ONLY: {product_id}")
    print("=" * 60)
    
    # Load existing metadata
    print("\n" + "-" * 40)
    print("Loading existing metadata...")
    print("-" * 40)
    
    existing_metadata = load_existing_metadata(product_output_dir)
    
    if not existing_metadata:
        log.error(f"No existing metadata found for {product_id}")
        print(f"❌ No metadata.json found in {product_output_dir}")
        return None
    
    # Check if video clips exist
    clips_info = existing_metadata.get('video_clips')
    if not clips_info:
        log.error(f"No video clips info found in metadata for {product_id}")
        print(f"❌ No video clips found in metadata - run video generation first")
        return None
    
    veo_local_paths = clips_info.get('veo_local_path', [])
    if not veo_local_paths:
        log.error(f"No local video paths found in metadata for {product_id}")
        print(f"❌ No local video paths found in metadata")
        return None
    
    # Determine which clip to use
    if clip_index is not None:
        if clip_index < 0 or clip_index >= len(veo_local_paths):
            log.error(f"Invalid clip index {clip_index}. Available clips: 0-{len(veo_local_paths)-1}")
            print(f"❌ Invalid clip index {clip_index}. Available: 0-{len(veo_local_paths)-1}")
            return None
        best_clip_idx = clip_index
        print(f"Using specified clip index: {best_clip_idx}")
    else:
        best_clip_idx = clips_info.get('init_best', -1)
        if best_clip_idx == -1:
            # Fallback to last clip if init_best is not set
            best_clip_idx = len(veo_local_paths) - 1
            print(f"⚠️ init_best not set, using last clip: {best_clip_idx}")
        else:
            print(f"Using init_best from metadata: {best_clip_idx}")
    
    best_clip_path = veo_local_paths[best_clip_idx]
    
    # Ensure the clip file exists locally (download from GCS if needed)
    try:
        best_clip_path = _ensure_local_video(best_clip_path)
    except FileNotFoundError:
        # Also try GCS URI from veo_results if available
        veo_results = clips_info.get('veo_results', [])
        if veo_results and best_clip_idx < len(veo_results):
            gcs_uri = veo_results[best_clip_idx]
            if gcs_uri and gcs_uri.startswith("gs://"):
                try:
                    best_clip_path = _ensure_local_video(gcs_uri)
                except FileNotFoundError:
                    log.error(f"Clip file not found locally or in GCS: {best_clip_path}")
                    print(f"❌ Clip file not found locally or in GCS")
                    return None
            else:
                log.error(f"Clip file not found: {best_clip_path}")
                print(f"❌ Clip file not found: {best_clip_path}")
                return None
        else:
            log.error(f"Clip file not found: {best_clip_path}")
            print(f"❌ Clip file not found: {best_clip_path}")
            return None
    
    print(f"✅ Best clip: {best_clip_path}")
    print(f"   Available clips: {len(veo_local_paths)}")
    for i, path in enumerate(veo_local_paths):
        marker = " <-- selected" if i == best_clip_idx else ""
        exists = "✓" if os.path.exists(path) else "✗"
        print(f"   {exists} {i}: {path}{marker}")
    
    # Run post-processing
    print("\n" + "-" * 40)
    print("Post-Processing - Selecting Best End Frame")
    print("-" * 40)
    
    # Need product_directory for edit_video_with_best_end_frame
    # Extract from output_dir and product_id
    product_directory = f"data/{product_id}"  # Fallback path
    
    final_video_info = edit_video_with_best_end_frame(
        clip_path=best_clip_path,
        product_directory=product_directory,
        k_frames=12
    )
    
    if not final_video_info:
        log.error(f"Failed to post-process video for {product_id}")
        print(f"❌ Post-processing failed")
        return None
    
    print(f"✅ Final video: {final_video_info['local_path']}")
    
    # Update metadata with final video info
    print("\n" + "-" * 40)
    print("Updating Metadata")
    print("-" * 40)
    
    existing_metadata['final_video'] = final_video_info
    existing_metadata['timestamp'] = datetime.now().isoformat()
    
    # Update clips_info with new init_best if different
    if clip_index is not None:
        existing_metadata['video_clips']['init_best'] = clip_index
    
    metadata_path = os.path.join(product_output_dir, "metadata.json")
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(existing_metadata, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Metadata updated: {metadata_path}")
    
    # Summary
    print("\n" + "=" * 60)
    print(f"✅ POST-PROCESSING COMPLETE: {product_id}")
    print("=" * 60)
    print(f"  • Source clip: {best_clip_path}")
    print(f"  • Final video: {final_video_info['local_path']}")
    print(f"  • Metadata: {metadata_path}")
    
    return {
        "product_id": product_id,
        "source_clip": best_clip_path,
        "final_video": final_video_info['local_path'],
        "metadata_path": metadata_path
    }
