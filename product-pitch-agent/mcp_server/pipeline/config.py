# Copyright 2025 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    LOG_DIR: str = "temp/logs"
    LOG_STDOUT_FILENAME: str = "genmedia_demo_stdout.log"
    LOG_STDERR_FILENAME: str = "genmedia_demo_stderr.log"

    TEMP_OUTPUT_DIR: str = "output_mcp"
    
    # GCP related
    VERTEX_AI_PROJECT_ID: str
    VERTEX_AI_PREVIEW_LOCATION: str
    VERTEX_AI_LOCATION: str
    GCS_BUCKET_NAME: str
    GCS_PREFIX: str
    
    # Google Drive related (optional - for manual upload)
    GDRIVE_FOLDER_ID: str = ""  # Root folder ID for Drive upload (e.g., veo_output folder)
    GDRIVE_SERVICE_ACCOUNT_KEY: str = "gdrive-service-account.json"  # Service account key file path
    
    # -----------------------------------------------------------------------------
    # Model Configuration
    # -----------------------------------------------------------------------------
    # Veo model version: veo2, veo3, veo3.1, veo3.1-preview
    VEO_MODEL_VERSION: str = "veo3.1"
    
    # Gemini model IDs
    GEMINI_MODEL_PRO: str = "gemini-3.1-pro-preview"
    GEMINI_MODEL_FLASH: str = "gemini-3-flash-preview"
    GEMINI_MODEL_IMAGE: str = "gemini-3-pro-image-preview"
    
    # -----------------------------------------------------------------------------
    # Default Pipeline Parameters
    # -----------------------------------------------------------------------------
    DEFAULT_COMPANY_NAME: str = "Cymbal Shop"
    DEFAULT_DATA_DIR: str = "data"
    
    # Max sample attempts for generation loops
    MAX_SAMPLE_IMAGES: int = 1
    MAX_SAMPLE_CLIPS: int = 1
    
    # -----------------------------------------------------------------------------
    # Video Generation Defaults
    # -----------------------------------------------------------------------------
    VEO_DEFAULT_SEED: int = 42
    VEO_DEFAULT_SAMPLE_COUNT: int = 1
    VEO_DEFAULT_ASPECT_RATIO: str = "16:9"
    VEO_DEFAULT_RESOLUTION: str = "1080p"

    # -----------------------------------------------------------------------------
    # Image Generation Defaults
    # -----------------------------------------------------------------------------
    # Gemini image_size: "1K" | "2K" | "4K"
    IMAGE_RESOLUTION: str = "1K"
    
    # -----------------------------------------------------------------------------
    # FPS Settings
    # -----------------------------------------------------------------------------
    # FPS for analyzing YouTube videos (lower = fewer tokens)
    VIDEO_ANALYSIS_FPS: int = 3
    # FPS for video evaluation with Gemini (lower = fewer tokens)
    VIDEO_EVAL_FPS: int = 3
    
    # -----------------------------------------------------------------------------
    # Video Duration
    # -----------------------------------------------------------------------------
    DEFAULT_VIDEO_DURATION: int = 8  # Target video duration in seconds
    
    # -----------------------------------------------------------------------------
    # Post-Processing Defaults
    # -----------------------------------------------------------------------------
    POSTPROCESS_FPS: int = 24  # FPS used for frame trimming calculations
    POSTPROCESS_K_FRAMES: int = 12  # Number of ending frames to evaluate
    
    # -----------------------------------------------------------------------------
    # Retry/Resilience Settings
    # -----------------------------------------------------------------------------
    GEMINI_MAX_RETRIES: int = 3  # Max retries for Gemini API calls
    VEO_WAIT_TIMEOUT: int = 60  # Max wait iterations for Veo job completion
    VEO_SLEEP_TIME: int = 15  # Sleep time (seconds) between Veo status checks
    

def get_settings():
    return Settings()


settings = get_settings()
