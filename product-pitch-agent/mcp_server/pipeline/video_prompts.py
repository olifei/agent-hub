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
Video generation and evaluation prompt templates.

This module contains all prompt templates for:
- Scene script generation
- Veo video generation
- Veo prompt with feedback
- Video quality evaluation
- End frame selection
"""


def get_scene_script_generation_prompt_v1(company_name: str, product_desc: str, country: str, speech_language: str) -> str:
    """Create prompt for dynamic scene script generation based on image (V1 - Original).
    
    Args:
        company_name: Company name for branding
        product_desc: Product description
        country: Target country for the advertisement
        speech_language: Language for the speech script
        
    Returns:
        str: Formatted scene script generation prompt
    """
    prompt = """Objective: You are a top-tier advertising creative director. Your task is to create a complete, ready-to-use video generation script, specifically optimized to prevent failed video endings, ensure character continuity, and guarantee professional-grade clarity, natural skin texture, realistic action, and product authenticity. The product image above is the starting frame of your video.

Instructions:
Follow the Thinking Steps below, but do not show them in the final output.
Only provide the final complete script in the specified Output Format, without any other commentary or explanations.
Quality Requirement: The visual must be described as professional-grade 4K clarity with rich detail. Reject overly smoothed skin textures and artificial-looking motions.
Speech Duration: The entire speech script, when read at a normal speaking speed in {{SPEECH_LANGUAGE}}, must be **strictly within 4-6 seconds** (approximately 17-22 words for English, adjust proportionally for other languages). The content needs to be direct but engaging, emphasizing the company first!

Context:
Company Name: {{COMPANY_NAME}}
Product: {{PRODUCT_DESC}}
Target Market: {{COUNTRY}}
Speech Language: {{SPEECH_LANGUAGE}}

Thinking Steps (Do NOT include in final output):
1. Think about the character: Based on the product and target market, conceptualize an engaging KOL/KOC persona. Crucially: Actions must be natural, realistic, and consistent with common product usage.
2. Think about the selling point: Write the key selling points in a short, impactful phrase for the product.
3. Think about the speech script: Create a voice-over line that includes {{COMPANY_NAME}} and highlights the selling point. Create the spoken line that is 4-6 seconds long when read, concise, and powerful, to ensure it finishes well before the 7-second video ends, avoiding abrupt cuts. The line must fit the {{SPEECH_LANGUAGE}} language and culture.

4. Integrate and output: Finally, generate a complete VEO script using the structure below.

Output Format (JSON):
Use this JSON schema for output:
{
    "scene": "The KOL/KOC's POV - 7 seconds total",
    "selling_point": "The key selling points you summarized in your thinking steps",
    "visual": "An immersive first-person POV shot. Requires professional-grade 4K quality with sharp, clear detail. The shot opens with a close-up on the product, highlighting its **selling point**. The character's action (holding/using the product) must be natural, realistic, and aligned with common usage.",
    "character_description": "The KOL/KOC persona you formulated in your thinking steps. Explicitly state: **Natural skin texture with detail, no smoothing applied.** Emotional expression must be a genuine reaction, not an exaggerated performance.",
    "camera_motion": "The camera then smoothly tilts up to meet their gaze. As their face breaks into an expression of genuine surprise and delight, they naturally lean in, speaking directly to the viewer to share an incredible secret about this item from {{COMPANY_NAME}}. The entire camera movement must be **stable and continuous, and the character transition must not be jarring.**",
    "speech": "The speech script you formulated in your thinking steps, **reading duration strictly controlled within 4-6 seconds (17-22 words for English).**",
    "speech_language": "{{SPEECH_LANGUAGE}}",
    "pacing": "**Quick and energetic, but all actions must be fluid and natural.** The character should seem genuinely proud, excited, and slightly surprised by this **high-quality, true-to-life product experience.**",
    "closing": "**After the speech ends, the character must settle into a still pose with mouth naturally closed in a confident smile.**"
}"""
    
    prompt = prompt.replace("{{COMPANY_NAME}}", company_name)
    prompt = prompt.replace("{{PRODUCT_DESC}}", product_desc)
    prompt = prompt.replace("{{COUNTRY}}", country)
    prompt = prompt.replace("{{SPEECH_LANGUAGE}}", speech_language)
    return prompt


def get_scene_script_generation_prompt_v2(company_name: str, product_desc: str, country: str, speech_language: str) -> str:
    """Create prompt for dynamic scene script generation based on image (V2 - Optimized for closed-mouth ending).
    
    V2 improvements:
    - Speech must end with closed-mouth sounds (bilabial consonants: m, p, b)
    - Pacing includes instruction for still pose with closed mouth after speech
    
    Args:
        company_name: Company name for branding
        product_desc: Product description
        country: Target country for the advertisement
        speech_language: Language for the speech script
        
    Returns:
        str: Formatted scene script generation prompt
    """
    prompt = """Objective: You are a top-tier advertising creative director. Your task is to create a complete, ready-to-use video generation script, specifically optimized to prevent failed video endings, ensure character continuity, and guarantee professional-grade clarity, natural skin texture, realistic action, and product authenticity. The product image above is the starting frame of your video.

