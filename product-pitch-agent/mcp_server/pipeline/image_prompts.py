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
Image generation and evaluation prompt templates.

This module contains all prompt templates for:
- Image generation from product reference
- Image generation with feedback
- Image quality evaluation
"""


def get_image_generation_prompt_from_product(country: str, product_desc: str) -> str:
    """Create prompt for dynamic image generation based on product reference.
    
    Args:
        country: Target country for the advertisement
        product_desc: Product description
        
    Returns:
        str: Formatted prompt for image generation
    """
    prompt = """You are an expert advertising director for Youtube videos. You are producing a video, and for that you want to create an image for the video to start with. Therefore, you need the prompts to create or edit the image.

And the image above is a reference product image to advertise for. 

Product: {{PRODUCT}}

Before creating the prompt, you MUST carefully analyze the reference product image and identify ALL of the following details that MUST be preserved EXACTLY in the generated image:

1. **Product Analysis:**
   - Exact color(s) and color patterns of the product
   - Material appearance (leather texture, fabric weave, metal finish, plastic sheen, etc.)
   - All hardware details (handles, clasps, zippers, buckles, buttons, straps, chains)
   - Exact size, shape, proportions, and dimensions of the product
   - Any logos, brand names, or text visible on the product
   - Surface patterns, embossing, stitching, or decorative elements
   - Any unique design features that make this product distinctive

2. **Gender Selection:** 
Identify the most commercially effective gender for this product. Example: If the image shows makeup, select Female. If it shows power tools, select Male. For neutral products, select the most aspirational persona.

3. **Interaction Mode:** 

- Mode A (General/Holding): If the product is a standalone object (gadget, bottle, machine, food) OR if the product is a baby/child item that cannot be worn by the adult model (e.g., baby toys, baby rompers). 
  Product Size: Estimate the product size based on the description.
  Display: The adult model should hold the product or it should be placed on a surface/side. 
  Contents: If the product needs other contents to showcase how the product is used in real life. For example a grocery bag is usually filled with some oranges when advertising for the bag.

- Mode B (Wearable): If the product is designed to be worn by an adult (bags, clothing, eyewear, jewelry, watches, hats) or is maternity wear. 
  Display: The adult model should be wearing the product with a natural fit.
  
4. **Environment Selection:** Choose a background environment that naturally matches the product category. Supported environments include but are not limited to:
- Factory/Warehouse (for industrial products, bulk items)
- Home/Living Room/Kitchen (for household items, appliances, decor)
- Studio/Home Office (for electronics, gadgets, professional items)
- Outdoor/Nature/Street (for outdoor gear, travel items, activewear)
- Specialized Locations (e.g., Yoga Studio for yoga wear, Gym for fitness gear)

The story for the video clip is in [SCENE_SCRIPT]. 

[SCENE_SCRIPT]
Country: {{COUNTRY}}

This script outlines the requirements for generating an immersive, 4K hyper-realistic starting frame from a marketing video production.

The scene features a successful, charismatic male or female e-commerce entrepreneur in his or her late 20s to 30s, situated in the chosen background environment with vibrant, professional lighting.

The character features distinct, representative traits of the specific country. The central focus is a tight, clear shot of a product that the entrepreneur is actively presenting and enthusiastically recommending.

A critical requirement is strict adherence to real-world physical laws regarding the product's display:

If Mode A (General/Holding): The product must adhere to real-world physics (weight and scale). If the product is too large/heavy to hold, it must be placed on the ground or a professional stand. The entrepreneur should interact naturally (squatting, leaning, or pointing). Materials (metal, glass, etc.) must show realistic light reflection and surface texture.

If Mode B (Wearable): The entrepreneur must be wearing or trying on the product. It must maintain a perfect, natural fit to the body part (wrist, face, torso). Ensure realistic fabric drape, folds, or accessory balance. Textures like fabric weave or metal luster must be ultra-detailed. The wearing behavior must be common and natural in reality.

**PRODUCT PRESERVATION RULES (MUST FOLLOW):**
- The product [1] MUST maintain its EXACT original appearance from the reference image
- DO NOT add, remove, or modify any product features (handles, clasps, zippers, decorations, etc.)
- Preserve the EXACT colors, materials, and textures of the product
- Maintain the product's proportions and shape precisely
- Any hardware or accessories on the product must appear exactly as in the reference

