import os
import uuid
from PIL import Image as PIL_Image
from mcp_server.pipeline.log import log


# Aspect ratio constants
ASPECT_RATIOS = {
    "16:9": 16 / 9,   # 1.7778 - landscape
    "9:16": 9 / 16,   # 0.5625 - portrait
}


def crop_to_aspect_ratio(
    image: PIL_Image.Image,
    target_aspect_ratio: str = "16:9",
    max_crop_percent: float = 5.0
) -> PIL_Image.Image:
    """Crop an image to exact aspect ratio using center crop.
    
    This function ensures generated images have the exact aspect ratio
    needed for video generation, eliminating black bars in the final video.
    
    Args:
        image: PIL Image to crop
        target_aspect_ratio: Target aspect ratio string (e.g., "16:9", "9:16")
        max_crop_percent: Maximum percentage of content that can be cropped.
                         If cropping would exceed this, returns original image.
                         Default: 10.0 (10%)
    
    Returns:
        PIL Image: Cropped image with exact target aspect ratio,
                   or original image if crop would exceed threshold
    """
    if target_aspect_ratio not in ASPECT_RATIOS:
        log.warning(f"Unknown aspect ratio '{target_aspect_ratio}', returning original image")
        return image
    
    target_ratio = ASPECT_RATIOS[target_aspect_ratio]
    
    current_width, current_height = image.size
    current_ratio = current_width / current_height
    
    # Check if already at target ratio (within 0.1% tolerance)
    ratio_diff = abs(current_ratio - target_ratio) / target_ratio * 100
    if ratio_diff < 0.1:
        log.info(f"Image already at target aspect ratio {target_aspect_ratio}")
        return image
    
    # Calculate new dimensions for center crop
    if current_ratio > target_ratio:
        # Image is wider than target - crop width
        new_width = int(current_height * target_ratio)
        new_height = current_height
        crop_percent = (current_width - new_width) / current_width * 100
    else:
        # Image is taller than target - crop height
        new_width = current_width
        new_height = int(current_width / target_ratio)
        crop_percent = (current_height - new_height) / current_height * 100
    
    # Check if crop exceeds threshold
    if crop_percent > max_crop_percent:
        log.warning(
            f"Aspect ratio correction would crop {crop_percent:.1f}% of image "
            f"(threshold: {max_crop_percent}%). Skipping correction."
        )
        log.warning(f"Original: {current_width}x{current_height} ({current_ratio:.4f}), "
                   f"Target: {target_aspect_ratio} ({target_ratio:.4f})")
        return image
    
    # Calculate crop box (center crop)
    left = (current_width - new_width) // 2
    top = (current_height - new_height) // 2
    right = left + new_width
    bottom = top + new_height
    
    # Perform crop
    cropped_image = image.crop((left, top, right, bottom))
    
    log.info(
        f"Cropped image from {current_width}x{current_height} to {new_width}x{new_height} "
        f"({crop_percent:.1f}% removed) for aspect ratio {target_aspect_ratio}"
    )
    
    return cropped_image


def get_image_aspect_ratio(image: PIL_Image.Image) -> tuple:
    """Get the aspect ratio information for an image.
    
    Args:
        image: PIL Image to analyze
        
    Returns:
        tuple: (width, height, ratio_float, closest_standard_ratio)
    """
    width, height = image.size
    ratio = width / height
    
    # Find closest standard ratio
    closest_ratio = min(ASPECT_RATIOS.keys(), 
                       key=lambda r: abs(ASPECT_RATIOS[r] - ratio))
    
    return width, height, ratio, closest_ratio


class CommonUtils:
    
    @staticmethod
    def get_file_name(file_path):
        """Extract filename from file path"""
        return os.path.basename(file_path)
    
    @staticmethod
    def get_unique_identifier():
        """Generate a unique identifier"""
        return str(uuid.uuid4())
    
    @staticmethod
    def mkdirs(directory):
        """Create directory if it doesn't exist"""
        os.makedirs(directory, exist_ok=True)