Instructions:
Follow the Thinking Steps below, but do not show them in the final output.
Only provide the final complete script in the specified Output Format, without any other commentary or explanations.
Quality Requirement: The visual must be described as professional-grade 4K clarity with rich detail. Reject overly smoothed skin textures and artificial-looking motions.
Speech Duration: The entire speech script, when read at a normal speaking speed in {{SPEECH_LANGUAGE}}, must be **strictly within 4-6 seconds** (approximately 17-22 words for English, adjust proportionally for other languages). The content needs to be direct but engaging, emphasizing the company first!

Context:
Company Name: {{COMPANY_NAME}}
Product: {{PRODUCT_DESC}}
Target Market: {{COUNTRY}}
Speech Language: {{SPEECH_LANGUAGE}}

Thinking Steps (Do NOT include in final output):
1. Think about the character: Based on the product and target market, conceptualize an engaging KOL/KOC persona. Crucially: Actions must be natural, realistic, and consistent with common product usage.
2. Think about the selling point: Write the key selling points in a short, impactful phrase for the product.
3. Think about the speech script: Create a voice-over line that includes {{COMPANY_NAME}} and highlights the selling point. Create the spoken line that is 4-6 seconds long when read, concise, and powerful, to ensure it finishes well before the 7-second video ends, avoiding abrupt cuts. The line must fit the {{SPEECH_LANGUAGE}} language and culture. The final word of the speech MUST end with a closed-mouth sound (e.g., words ending in 'm', 'p', 'b', or similar mouth-closing sounds) to ensure the character's mouth is naturally closed when speaking finishes.

4. Integrate and output: Finally, generate a complete VEO script using the structure below.

