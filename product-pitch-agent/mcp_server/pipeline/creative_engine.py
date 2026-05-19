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
Creative Engine for YouTube-based Scene Script Generation.

This module provides a standalone creative engine that:
- Analyzes YouTube videos to extract advertising style patterns
- Generates reusable Image Scene Scripts (for starting frame generation)
- Generates Video Scene Scripts (8-second duration) following the analyzed style

This is NOT part of the batch processing pipeline - it's a creative tool
for generating scene script templates from reference videos.
"""

from typing import Optional
from mcp_server.pipeline.vertex_ai_service import vertex_ai
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel
from mcp_server.pipeline.log import log


def get_youtube_scene_script_engine_prompt(video_duration: int = 8, time_range: str = None, clip_intent: str = None) -> str:
    """Create prompt for analyzing YouTube video and generating scene scripts.
    
    Handles both single-scene videos (≤8s) and multi-scene videos (>8s).
    For multi-scene videos, identifies the most relevant 8-second subclip.
    
    Args:
        video_duration: Target video duration in seconds (default: 8)
        time_range: Optional time range to analyze (format: "MM:SS-MM:SS", e.g., "00:00-00:07")
                   If provided, only this segment will be analyzed instead of the whole video.
        clip_intent: Optional user-provided description of what the clip is intended to create.
        
    Returns:
        str: Formatted prompt for YouTube analysis and scene script generation
    """
    
    # Build time range instruction if specified
    time_range_instruction = ""
    if time_range:
        time_range_instruction = f"""
=== TIME RANGE CONSTRAINT ===
**IMPORTANT**: You MUST analyze ONLY the segment from {time_range} of this video.
- Ignore all content outside this time range
- Treat this segment as your entire reference video
- All analysis below should be based ONLY on this specific time segment
- For "Selected Subclip", set to "{time_range} (user-specified)" 
- For "Is Multi-Scene", evaluate ONLY within this time range
"""
    
    # Build clip intent instruction if specified
    clip_intent_instruction = ""
    if clip_intent:
        clip_intent_instruction = f"""
=== CLIP INTENT (USER-PROVIDED) ===
**Creative Intent**: {clip_intent}

Use this intent to guide your analysis and scene script generation. The generated templates should align with this creative purpose.
"""
    
    prompt = f"""You are an elite advertising Creative Director analyzing a reference video to create reusable scene script templates.

TASK: Analyze the provided YouTube video and generate scene scripts for an {video_duration}-second product marketing video.
{clip_intent_instruction}

{time_range_instruction}

=== PHASE 1: VIDEO STRUCTURE ANALYSIS ===

First, determine if this is a single-scene or multi-scene video:

**SINGLE-SCENE VIDEO** (≤{video_duration} seconds): 
- One continuous shot with no hard cuts
- Single location/environment
- One complete action arc
- One key message

**MULTI-SCENE VIDEO** (>{video_duration} seconds):
- Contains multiple cuts/transitions
- May have different locations or camera setups
- Multiple action sequences
- Multiple messages or product angles

If this is a **MULTI-SCENE VIDEO**, you MUST:
1. Identify all distinct scenes (look for cuts, transitions, location changes)
2. Select the SINGLE BEST 8-second subclip that best represents an "influencer product showcase" pattern
3. Analyze ONLY that selected subclip for scene script generation

**8-SECOND SUBCLIP STRUCTURE** (what to look for):
```
[0-2s]  HOOK         → Product/action that grabs attention
[2-6s]  KEY MESSAGE  → Main pitch/demonstration with speech
[6-8s]  CLOSE        → Resolution/confident ending pose
```

=== PHASE 2: YOUTUBE VIDEO ANALYSIS ===

Analyze the video (or selected subclip) and extract the HIGH-LEVEL advertising pattern:

1. **Ad Type**: Category of advertisement (e.g., "Influencer product showcase", "Unboxing reveal", "Lifestyle demonstration")

2. **Aspect Ratio**: Video format:
   - "16:9" (horizontal/landscape - traditional YouTube, TV)
   - "9:16" (vertical/portrait - TikTok, Instagram Reels, YouTube Shorts)

3. **Video Duration**: Total length of reference video

4. **Is Multi-Scene**: true/false - whether this video contains multiple scenes

5. **Selected Subclip** (if multi-scene): Describe which 8-second segment was selected and why
   Example: "Selected scene 2 (8-16s): Influencer holds product and delivers pitch to camera"

6. **Script Pattern**: Narrative flow template for the selected scene
   Example: "Product close-up → reveal to face → enthusiastic pitch → confident close"