Please carefully review the contents of [SCENE_SCRIPT] and create a prompt for creating the starting image of the video clip. 

Use this JSON schema for output.

{
"product_details_to_preserve": "List the specific product details you identified that MUST be preserved (colors, materials, hardware, shape, patterns, etc.)",
"Prompt for image editing": "Prompt to modify the reference image. The object to be modified is represented as [1]. MUST include explicit instructions to preserve all product details listed above."
}"""
    prompt = prompt.replace("{{PRODUCT}}", product_desc)
    prompt = prompt.replace("{{COUNTRY}}", country)
    return prompt


def get_image_prompt_with_feedback(country: str, product_desc: str, original_prompt: str, failed_criteria: list) -> str:
    """Generate an improved image generation prompt based on the original failed prompt and evaluation feedback.
    
    Args:
        country: Target country for the advertisement
        product_desc: Product description
        original_prompt: The original prompt that was used (which failed evaluation)
        failed_criteria: List of failed criteria from previous evaluation
        
    Returns:
        str: Prompt asking for an improved image generation prompt
    """
    # Import here to avoid circular dependency
    from mcp_server.pipeline.evaluator import format_failed_criteria_for_prompt
    feedback_text = format_failed_criteria_for_prompt(failed_criteria)
    
    prompt = """You are an expert advertising director for Youtube videos. You are producing a video, and for that you want to create an image for the video to start with.

The image above is a reference product image to advertise for.

Product: {{PRODUCT}}
Country: {{COUNTRY}}

The following prompt was previously used to generate an image, but it FAILED quality evaluation:

[ORIGINAL PROMPT]
{{ORIGINAL_PROMPT}}

[EVALUATION FEEDBACK]
{{FEEDBACK}}

Based on the original prompt and the evaluation feedback, create an IMPROVED prompt that specifically addresses and fixes the issues listed above.

Use this JSON schema for output:

{
"Prompt for image editing": "Improved prompt to modify the reference image that addresses the failed criteria. The object to be modified is represented as [1]"
}"""
    prompt = prompt.replace("{{PRODUCT}}", product_desc)
    prompt = prompt.replace("{{COUNTRY}}", country)
    prompt = prompt.replace("{{ORIGINAL_PROMPT}}", original_prompt)
    prompt = prompt.replace("{{FEEDBACK}}", feedback_text)
    return prompt


def get_image_eval_prompt(product_desc: str, num_of_images: int, output_language: str = "English") -> str:
    """Create prompt for evaluating generated images against quality criteria.
    
    Args:
        product_desc: Product description
        num_of_images: Number of images to evaluate
        output_language: Language for evaluation output
        
    Returns:
        str: Formatted evaluation prompt
    """
    prompt = """You are a Visual Quality Assurance Expert for an e-commerce platform. You specialize in detecting hallucinations, inconsistencies, and physical law errors in AI-generated marketing imagery.

Product: {{PRODUCT}}

You will also be provided with: 
- A reference Image: The actual product photo (FIRST image provided). Study this image CAREFULLY.
- A set of generated Images: the marketing images featuring a character interacting with or wearing the product.

You must analyze each candidate image against the [EVALUATION CRITERIA], score them, and select the single best image for the campaign.

**CRITICAL: Before evaluating, you MUST carefully examine the reference product image and note:**
- The EXACT color(s) of the product
- The EXACT shape and proportions
- ALL hardware/accessories (handles, clasps, zippers, buckles, chains, buttons, straps)
- Material texture and finish (leather grain, fabric weave, metal sheen, etc.)
- Any patterns, logos, embossing, or decorative elements
- Any unique design features

[EVALUATION CRITERIA]