Output Format (JSON):
Use this JSON schema for output:
{
    "scene": "The KOL/KOC's POV - 7 seconds total",
    "selling_point": "The key selling points you summarized in your thinking steps",
    "visual": "An immersive first-person POV shot. Requires professional-grade 4K quality with sharp, clear detail. The shot opens with a close-up on the {{PRODUCT}}, highlighting its **selling point**. The character's action (holding/using the product) must be natural, realistic, and aligned with common usage.",
    "character_description": "The KOL/KOC persona you formulated in your thinking steps. Explicitly state: **Natural skin texture with detail, no smoothing applied.** Emotional expression must be a genuine reaction, not an exaggerated performance.",
    "camera_motion": "The camera then smoothly tilts up to meet their gaze. As their face breaks into an expression of genuine surprise and delight, they naturally lean in, speaking directly to the viewer to share an incredible secret about this item from {{COMPANY_NAME}}. The entire camera movement must be **stable and continuous, and the character transition must not be jarring.**",
    "speech": "The speech script you formulated in your thinking steps, **reading duration strictly controlled within 4-6 seconds (17-22 words for English).** The final word MUST end with a closed-mouth sound (e.g., 'm', 'p', 'b') so the mouth is naturally closed after speaking.**",
    "speech_language": "{{SPEECH_LANGUAGE}}",
    "pacing": "**Quick and energetic, but all actions must be fluid and natural.** The character should seem genuinely proud, excited, and slightly surprised by this **high-quality, true-to-life product experience.** **After the speech ends, the character must settle into a still pose with mouth naturally closed in a confident smile.**"
}"""
    
    prompt = prompt.replace("{{COMPANY_NAME}}", company_name)
    prompt = prompt.replace("{{PRODUCT_DESC}}", product_desc)
    prompt = prompt.replace("{{COUNTRY}}", country)
    prompt = prompt.replace("{{SPEECH_LANGUAGE}}", speech_language)
    return prompt


def get_scene_script_generation_prompt(company_name: str, product_desc: str, country: str, speech_language: str) -> str:
    """Create prompt for dynamic scene script generation based on image.
    
    Default uses V1 (original version).
    
    Args:
        company_name: Company name for branding
        product_desc: Product description
        country: Target country for the advertisement
        speech_language: Language for the speech script
        
    Returns:
        str: Formatted scene script generation prompt
    """
    return get_scene_script_generation_prompt_v1(company_name, product_desc, country, speech_language)

def get_veo_prompt_with_scene_script() -> str:
    """Get the Veo video generation prompt template with scene script placeholder.
    
    Returns:
        str: Veo prompt template with {{SCENE_SCRIPT}} placeholder
    """
    prompt = """You are an expert at evaluating image and creating prompt for video generation.
You want to generate a product showcase video that starts with the provided image as the first frame.

**CRITICAL INSTRUCTIONS:**
1. **Consistency**: The product and model details MUST be maintained exactly as the provided image. Do NOT add any new objects (e.g., locks, handles, buttons) to the product that are not present in the starting frame.
2. **First Frame Face Clarity**: The character's face MUST be in sharp focus with clearly visible facial details (eyes, nose, mouth, skin texture) from the VERY FIRST FRAME. The face should NOT appear blurry, soft-focus, or lacking detail at any point, especially at the start.
3. **Quality**: Ensure the video starts with a crystal clear, high-quality frame matching the input image. Avoid any blurriness or low-quality artifacts in the first few frames.
4. **No Operational Interactions**: The character must NOT operate, open, close, or manipulate the product in ways that change its physical state. Only passive interactions are allowed (holding, displaying, wearing, or placing the product). Do NOT include actions like opening gates/doors/lids, pressing buttons, pulling zippers, folding/unfolding parts, or rotating movable components.
5. **Single-View Constraint**: The product MUST only be shown from angles visible in the starting frame image. Do NOT rotate the product to show the back, hidden sides, or any angles that were not captured in the reference image. The camera can move around the scene, but the product should maintain its original front-facing orientation.
6. **Background Continuity**: Ensure smooth and consistent background throughout the video. When the camera zooms or moves, the background environment must remain spatially coherent. Avoid any "picture stitching" effects where the outer edges of the frame show a different environment or visible seams.
7. **Natural Skin Texture**: Render natural skin texture with detail, no smoothing applied. Preserve natural skin imperfections, pores, and texture. Avoid artificial, over-processed, or "beauty filter" appearances.
8. **Natural Indoor Lighting**: For indoor scenes, use soft, diffused lighting that feels natural and realistic. Avoid harsh, direct lighting on faces that creates overexposed highlights or strong shadows. Lighting should feel like natural window light or well-balanced ambient indoor lighting, reducing any strong spotlight effects on people's faces.

The image above is used as the first frame of this video.

The story for video clip is in [SCENE_SCRIPT].

[SCENE_SCRIPT]
{{SCENE_SCRIPT}}

Create 1 prompt that will be used when generating a video that starts with this image as the first frame and follows the instructions in [SCENE_SCRIPT].

Make sure the character delivers the exact speech in the video. Highlight the **Pacing and Closing** description in the prompt.

**CRITICAL**: You MUST also include a negative prompt to explicitly specify elements to AVOID for realistic character rendering.