7. **Model Style Analysis**: Analyze the influencer/model's appearance and extract the GENERALIZED STYLE PATTERN:
   - **Style Category**: Classify the overall aesthetic category (e.g., "Casual Chic", "Professional", "Athleisure", "Streetwear", "Glam", "Bohemian", "Minimalist", "Trendy")
   - **Color Palette**: General color scheme (e.g., "Neutral tones", "Bright and bold", "Monochromatic", "Earth tones")
   - **Formality Level**: How dressed up is the look? (e.g., "Relaxed casual", "Smart casual", "Business casual", "Formal")
   - **Aesthetic Era**: The fashion era/trend influence (e.g., "Modern minimalist", "Y2K inspired", "Classic timeless", "Streetwear influenced")
   - **Overall Vibe**: Summarize the energy and personality conveyed (e.g., "Approachable and relatable influencer", "Polished professional", "Edgy and fashion-forward", "Warm and trustworthy")
   
   **IMPORTANT**: Do NOT describe specific clothing items (like "white t-shirt" or "blue jeans"). Instead, describe the PATTERN and AESTHETIC that can be applied to any outfit.

8. **Voice-Over Analysis**: Analyze the audio/speech style in the video:
   - **Voice Type**: Determine how the speech is delivered:
     - "on_camera" - Model is speaking directly to camera with visible lip movements (lip-sync)
     - "dubbed" - External voice-over narration (voice doesn't match lip movements, or no speaking visible)
     - "mixed" - Combination of both (e.g., model speaks some lines, narrator speaks others)
   - **Pacing**: The energy, tempo, and rhythm of the speech delivery (e.g., "Fast-paced energetic pitch", "Slow deliberate narration", "Natural conversational rhythm", "Dynamic with pauses for emphasis")
   - **Lip Sync Required**: true if the video shows the model speaking with lip movements, false if voice is external narration

=== PHASE 3: GENERATE SCENE SCRIPTS ===

Based on the analyzed pattern (from the selected 8-second subclip if multi-scene), generate GENERIC REUSABLE TEMPLATES.

**CRITICAL: DO NOT literally describe the specific video. Extract the PATTERN and create GENERIC templates.**

**A) IMAGE SCENE SCRIPT (Starting Frame Description)**
Create a GENERIC, REUSABLE template following this exact structure and style:

**KEY RULES for Image Scene Script:**
1. Start with purpose statement: "This script outlines the requirements for generating [a type of the youtube video]..."
2. Use GENDER-NEUTRAL language: "male or female" (not specific gender from video)
3. Use ARCHETYPE descriptions: "successful, charismatic entrepreneur" (not literal video description)
4. Use PLACEHOLDER language for environment: "the chosen background environment" (not specific room details)
5. Include: professional lighting, composition focus, quality requirements
6. Extract the PATTERN (e.g., energy level, presentation style) but express it generically
7. **AVOID specific interaction verbs** like "holding", "wearing", "carrying" - the interaction mode will be determined dynamically based on the input product

**B) VIDEO SCENE SCRIPT ({video_duration}-Second JSON)**
Create a GENERIC, REUSABLE video scene script template following this exact structure and style:

**KEY RULES for Video Scene Script:**
1. Total duration: {video_duration} seconds
2. Extract the PATTERN (camera movement style, pacing, energy) from the analyzed video
3. Keep language generic and reusable for any product

=== OUTPUT FORMAT ===

