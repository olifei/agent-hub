
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

import os
import json
import random
import base64
import time
import requests
import subprocess

import google.auth
from google.cloud import secretmanager

# Jingyi's update: change to genai package
from google import genai
from google.genai import types

from vertexai.vision_models import ImageGenerationModel

from mcp_server.pipeline.log import log
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.common_utils import CommonUtils
from mcp_server.pipeline.enums import GeminiModelType, GeminiCreativityLevel, GeminiToolList, ImagenCustomizationSubjectType


class VertexAIService:

    def __init__(self):
        self.__init_gemini()
        self.__init_imagen_customization()
        self.__init_veo()
        self.__init_gcp_token_manage()

    def __init_gcp_token_manage(self):
        self.google_auth_scopes = [
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/compute",
        ]
        secret_id = "corp-account-access-token"
        self.secret_name = (
            f"projects/{settings.VERTEX_AI_PROJECT_ID}/secrets/{secret_id}"
        )
        self.sm_client = secretmanager.SecretManagerServiceClient()
    
    def __init_imagen_customization(self) -> None:
        self.imagen_cust_project_id = settings.VERTEX_AI_PROJECT_ID
        
        self.imagen_upscale_model_id = "imagen-4.0-upscale-preview"
        self.imagen_cust_endpoint_url = "https://us-central1-aiplatform.googleapis.com"

    def __init_veo(self) -> None:
        veo_model_id = {
            "veo2": "veo-2.0-generate-001",
            "veo3": "veo-3.0-generate-001",
            "veo3.1": "veo-3.1-generate-001",
            "veo3.1-preview": "veo-3.1-generate-preview"
        }
        self.veo_project_id = settings.VERTEX_AI_PROJECT_ID
        # Use configurable model version from settings
        model_id = veo_model_id.get(settings.VEO_MODEL_VERSION, "veo-3.1-generate-preview")

        self.veo_base_endpoint_url = f"https://us-central1-aiplatform.googleapis.com/v1beta1/projects/{self.veo_project_id}/locations/{settings.VERTEX_AI_LOCATION}/publishers/google/models/{model_id}"
        self.veo_model_url = f"{self.veo_base_endpoint_url}:predictLongRunning"
        self.veo_status_url = f"{self.veo_base_endpoint_url}:fetchPredictOperation"

    def __init_gemini(self) -> None:
        self.gemini_client = genai.Client(
            vertexai=True,
            project=settings.VERTEX_AI_PROJECT_ID,
            location=settings.VERTEX_AI_PREVIEW_LOCATION,
        )
        
        self.safety_settings = [
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="OFF"
            )
        ]
        

        # @TODO
        # search is changed for 2.0 : https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_2_0_flash.ipynb
        # self.google_search_tool = Tool.from_google_search_retrieval(
        #     grounding.GoogleSearchRetrieval()
        # )
        self.google_search_tool = types.Tool(google_search=types.GoogleSearch())

    def _create_multimodal_part(self, file_uri: str, mime_type: str, fps: int = None) -> types.Part:
        """
        Create a multimodal Part with proper video_metadata handling.
        video_metadata (fps) is only applied to video type files.
        
        Args:
            file_uri: The URI of the file (e.g., gs://bucket/file.mp4)
            mime_type: The MIME type of the file (e.g., video/mp4, image/png)
            fps: Optional FPS for video sampling (only applied to video files)
        
        Returns:
            types.Part: A properly constructed Part object
        """
        # For video files, use Part constructor with FileData and video_metadata
        if mime_type.startswith("video/"):
            file_data = types.FileData(file_uri=file_uri, mime_type=mime_type)
            if fps is not None:
                video_metadata = types.VideoMetadata(fps=fps)
                log.info(f"[Gemini] Video input with fps={fps}: {file_uri}")
                return types.Part(file_data=file_data, video_metadata=video_metadata)
            else:
                return types.Part(file_data=file_data)
        else:
            # For other types (images, etc.), use from_uri method
            return types.Part.from_uri(file_uri=file_uri, mime_type=mime_type)

    def get_gcp_access_token(self) -> str:
        return self.__get_access_token()

    def __get_access_token_from_secret_manager(self) -> str:
        response = self.sm_client.access_secret_version(
            request={"name": f"{self.secret_name}/versions/latest"}
        )
        payload = response.payload.data.decode("UTF-8")
        return payload

    def __get_access_token(self) -> str:
        # if settings.ENV == "local":
        #     # token = self.__get_access_token_google_auth()
        #     token = self.__get_access_token_subprocess()
        # else:
        #     # token = self.__get_access_token_google_auth()
        #     token = self.__get_access_token_from_secret_manager()
        
        token = self.__get_access_token_google_auth()
        return token

    def __get_access_token_google_auth(self) -> str:
        creds, _ = google.auth.default(scopes=self.google_auth_scopes)
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        token = creds.token
        return token

    def __get_access_token_subprocess(self) -> str:
        access_token = (
            subprocess.check_output("gcloud auth print-access-token", shell=True)
            .decode("utf-8")
            .strip()
        )
        return access_token

    def __get_tools(self, tools):
        gemini_tools = []
        for tool in tools:
            if tool == GeminiToolList.GOOGLE_SEARCH:
                gemini_tools.append(self.google_search_tool)
        return gemini_tools
    
    def _get_model_id(self, model_type: GeminiModelType) -> str:
        """Map GeminiModelType enum to actual model ID from settings."""
        model_mapping = {
            GeminiModelType.PRO: settings.GEMINI_MODEL_PRO,
            GeminiModelType.FLASH: settings.GEMINI_MODEL_FLASH,
            GeminiModelType.IMAGE: settings.GEMINI_MODEL_IMAGE,
        }
        return model_mapping.get(model_type, settings.GEMINI_MODEL_PRO)

    def __get_generation_config(self, creativity, tools, response_modalities=['TEXT'], image_config_dict=None):
        if creativity == GeminiCreativityLevel.HIGH:
            temperature = 1.5
            top_p = 1
        elif creativity == GeminiCreativityLevel.MEDIUM:
            temperature = 1
            top_p = 0.95
        elif creativity == GeminiCreativityLevel.LOW:
            temperature = 0.1
            top_p = 0.5
        
        # Build config_params with only non-None values
        config_params = {
            "temperature": temperature,
            "top_p": top_p,
            "safety_settings": self.safety_settings,
            "tools": self.__get_tools(tools),
            "response_modalities": response_modalities,
        }
        
        # Only add image_config if provided
        if image_config_dict is not None:
            image_config = types.ImageConfig(
                aspect_ratio=image_config_dict['aspect_ratio'],
                image_size=image_config_dict['image_size'],
                output_mime_type="image/png"
            )
            config_params["image_config"] = image_config
        
        # Only add response_mime_type for TEXT responses
        if 'IMAGE' not in response_modalities:
            config_params["response_mime_type"] = "application/json"

        generation_config = types.GenerateContentConfig(**config_params)
        return generation_config

    def invoke_gemini(
        self,
        prompt,
        model_type=GeminiModelType.PRO,
        creativity=GeminiCreativityLevel.MEDIUM,
        tools=[],
        multimodal_input=None,
        response_modalities=['TEXT'],
        image_config_dict=None,
        max_retries=3,
    ):
        """
        Invoke Gemini API with automatic retry logic for transient failures.
        
        Args:
            prompt: The text prompt for the model
            model_type: The Gemini model to use
            creativity: Creativity level (affects temperature)
            tools: List of tools to enable
            multimodal_input: List of multimodal inputs (images, videos, etc.)
                Each item can be a dict with:
                - uri: The file URI (required)
                - mime_type: The MIME type (required)
                - fps: Optional FPS for video inputs (e.g., 5 for sampling at 5 fps)
            response_modalities: Expected response type ['TEXT'] or ['IMAGE']
            image_config_dict: Configuration for image generation
            max_retries: Maximum number of retry attempts (default: 3)
        
        Returns:
            Structured output (dict for TEXT, image for IMAGE) or False on failure
        """
        # Prepare input once (doesn't need to be recreated for retries)
        input_value = []
        if multimodal_input is not None:
            for m in multimodal_input:
                part = self._create_multimodal_part(
                    file_uri=m["uri"],
                    mime_type=m["mime_type"],
                    fps=m.get("fps")
                )
                input_value.append(part)
        
        input_value.append(types.Part.from_text(text=prompt))
                
        contents = [
            types.Content(
            role="user",
            parts=input_value
            )
        ]
        generation_config = self.__get_generation_config(creativity, tools, response_modalities, image_config_dict)
        
        # Resolve model type to actual model ID from settings
        model_id = self._get_model_id(model_type)
        
        for attempt in range(max_retries):
            try:
                log.info(f"[Gemini] Attempt {attempt + 1}/{max_retries} - Model: {model_id}")
                
                response = self.gemini_client.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=generation_config,
                )

                structured_output = None
                if 'IMAGE' in response_modalities:
                    for part in response.parts:
                        if part.inline_data is not None:
                            structured_output = part.as_image()
                            break
                    if structured_output is None:
                        log.error(f"[Gemini] No image found in response parts: {response}")
                        if attempt < max_retries - 1:
                            log.info(f"[Gemini] Retrying...")
                            time.sleep(1)  # Brief delay before retry
                            continue
                        return False
                else:
                    # Parse JSON response
                    try:
                        structured_output = json.loads(response.text)
                    except json.JSONDecodeError as json_err:
                        log.error(f"[Gemini] JSON parsing failed (attempt {attempt + 1}): {json_err}")
                        log.error(f"[Gemini] Raw response text: {response.text[:500]}...")
                        if attempt < max_retries - 1:
                            log.info(f"[Gemini] Retrying due to JSON parse error...")
                            time.sleep(1)
                            continue
                        return False
                    
                    # Handle case where Gemini returns a list instead of dict
                    if isinstance(structured_output, list):
                        if len(structured_output) > 0:
                            log.warning(f"[Gemini] Response was a list, extracting first element")
                            structured_output = structured_output[0]
                        else:
                            log.error(f"[Gemini] Response was an empty list")
                            if attempt < max_retries - 1:
                                log.info(f"[Gemini] Retrying due to empty list response...")
                                time.sleep(1)
                                continue
                            return False
                    
                    # Validate that output is a dictionary
                    if not isinstance(structured_output, dict):
                        log.error(f"[Gemini] Unexpected response type: {type(structured_output)}")
                        if attempt < max_retries - 1:
                            log.info(f"[Gemini] Retrying due to unexpected response type...")
                            time.sleep(1)
                            continue
                        return False
                
                log.info(f"[Gemini] Request successful on attempt {attempt + 1}")
                return structured_output
                
            except Exception as e:
                log.error(f"[Gemini] Error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    log.info(f"[Gemini] Retrying after error...")
                    time.sleep(1)  # Brief delay before retry
                    continue
                log.error(f"[Gemini] All {max_retries} attempts failed")
                return False
        
        log.error(f"[Gemini] Failed after {max_retries} attempts")
        return False
        
    # Jingyi's update
    # Function to upscale an image using imagen
    def invoke_imagen_upscale(
        self,
        image_path: str,
        save_dir: str,
        upscale_factor: str = "x2"
    ):
        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
        request_data = {
            "instances": [{"prompt": "","image": {"bytesBase64Encoded": image_base64},}],
            "parameters": {
                "sampleCount": 1,
                "mode": "upscale",
                "upscaleConfig": {"upscaleFactor": upscale_factor}
            }
        }
        access_token = self.__get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.imagen_cust_endpoint_url}/v1/projects/{self.imagen_cust_project_id}/locations/{settings.VERTEX_AI_LOCATION}/publishers/google/models/{self.imagen_upscale_model_id}:predict"
        try:
            response = requests.post(url, headers=headers, json=request_data)
            response.raise_for_status()  # Raise an exception for HTTP errors
            output = response.json()

            if "predictions" in output:
                log.info("Imagen response is received ...")
                # output_dir = f"{save_dir}/{CommonUtils.get_unique_identifier()}"
                output_dir = save_dir
                CommonUtils.mkdirs(output_dir)
                pred_result = output["predictions"][0]
                image_data = pred_result["bytesBase64Encoded"]
                decoded_image = base64.b64decode(image_data)
                filename = os.path.basename(image_path)
                output_path = os.path.join(output_dir, f"upscale_{upscale_factor}_{filename}")
                with open(output_path, "wb") as f:
                    f.write(decoded_image)
                log.info(f"Saved image to {output_path}")
                return output_path
            else:
                log.error("****** ERROR ******")
                log.error(f"API response missing 'predictions' field: {output}")
                # Check for error information in the response
                if "error" in output:
                    log.error(f"API error details: {output['error']}")
                return False
        except requests.exceptions.HTTPError as http_err:
            log.error(f"HTTP error occurred: {http_err}")
            log.error(f"Response content: {response.text}")
            return False
        except requests.exceptions.RequestException as req_err:
            log.error(f"Request error occurred: {req_err}")
            return False
        except Exception as e:
            log.error(f"Unexpected error in invoke_imagen_upscale: {e}")
            return False
    
    # Jingyi's update
    # Function to generate veo including first frame last frame
    def invoke_veo_generation_sync(
        self,
        prompt: str,
        image_uri: str,
        gcs_uri: str,
        seed: int = None,
        sample_count: int = 2,
        sleep_time: int = 15,
        last_frame_uri: str = None,
        aspect_ratio: str = "16:9",
        resolution: str = "1080p"
    ):
        """
        Synchronously generate video with Veo and wait for completion.
        
        Returns:
            list: List of video URIs on success
            dict: {"status": "CONTENT_POLICY_VIOLATION", "error": "..."} on content policy violation
            dict: {"status": "ERROR", "error": "..."} on other errors
            False: On unexpected failures
        """
        if last_frame_uri:
            op = self.invoke_veo_generation_advanced_control(
                prompt=prompt,
                image_uri=image_uri,
                gcs_uri=gcs_uri,
                seed=seed,
                sample_count=sample_count,
                last_frame_uri=last_frame_uri,
                # duration and enhance_prompt will take their defaults from invoke_veo_generation_advanced_control
                aspect_ratio=aspect_ratio,  # Correctly pass the aspect_ratio,
                resolution=resolution
            )
        else:
            op = self.invoke_veo_generation(
                prompt=prompt,
                image_uri=image_uri,
                gcs_uri=gcs_uri,
                seed=seed,
                sample_count=sample_count,
                aspect_ratio=aspect_ratio,# Correctly pass the aspect_ratio
                resolution=resolution
            )
        if not op:
            return {"status": "ERROR", "error": "Failed to submit Veo generation job"}
        op_name = op["operation_name"]

        wait_counter = 0
        time.sleep(sleep_time)

        while True:
            if wait_counter > 60:
                log.error(
                    f"It takes too long time. (exceeds 1hr) check the result manually: {op_name}"
                )
                return {"status": "ERROR", "error": "Timeout waiting for Veo generation"}

            check_result = self.check_veo_generation_status(op_name)
            
            # Handle different status types
            if check_result["status"] == "IN_PROGRESS":
                log.info(f"[Veo] still processing ... (wait counter: {wait_counter})")
            elif check_result["status"] == "SUCCESS":
                video_uris = check_result["video_uris"]
                log.info(f"[Veo] Success to generate videos: {video_uris}")
                return video_uris
            elif check_result["status"] == "CONTENT_POLICY_VIOLATION":
                log.error(f"[Veo] Content policy violation: {check_result.get('error', 'Unknown')}")
                return check_result  # Propagate to allow caller to retry with new prompt
            elif check_result["status"] == "ERROR":
                log.error(f"[Veo] Generation error: {check_result.get('error', 'Unknown')}")
                return check_result
            else:
                log.error(f"[Veo] Unknown status: {check_result}")
                return {"status": "ERROR", "error": f"Unknown status: {check_result}"}

            wait_counter += 1
            time.sleep(sleep_time)

        return {"status": "ERROR", "error": "Unexpected exit from generation loop"}
    
    def invoke_veo_generation_advanced_control(
        self,
        prompt: str,
        image_uri: str,
        gcs_uri: str,
        seed: int = None,
        sample_count: int = 2,
        last_frame_uri: str = "",
        duration: int = 8,
        enhance_prompt: bool = False,
        aspect_ratio: str = "16:9",
    ):
        try:
            if not seed or seed == -1:
                seed = random.randint(0, 999999)

            instance = {"prompt": prompt}
            if "gs://" in image_uri:
                instance["image"] = {"gcsUri": image_uri, "mimeType": "png"}
            if "gs://" in last_frame_uri:
                instance["lastFrame"] = {"gcsUri": last_frame_uri, "mimeType": "image/jpg"}

            request_data = {
                "instances": [instance],
                "parameters": {
                    "aspectRatio": aspect_ratio,
                    "storageUri": gcs_uri,
                    "durationSeconds": duration,
                    "enhancePrompt": enhance_prompt,
                    "sampleCount": sample_count,
                    "seed": seed,
                },
            }

            access_token = self.__get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.post(
                self.veo_exp_model_url, headers=headers, json=request_data
            )
            output = response.json()
            log.info(f"[Veo] Job submitted: {output}")
            if "name" in output:
                operation_name = output["name"]
                operation_id = operation_name.split("operations/")[1]
                return {
                    "operation_id": operation_id,
                    "operation_name": operation_name,
                    "prompt": prompt,
                    "seed": seed,
                    "image_uri": image_uri,
                }
            else:
                log.error(output)
                return False
        except Exception as e:
            log.error(e)
            return False
            

    def invoke_veo_generation(
        self,
        prompt: str,
        image_uri: str,
        gcs_uri: str,
        seed: int = None,
        sample_count: int = 2,
        aspect_ratio: str = "16:9",
        resolution: str = "1080p"
    ):
        try:
            if not seed or seed == -1:
                seed = random.randint(0, 999999)

            instance = {"prompt": prompt}
            if "gs://" in image_uri:
                instance["image"] = {"gcsUri": image_uri, "mimeType": "png"}

            request_data = {
                "instances": [instance],
                "parameters": {
                    "storageUri": gcs_uri,
                    "sampleCount": sample_count,
                    "seed": seed,
                    "aspectRatio": aspect_ratio,
                    "resolution": resolution,
                    "addWatermark": False,
                    "personGeneration": "allow_adult",
                    "enablePromptRewriting": True,
                },
            }

            access_token = self.__get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.post(
                self.veo_model_url, headers=headers, json=request_data
            )
            output = response.json()
            log.info(f"[Veo] Job submitted: {output}")
            if "name" in output:
                operation_name = output["name"]
                operation_id = operation_name.split("operations/")[1]
                return {
                    "operation_id": operation_id,
                    "operation_name": operation_name,
                    "prompt": prompt,
                    "seed": seed,
                    "image_uri": image_uri,
                }
            else:
                log.error(output)
                return False
        except Exception as e:
            log.error(e)
            return False

    def check_veo_generation_status(self, operation_name: str, veo_status_url: str = None):
        if not veo_status_url:
            veo_status_url = self.veo_status_url
        try:
            request_data = {"operationName": operation_name}
            access_token = self.__get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = requests.post(
                veo_status_url, headers=headers, json=request_data
            )
            output = response.json()
            log.info(f"[veo] job status response: {output}")

            if "done" in output and output["done"]:
                # Check for error response first (e.g., content policy violations)
                if "error" in output:
                    error_msg = output["error"].get("message", "Unknown error")
                    error_code = output["error"].get("code", 0)
                    log.error(f"[Veo] Generation failed with error code {error_code}: {error_msg}")
                    
                    # Return specific status for content policy violations
                    if "usage guidelines" in error_msg.lower() or "violate" in error_msg.lower():
                        return {"status": "CONTENT_POLICY_VIOLATION", "error": error_msg}
                    
                    # Return specific status for high load / transient errors (error code 8)
                    if error_code == 8 or "high load" in error_msg.lower():
                        return {"status": "HIGH_LOAD", "error": error_msg}
                    
                    return {"status": "ERROR", "error": error_msg}
                
                video_uris = []

                # GA version
                for o in output["response"]["videos"]:
                    video_uris.append(o["gcsUri"])

                # Experiment version
                # for o in output["response"]["generatedSamples"]:
                #     video_uris.append(o["video"]["uri"])
                
                return {"video_uris": video_uris, "status": "SUCCESS"}
            elif output["name"] == operation_name:
                return {"status": "IN_PROGRESS"}
            else:
                log.error(f"Unknown status: {output}")
                return {"status": "ERROR", "error": f"Unknown status: {output}"}
        except Exception as e:
            log.error(f"[Veo] Exception in check_veo_generation_status: {e}")
            return {"status": "ERROR", "error": str(e)}

    def invoke_lyria(self, prompt: str, save_dir: str):
        instance = {"prompt": prompt}
        request_data = {
            "instances": [instance],
            "parameters": {},
        }

        access_token = self.__get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        endpoint_url = "https://us-central1-aiplatform.googleapis.com/v1/projects"
        project_id = "music-generation-434117"
        model_id = "lyria-002"
        url = f"{endpoint_url}/{project_id}/locations/{settings.VERTEX_AI_LOCATION}/publishers/google/models/{model_id}:predict"

        response = requests.post(url, headers=headers, json=request_data)
        output = response.json()
        if "predictions" in output:
            log.info("Lyria response is received ...")
            output_dir = f"{save_dir}/{CommonUtils.get_unique_identifier()}"
            CommonUtils.mkdirs(output_dir)
            pred_results = output["predictions"]
            output_paths = []
            for i in range(len(pred_results)):
                image_data = pred_results[i]["bytesBase64Encoded"]
                decoded_image = base64.b64decode(image_data)
                output_path = os.path.join(output_dir, f"lyria_{i:02}.wav")
                with open(output_path, "wb") as f:
                    f.write(decoded_image)
                log.info(f"Saved music to {output_path}")
                output_paths.append(output_path)
            return output_paths
        else:
            log.error("****** ERROR ******")
            log.error(output)
            return False


vertex_ai = VertexAIService()