Use this JSON schema for output:
{
"video_prompt": "Prompt for video generation.",
"negative_prompt": "Up to 5 items maximum. Example: over-smoothed poreless skin, beauty filter effect, plastic wax-like appearance, harsh direct lighting, flat lighting"
}"""
    return prompt


def get_veo_prompt_with_feedback(scene_script: str, original_prompt: str, failed_criteria: list) -> str:
    """Generate an improved Veo prompt based on the original failed prompt and evaluation feedback.
    
    Args:
        scene_script: The scene script for video generation
        original_prompt: The original Veo prompt that was used (which failed evaluation)
        failed_criteria: List of failed criteria from previous video evaluation
        
    Returns:
        str: Prompt asking for an improved Veo prompt
    """
    # Import here to avoid circular dependency
    from mcp_server.pipeline.evaluator import format_failed_criteria_for_prompt
    feedback_text = format_failed_criteria_for_prompt(failed_criteria)
    
    prompt = """You are an expert at evaluating image and creating prompt for video generation.
You want to generate a product showcase video that starts with the provided image as the first frame.

**CRITICAL INSTRUCTIONS:**
1. **Consistency**: The product and model details MUST be maintained exactly as the provided image. Do NOT add any new objects (e.g., locks, handles, buttons) to the product that are not present in the starting frame.
2. **First Frame Face Clarity**: The character's face MUST be in sharp focus with clearly visible facial details (eyes, nose, mouth, skin texture) from the VERY FIRST FRAME. The face should NOT appear blurry, soft-focus, or lacking detail at any point, especially at the start.
3. **Quality**: Ensure the video starts with a crystal clear, high-quality frame matching the input image. Avoid any blurriness or low-quality artifacts in the first few frames.
4. **No Operational Interactions**: The character must NOT operate, open, close, or manipulate the product in ways that change its physical state. Only passive interactions are allowed (holding, displaying, wearing, or placing the product). Do NOT include actions like opening gates/doors/lids, pressing buttons, pulling zippers, folding/unfolding parts, or rotating movable components.
5. **Single-View Constraint**: The product MUST only be shown from angles visible in the starting frame image. Do NOT rotate the product to show the back, hidden sides, or any angles that were not captured in the reference image. The camera can move around the scene, but the product should maintain its original front-facing orientation.
6. **Background Continuity**: Ensure smooth and consistent background throughout the video. When the camera zooms or moves, the background environment must remain spatially coherent. Avoid any "picture stitching" effects where the outer edges of the frame show a different environment or visible seams.
7. **Natural Skin Texture**: Render natural skin texture with detail, no smoothing applied. Preserve natural skin imperfections, pores, and texture. Avoid artificial, over-processed, or "beauty filter" appearances.
8. **Natural Indoor Lighting**: For indoor scenes, use soft, diffused lighting that feels natural and realistic. Avoid harsh, direct lighting on faces that creates overexposed highlights or strong shadows. Lighting should feel like natural window light or well-balanced ambient indoor lighting, reducing any strong spotlight effects on people's faces.

The image above is used as the first frame of this video.

The story for video clip is in [SCENE_SCRIPT].

[SCENE_SCRIPT]
{{SCENE_SCRIPT}}

The following prompt was previously used to generate a video, but it FAILED quality evaluation:

[ORIGINAL PROMPT]
{{ORIGINAL_PROMPT}}

[EVALUATION FEEDBACK]
{{FEEDBACK}}

Based on the original prompt and the evaluation feedback, create 1 IMPROVED prompt that specifically addresses and fixes the issues listed above.

Make sure the character delivers the exact speech in the video. Highlight the **Pacing and Closing** description in the prompt.

**CRITICAL**: You MUST also include a negative prompt to explicitly specify elements to AVOID for realistic character rendering.