Use this JSON schema for output:
{{
    "youtube_analysis": {{
        "ad_type": "High-level category of the advertising style",
        "aspect_ratio": "16:9 or 9:16",
        "video_duration": "Total duration of reference video (e.g., '30 seconds')",
        "is_multi_scene": true or false,
        "selected_subclip": "Description of selected 8-second subclip (null if single-scene video)",
        "script_pattern": "Narrative flow template (e.g., 'Product reveal → Face reveal → Pitch → Close')",
        "model_style": {{
            "style_category": "Overall aesthetic category (e.g., Casual Chic/Professional/Athleisure/Streetwear/Glam/Bohemian/Minimalist/Trendy)",
            "color_palette": "General color scheme (e.g., Neutral tones/Bright and bold/Monochromatic/Earth tones)",
            "formality_level": "How dressed up (e.g., Relaxed casual/Smart casual/Business casual/Formal)",
            "aesthetic_era": "Fashion era/trend influence (e.g., Modern minimalist/Y2K inspired/Classic timeless)",
            "overall_vibe": "Energy and personality conveyed (e.g., Approachable influencer/Polished professional/Edgy and fashion-forward)"
        }},
        "voice_over": {{
            "voice_type": "Type of how the speech is delivered based on **PHASE 2 Voice-Over Analysis**",
            "pacing": "Energy, tempo, rhythm of speech delivery (e.g., Fast-paced energetic pitch/Slow deliberate narration/Natural conversational rhythm/Dynamic with pauses)",
            "lip_sync_required": true or false
        }}
    }},
    "image_scene_script": "Complete text description for starting frame image generation. Must include environment, character, product presentation, lighting, composition, and 4K quality requirements. Write as a professional creative brief.",
    "video_scene_script": {{
        "scene": "The KOL/KOC's POV (adapt based on the analyzed scenario) - {video_duration} seconds total",
        "visual": "Immersive first-person POV shot description. Professional-grade 4K quality. Product positioning and character action description.",
        "camera_motion": "Camera movement description following the analyzed pattern. Must be stable and continuous.",
        "closing": "Closing description based on the analyzed pattern."
    }}
}}"""
    
    return prompt


def generate_scene_scripts_from_youtube(
    youtube_url: str,
    video_duration: int = None,
    time_range: str = None,
    clip_intent: str = None,
    video_fps: Optional[int] = None
) -> dict:
    """Analyze YouTube video and generate reusable scene script templates.
    
    This is a standalone creative engine that extracts advertising patterns
    from a reference YouTube video and generates scene scripts that can be
    applied to any product.
    
    Args:
        youtube_url: YouTube video URL to analyze
        video_duration: Target video duration in seconds (default: 8)
        time_range: Optional time range to analyze (format: "MM:SS-MM:SS", e.g., "00:00-00:07")
                   If provided, only this segment will be analyzed instead of the whole video.
        clip_intent: Optional user-provided description of what the clip is intended to create.
        video_fps: Optional FPS for video sampling (default: 1). 
                   Lower values reduce token usage. Set to None to use full video.
        
    Returns:
        dict: {
            "youtube_analysis": {
                "ad_type": str,
                "aspect_ratio": str,
                "duration": str,
                "script_pattern": str,
                "clip_intent": str (if provided)
            },
            "image_scene_script": str,
            "video_scene_script": dict
        }
        Returns False if generation failed
    """
    # Apply defaults from settings
    if video_duration is None:
        video_duration = settings.DEFAULT_VIDEO_DURATION
    if video_fps is None:
        video_fps = settings.VIDEO_ANALYSIS_FPS
    
    log.info(f"Creative Engine: Analyzing YouTube video: {youtube_url}")
    if time_range:
        log.info(f"Parameters - Duration: {video_duration}s, Time Range: {time_range}")
    else:
        log.info(f"Parameters - Duration: {video_duration}s")
    if clip_intent:
        log.info(f"Clip Intent: {clip_intent}")
    if video_fps is not None:
        log.info(f"Video FPS: {video_fps}")
    
    # Prepare the prompt
    prompt = get_youtube_scene_script_engine_prompt(video_duration, time_range, clip_intent)
    
    # Prepare YouTube video as multimodal input
    # Gemini 2.0 supports YouTube URLs directly
    youtube_input = [{"uri": youtube_url, "mime_type": "video/mp4"}]
    if video_fps is not None:
        youtube_input[0]["fps"] = video_fps
    
    # Invoke Gemini to analyze the video and generate scene scripts
    result = vertex_ai.invoke_gemini(
        prompt=prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        multimodal_input=youtube_input,
    )
    
    # Check if API call failed
    if result is False:
        log.error("Creative Engine: Scene script generation failed after all retries")
        return False
    
    # Validate the result structure
    required_keys = ["youtube_analysis", "image_scene_script", "video_scene_script"]
    for key in required_keys:
        if key not in result:
            log.error(f"Creative Engine: Missing required key '{key}' in response")
            log.error(f"Result: {result}")
            return False
    
    # Validate youtube_analysis structure
    analysis_keys = ["ad_type", "aspect_ratio", "video_duration", "is_multi_scene", "script_pattern"]
    for key in analysis_keys:
        if key not in result.get("youtube_analysis", {}):
            log.warning(f"Creative Engine: Missing analysis key '{key}'")
    
    # Log multi-scene detection
    is_multi_scene = result.get("youtube_analysis", {}).get("is_multi_scene", False)
    if is_multi_scene:
        selected_subclip = result.get("youtube_analysis", {}).get("selected_subclip", "N/A")
        log.info(f"Creative Engine: Multi-scene video detected")
        log.info(f"Creative Engine: Selected subclip: {selected_subclip}")
    
    # Validate video_scene_script structure
    script_keys = ["scene", "visual", "camera_motion", "pacing", "closing"]
    for key in script_keys:
        if key not in result.get("video_scene_script", {}):
            log.warning(f"Creative Engine: Missing video script key '{key}'")
    
    # Add user-provided clip_intent to the result
    if clip_intent:
        result["youtube_analysis"]["clip_intent"] = clip_intent
    
    log.info("Creative Engine: Scene scripts generated successfully")
    log.info(f"Ad Type: {result['youtube_analysis'].get('ad_type', 'N/A')}")
    log.info(f"Aspect Ratio: {result['youtube_analysis'].get('aspect_ratio', 'N/A')}")
    log.info(f"Script Pattern: {result['youtube_analysis'].get('script_pattern', 'N/A')}")
    if clip_intent:
        log.info(f"Clip Intent: {clip_intent}")
    
    return result


def format_scene_scripts_for_display(result: dict) -> str:
    """Format the generated scene scripts for human-readable display.
    
    Args:
        result: The result from generate_scene_scripts_from_youtube()
        
    Returns:
        str: Formatted string for display
    """
    if not result:
        return "No scene scripts generated."
    
    output = []
    output.append("=" * 60)
    output.append("CREATIVE ENGINE OUTPUT")
    output.append("=" * 60)
    
    # YouTube Analysis
    analysis = result.get("youtube_analysis", {})
    output.append("\n📺 YOUTUBE ANALYSIS")
    output.append("-" * 40)
    output.append(f"Ad Type: {analysis.get('ad_type', 'N/A')}")
    output.append(f"Aspect Ratio: {analysis.get('aspect_ratio', 'N/A')}")
    output.append(f"Video Duration: {analysis.get('video_duration', 'N/A')}")
    output.append(f"Multi-Scene: {'Yes' if analysis.get('is_multi_scene', False) else 'No'}")
    if analysis.get('is_multi_scene', False) and analysis.get('selected_subclip'):
        output.append(f"Selected Subclip: {analysis.get('selected_subclip')}")
    output.append(f"Script Pattern: {analysis.get('script_pattern', 'N/A')}")
    if analysis.get('clip_intent'):
        output.append(f"Clip Intent: {analysis.get('clip_intent')}")
    
    # Model Style
    model_style = analysis.get("model_style", {})
    if model_style:
        output.append("\n👗 MODEL STYLE PATTERN")
        output.append("-" * 40)
        output.append(f"Style Category: {model_style.get('style_category', 'N/A')}")
        output.append(f"Color Palette: {model_style.get('color_palette', 'N/A')}")
        output.append(f"Formality: {model_style.get('formality_level', 'N/A')}")
        output.append(f"Aesthetic Era: {model_style.get('aesthetic_era', 'N/A')}")
        output.append(f"Overall Vibe: {model_style.get('overall_vibe', 'N/A')}")
    
    # Voice-Over
    voice_over = analysis.get("voice_over", {})
    if voice_over:
        output.append("\n🎙️ VOICE-OVER ANALYSIS")
        output.append("-" * 40)
        output.append(f"Voice Type: {voice_over.get('voice_type', 'N/A')}")
        output.append(f"Pacing: {voice_over.get('pacing', 'N/A')}")
        output.append(f"Lip Sync Required: {'Yes' if voice_over.get('lip_sync_required', True) else 'No'}")
    
    # Image Scene Script
    output.append("\n🖼️ IMAGE SCENE SCRIPT")
    output.append("-" * 40)
    output.append(result.get("image_scene_script", "N/A"))
    
    # Video Scene Script
    output.append("\n🎬 VIDEO SCENE SCRIPT")
    output.append("-" * 40)
    video_script = result.get("video_scene_script", {})
    for key, value in video_script.items():
        output.append(f"{key}: {value}")
    
    output.append("\n" + "=" * 60)
    
    return "\n".join(output)


# Example usage and testing
if __name__ == "__main__":
    
    # Example: Analyze a YouTube video and generate scene scripts
    # Replace with an actual YouTube URL
    test_url = "https://www.youtube.com/shorts/qhYdyoz2w0k"
    
    print("Creative Engine - YouTube Scene Script Generator")
    print("=" * 50)
    print(f"Analyzing: {test_url}")
    print()
    
    result = generate_scene_scripts_from_youtube(
        youtube_url=test_url,
        video_duration=8
    )
    
    if result:
        print(format_scene_scripts_for_display(result))
    else:
        print("Failed to generate scene scripts.")
