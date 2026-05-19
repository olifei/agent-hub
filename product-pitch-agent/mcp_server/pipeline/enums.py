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

from enum import Enum, unique
from enum import IntEnum as SourceIntEnum
from typing import Type

class _EnumBase:
    @classmethod
    def get_member_keys(cls: Type[Enum]) -> list[str]:
        return [name for name in cls.__members__.keys()]

    @classmethod
    def get_member_values(cls: Type[Enum]) -> list:
        return [item.value for item in cls.__members__.values()]
    

class IntEnum(_EnumBase, SourceIntEnum):
    pass


class StrEnum(_EnumBase, str, Enum):
    pass

# Note: GeminiModelType values are now configurable via settings.
# Use settings.GEMINI_MODEL_PRO, settings.GEMINI_MODEL_FLASH, settings.GEMINI_MODEL_IMAGE
# for the actual model IDs. The enum serves as a type-safe reference.
@unique
class GeminiModelType(str, Enum):
    PRO = "pro"
    FLASH = "flash"
    IMAGE = "image"

@unique
class GeminiCreativityLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@unique
class GeminiToolList(str, Enum):
    GOOGLE_SEARCH = "google_search"


@unique
class ImagenCustomizationSubjectType(str, Enum):
    SUBJECT_TYPE_DEFAULT = "SUBJECT_TYPE_DEFAULT"
    SUBJECT_TYPE_PERSON = "SUBJECT_TYPE_PERSON"
    SUBJECT_TYPE_ANIMAL = "SUBJECT_TYPE_ANIMAL"
    SUBJECT_TYPE_PRODUCT = "SUBJECT_TYPE_PRODUCT"
    
@unique
class CustomEvalCriterion(str, Enum):
    END_FRAME_SHARPNESS = "end_frame_sharpness"
    NEGATIVE_POSE_DETECTION = "negative_pose_detection"
    
@unique
class PreprocessSteps(str, Enum):
    FIRST_LAST_FRAME_AUTOSELECTION = "first_last_frame_autoselection"
    IMAGE_UPSCALING = "image_upscaling"
    
@unique
class PostprocessSteps(str, Enum):
    ADD_BG_MUSIC = "add_bg_music"
    END_FRAME_SHARPENING = "end_frame_sharpening"