Use this JSON schema for output:
{
"video_prompt": "Improved prompt for video generation that addresses the failed criteria.",
"negative_prompt": "Up to 5 items maximum. Example: over-smoothed poreless skin, beauty filter effect, plastic wax-like appearance, harsh direct lighting, flat lighting"
}"""
    prompt = prompt.replace("{{SCENE_SCRIPT}}", scene_script)
    prompt = prompt.replace("{{ORIGINAL_PROMPT}}", original_prompt if original_prompt else "N/A")
    prompt = prompt.replace("{{FEEDBACK}}", feedback_text)
    return prompt


def get_video_eval_prompt(num_of_videos: int, output_language: str = "English") -> str:
    """Create prompt for evaluating generated videos against quality criteria.
    
    Args:
        num_of_videos: Number of videos to evaluate
        output_language: Language for evaluation output
        
    Returns:
        str: Formatted video evaluation prompt
    """
    prompt = """You are an expert at evaluating video clips.
    
You will be provided with: 
- A reference Image: The actual product photo (FIRST image provided). Study this image CAREFULLY.
- A set of generated video clips: the marketing videos featuring a character interacting with or wearing the product.

There are {{ALL_COUNT}} video clips above. 

You must analyze each candidate video against the [EVALUATION CRITERIA], score them, and select the single best video for the campaign.

**CRITICAL: Before evaluating, you MUST carefully examine the reference product image and note:**
- The EXACT color(s) of the product
- The EXACT shape and proportions
- ALL hardware/accessories (handles, clasps, zippers, buckles, chains, buttons, straps)
- Material texture and finish (leather grain, fabric weave, metal sheen, etc.)
- Any patterns, logos, embossing, or decorative elements
- Any unique design features

[EVALUATION CRITERIA]

1. Product Appearance Consistency & Detail Preservation (STRICT - Most Important):
    **This is the most critical criterion. FAIL if ANY of the following are not met:**
    
    a) COLOR ACCURACY: The product's color(s) must EXACTLY match the reference image throughout the entire video.
       - FAIL if colors shift, fade, change shade, or differ from the reference at any frame.
       - FAIL if lighting causes unnatural color changes that don't match the reference.
    
    b) SHAPE & PROPORTIONS: The product's overall shape, dimensions, and proportions must be preserved throughout.
       - FAIL if the product appears stretched, compressed, or deformed during motion.
       - FAIL if the product's shape differs from the reference at any point.
       - FAIL if the product fuses with or blends into the character's body/clothing.
    
    c) HARDWARE FIDELITY: ALL hardware details (handles, clasps, zippers, buckles, chains, buttons, straps) must match the reference and remain consistent.
       - FAIL if any hardware is missing, added, or looks different from the reference.
       - FAIL if handles have different shapes, positions, or materials.
       - FAIL if clasps, zippers, or buckles disappear, reappear, or change appearance.
       - FAIL if the number of hardware elements differs from the reference.
    
    d) MATERIAL & TEXTURE: The product's material appearance must remain consistent with the reference.
       - FAIL if leather looks like fabric, or metal looks like plastic, etc.
       - FAIL if texture patterns (grain, weave, sheen) change during the video.
       - FAIL if material finish appears inconsistent with the reference.
    
    e) TEXT & LOGO ACCURACY: Any text, logos, brand names, or labels visible on the product must match the reference EXACTLY.
       - FAIL if text becomes unreadable, distorted, or changes during video.
       - FAIL if logos disappear, shift position, or change appearance.
    
    f) NO HALLUCINATIONS: The product must NOT have any NEW features not present in the reference.
       - FAIL if new locks, handles, pockets, straps, or decorations suddenly appear.
       - FAIL if parts that weren't visible in the reference suddenly appear (e.g., back pockets when only front was shown).
       - FAIL if the product is rotated to show unverified angles not in the reference image (Single-view validation).
    
    g) PRODUCT VISIBILITY CONTINUITY: The product MUST remain visible throughout the entire video.
       - FAIL if the product suddenly disappears, fades out unexpectedly, or becomes invisible.
       - FAIL if the product teleports to a different location without natural movement.
       - The product should maintain continuous presence from start to end.