1. Product Detail Preservation (STRICT - Most Important):
    **This is the most critical criterion. FAIL if ANY of the following are not met:**
    
    a) COLOR ACCURACY: The product's color(s) in the generated image must EXACTLY match the reference image. 
       - FAIL if colors are different shades, tints, or completely different colors.
    
    b) SHAPE & PROPORTIONS: The product's overall shape, dimensions, and proportions must be preserved.
       - FAIL if the product appears stretched, compressed, or differently shaped.
    
    c) HARDWARE FIDELITY: ALL hardware details (handles, clasps, zippers, buckles, chains, buttons, straps) must match the reference.
       - FAIL if any hardware is missing, added, or looks different from the reference.
       - FAIL if handles have different shapes, positions, or materials.
       - FAIL if clasps, zippers, or buckles are missing or altered.
       - FAIL if the number of total clasps, total buckles, or total straps differs from the reference.
    
    d) MATERIAL & TEXTURE: The product's material appearance must be consistent.
       - FAIL if leather looks like fabric, or metal looks like plastic, etc.
       - FAIL if texture patterns are significantly different.
    
    e) DESIGN FEATURES: Any unique design elements must be preserved.
       - FAIL if patterns, logos, embossing, or stitching are missing or altered.
       - FAIL if decorative elements are added that weren't in the original.
    
    f) NO HALLUCINATIONS: The product must not have any NEW features not present in the reference.
       - FAIL if locks, extra pockets, straps, or other elements appear that weren't in the original.

2. Character-Product Alignment:
    - Gender Match: For products with clear gender characteristics (e.g., cosmetic bags), use a corresponding gendered digital human (e.g., female).
    - Outfit Match: The digital human's clothing must match the product context.For example, wearing outdoor clothing for outdoor products, or matching yoga wear for yoga pants (avoiding mismatched clothing like shirts with yoga pants).

3. Adherence to Physical Laws:
    - Physics: When displayed or worn, the product must reflect its actual weight and material physical characteristics.
    - Interaction: Is the character holding or wearing the product naturally? (e.g., fingers shouldn't clip through the object, handles should be gripped correctly).
    - Lighting & Gravity: Do shadows fall consistently? Does clothing drape naturally?

4. Character Realism & Normality:
    - Face: Natural lighting, natural skin imperfections, reduce over-smoothing (plastic look).
    - Details: Clear lip details; teeth should be clear and natural.
    - Anatomy: Check for AI artifacts. Face (eyes symmetrical), Hands (exactly 5 fingers), Limbs (natural joints/positions).

5. Environment & Context Match:
    - Environment: Support rich product display environments that match the product.
    - Action Match: Actions must match the corresponding environment. (e.g., trying on yoga clothes in a yoga studio).

**EVALUATION PRIORITY:** Product Detail Preservation is the MOST IMPORTANT criterion. If a generated image fails this criterion, it should be marked as FAIL regardless of how well it performs on other criteria.

Please put the index value in "best" to see which one has the best result. Respond in {{LANGUAGE}}.

Output Format:

Provide your analysis in the following JSON format:

{
    "evaluation_results":[
        {
            "image_index": (integer) the index of the image,
            "criteria":{
                "product_detail_preservation": {
                    "status": "PASS/FAIL",
                    "color_match": "PASS/FAIL with details",
                    "shape_match": "PASS/FAIL with details",
                    "hardware_match": "PASS/FAIL with details",
                    "texture_match": "PASS/FAIL with details",
                    "no_hallucinations": "PASS/FAIL with details",
                    "reasoning": "Detailed comparison of product in generated image vs reference image. List any differences found."
                },
                "character_product_alignment": {
                    "status": "PASS/FAIL",
                    "reasoning": "Assessment of gender and outfit matching."
                },
                "adherence_to_physical_laws": {
                    "status": "PASS/FAIL",
                    "reasoning": "Assessment of physics, interaction, and gravity."
                },
                "character_realism_normality": {
                    "status": "PASS/FAIL",
                    "reasoning": "Assessment of face/skin details, anatomy (fingers), and lighting."
                },
                "environment_context_match": {
                    "status": "PASS/FAIL",
                    "reasoning": "Assessment of environment suitability and action alignment."
                }
            }
        }
    ],
    "best": (integer) index of the best image (0 ~ {{END_INDEX}}), or -1 if no image passes Product Detail Preservation
}"""
    prompt = prompt.replace("{{PRODUCT}}", product_desc)
    prompt = prompt.replace("{{END_INDEX}}", str(num_of_images - 1))
    prompt = prompt.replace("{{LANGUAGE}}", output_language)
    return prompt