2. Adherence to Physical Laws:
    - Physics: When displayed or worn, the product must reflect its actual weight and material physical characteristics.
    - Weight Transfer Realism: If the product is initially held with two hands and one hand releases it, the remaining hand MUST visibly adjust, shift, or show strain to compensate for the changed weight distribution. 
    - Interaction: Natural holding/wearing behavior. The character should NOT operate the product in ways that change its physical state (e.g., opening gates/doors/lids, pressing buttons, pulling zippers, folding/unfolding parts, rotating movable components). Only passive display interactions (holding, wearing, placing) are acceptable.
    - No Spontaneous State Changes: The product must NOT suddenly change its state or status without human action or a logical cause. For example, wheels should not start spinning, buttons should not press themselves, and parts should not move on their own without visible interaction.
    - Product Position Continuity: The product MUST maintain a consistent, natural position relative to the character throughout the video. REJECT if the product suddenly appears at a different location without natural movement (e.g., a backpack worn on the back suddenly appearing at the front when the model turns, or a bag teleporting from one hand to another). If the character turns or moves, the product position must change naturally according to physics.
    - No Sudden Appearances: REJECT if the product suddenly "pops" into view from nowhere, appears in a different position without natural movement, or teleports between frames. The product must have continuous, physically plausible motion throughout the video.

3. Character Realism & Performance:
    - Skin Texture Quality (CRITICAL for Realism):
       * FAIL if skin appears unnaturally smooth with no visible pores or texture (beauty filter effect)
       * FAIL if skin has "airbrushed" or over-retouched appearance
       * FAIL if skin looks plastic, waxy, or CGI-like rather than natural human skin
       * FAIL if skin tone is unnaturally uniform without natural color variations
       * PASS requires: visible skin pores, natural imperfections (fine lines, subtle blemishes), realistic texture throughout the video
    
    - Lighting on Face (CRITICAL for Realism):
       * FAIL if harsh, direct spotlight creates overexposed highlights or "blown out" areas on face
       * FAIL if flat, frontal lighting removes all skin texture and facial contours
       * FAIL if lighting creates unnatural shadows or harsh contrast on facial features
       * FAIL if face appears "glowing" or unnaturally bright compared to environment
       * PASS requires: soft, diffused lighting that preserves skin texture and natural facial contours
    
    - Face: Clear facial features with natural skin imperfections preserved.
    - Mouth: Clear lip details. Mouth shape should be natural when speaking, with clear teeth details.
    - Lip Sync: Audio-visual synchronization. Avoid cases where there is speech but no mouth movement. Slightly mismatched lip shapes are acceptable.
    - Movement: Enhance richness of character movements, adapted to the environment.
    - Anatomy: Realistic body, 5 fingers, natural motions.

4. Environment & Context Match:
    - Character actions must match the corresponding environment.

5. Video Technical Quality:
    - First Frame Quality **CRITICAL**: The video should start with high quality, sharp details. Make sure the model face and objects are depicted in detail from the very first frame. The video MUST start with a crystal-clear first frame where the character's face is in SHARP FOCUS with clearly visible facial details (eyes, nose, mouth, skin texture).
    - Visual Noise & Artifacts: Check for visual noise, random artifacts, or anomalies throughout the video (e.g., random light spots, bokeh effects, flickering, grain, ghosting).
    - Background Continuity: Check for background stitching artifacts during camera movements (especially zoom). Reject if the outer areas of the frame show inconsistent environments, visible seams, or "picture-in-picture" effects where the background appears to be from a different scene. The entire visible background must maintain spatial consistency throughout the video.

Please put the index value in "best" to see which one has the best result. Respond in {{LANGUAGE}}.

**EVALUATION PRIORITY:** Product Appearance Consistency & Detail Preservation is the MOST IMPORTANT criterion. If a generated video fails this criterion, it should be marked as FAIL regardless of how well it performs on other criteria.

Use this JSON schema for output:
{
    "evaluation_results":[
        {
            "video_index": (integer) the index of the video,
            "criteria":{
                "product_appearance_consistency": {
                    "status": "PASS/FAIL",
                    "color_match": "PASS/FAIL with details",
                    "shape_match": "PASS/FAIL with details",
                    "hardware_match": "PASS/FAIL with details",
                    "texture_match": "PASS/FAIL with details",
                    "text_logo_match": "PASS/FAIL with details",
                    "no_hallucinations": "PASS/FAIL with details",
                    "visibility_continuity": "PASS/FAIL with details",
                    "reasoning": "Detailed comparison of product in video vs reference image. List any differences, inconsistencies, or issues found throughout the video."
                },
                "adherence_to_physical_laws": {
                    "status": "PASS/FAIL",
                    "physics_realism": "PASS/FAIL - product weight and material behave realistically",
                    "interaction_quality": "PASS/FAIL - natural holding/wearing without operating the product",
                    "position_continuity": "PASS/FAIL - product maintains consistent position relative to character",
                    "reasoning": "Assessment of physical law adherence including weight, interaction, and position continuity"
                },
                "character_realism": {
                    "status": "PASS/FAIL",
                    "skin_texture_quality": "PASS/FAIL - describe if skin appears natural with visible pores and texture, or if it looks over-smoothed/airbrushed/plastic",
                    "lighting_on_face": "PASS/FAIL - describe if lighting is soft and natural, or harsh/flat/overexposed",
                    "reasoning": "Detailed assessment of skin texture realism and facial lighting quality"
                },
                "environment_context_match": {
                    "status": "PASS/FAIL",
                    "reasoning": "Detailed explanation"
                },
                "video_technical_quality": {
                    "status": "PASS/FAIL",
                    "reasoning": "Detailed explanation"
                }
            }
        }
    ],
    "best": (integer) index of the best video clip (0 ~ {{END_IDX}})
}"""
    prompt = prompt.replace("{{END_IDX}}", str(num_of_videos - 1))
    prompt = prompt.replace("{{ALL_COUNT}}", str(num_of_videos))
    prompt = prompt.replace("{{LANGUAGE}}", str(output_language))
    return prompt


def get_end_frame_select_prompt(k_frames: int) -> str:
    """Create prompt for selecting the best ending frame from video.
    
    Args:
        k_frames: Number of frames to evaluate
        
    Returns:
        str: Formatted end frame selection prompt
    """
    prompt = """You are an expert at evaluating video frames for professional marketing content.
    
Your task is to select the BEST valid ending frame from the last {{ALL_COUNT}} frames of a video featuring a person speaking about a product.

Selection Criteria:
1. **Speech Completion**: The character has clearly finished talking - mouth is closed or in a natural resting position, NOT mid-word or with mouth open awkwardly
2. **Eyes Still and In Focus**: The eyes are completely still, NOT moving, and in SHARP FOCUS. REJECT any frame where the eyes appear to be in motion, shifting gaze, or are blurry/unfocused.
3. **Settled Still Pose**: Face and body have settled into a stable, still resting position - NOT in transition, NOT still moving
4. **Visual Clarity**: The frame is clear, sharp, and in focus - NOT blurred
5. **Before Post-Take Movement**: Before the person starts another movement (e.g., relaxing arms, looking away, eye movement)

Your Goal:
Find the BEST frame where:
- Speech is definitely complete
- Eyes are looking at the camera, completely still and in sharp focus (NOT moving or shifting)
- Person is in a natural, still pose with face details in focus
- Before any post-take movement begins

If in doubt between two frames, select the one with superior sharpness, focus, and clarity of facial features.

The BEST valid ending frame should look like a natural, professional ending to a video recommendation - as if the person just finished their enthusiastic pitch and is confidently looking at the camera with still, focused eyes.

There are {{ALL_COUNT}} images above representing the last frames of the video in chronological order.

Use this JSON schema for output:
{
    "reasoning": (string) brief explanation of why this frame was selected,
    "best": (integer) index of the best valid ending frame (0 ~ {{END_IDX}})
}"""
    prompt = prompt.replace("{{ALL_COUNT}}", str(k_frames))
    prompt = prompt.replace("{{END_IDX}}", str(k_frames - 1))
    return prompt
