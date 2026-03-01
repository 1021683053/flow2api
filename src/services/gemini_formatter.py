"""Gemini API response formatters and model mapper

This module provides:
1. GeminiModelMapper - Maps Gemini API parameters to internal Flow2API configurations
2. GeminiResponseFormatter - Formats internal responses to Gemini API format
"""

from typing import Tuple, Optional, Dict, Any, List
from fastapi import HTTPException

from ..core.gemini_mapping import (
    GEMINI_IMAGE_MODEL_MAP,
    GEMINI_IMAGE_SIZE_MAP,
    GEMINI_VIDEO_MODEL_MAP,
    GEMINI_VIDEO_RESOLUTION_MAP,
)


class GeminiModelMapper:
    """Maps Gemini API model names and parameters to internal Flow2API configuration"""

    @staticmethod
    def map_image_model(
        gemini_model: str,
        aspect_ratio: str = "16:9",
        image_size: Optional[str] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Map Gemini image model parameters to internal model configuration.

        Args:
            gemini_model: Gemini model name (e.g., "gemini-3-pro-image")
            aspect_ratio: Aspect ratio (e.g., "16:9", "1:1")
            image_size: Image size (e.g., "1K", "2K", "4K")

        Returns:
            Tuple of (internal_model_id, upsample_config)

        Raises:
            HTTPException: If model or aspect ratio is not supported
        """
        if gemini_model not in GEMINI_IMAGE_MODEL_MAP:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": 400,
                        "message": f"Unsupported Gemini image model: {gemini_model}. "
                                   f"Supported: {list(GEMINI_IMAGE_MODEL_MAP.keys())}"
                    }
                }
            )

        model_config = GEMINI_IMAGE_MODEL_MAP[gemini_model]

        # Validate aspect ratio
        if aspect_ratio not in model_config["supported_ratios"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": 400,
                        "message": f"Aspect ratio '{aspect_ratio}' not supported by {gemini_model}. "
                                   f"Supported: {model_config['supported_ratios']}"
                    }
                }
            )

        # Get internal aspect ratio constant
        internal_ratio = model_config["ratio_map"][aspect_ratio]

        # Map Gemini model name to MODEL_CONFIG key
        # gemini-3-pro-image -> gemini-3.0-pro-image
        # gemini-2.5-flash-image -> gemini-2.5-flash-image (already correct)
        # gemini-3.1-flash-image-preview -> gemini-3.1-flash-image-preview (already correct)
        model_prefix = gemini_model
        if gemini_model == "gemini-3-pro-image":
            model_prefix = "gemini-3.0-pro-image"

        # Map aspect ratio to suffix used in MODEL_CONFIG
        # 16:9 -> landscape, 9:16 -> portrait, 1:1 -> square, etc.
        ratio_suffix_map = {
            "16:9": "landscape",
            "9:16": "portrait",
            "1:1": "square",
            "4:3": "four-three",
            "3:4": "three-four",
            "1:4": "1-4",
            "4:1": "4-1",
            "1:8": "1-8",
            "8:1": "8-1",
        }
        ratio_suffix = ratio_suffix_map.get(aspect_ratio, aspect_ratio.replace(":", "-"))

        # Build internal model ID following MODEL_CONFIG naming convention
        # e.g., "gemini-3.0-pro-image-landscape", "gemini-3.0-pro-image-landscape-2k"
        internal_model_id = f"{model_prefix}-{ratio_suffix}"

        # Add size suffix if specified and not 1K
        upsample = None
        if image_size and image_size != "1K":
            if image_size not in GEMINI_IMAGE_SIZE_MAP:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "code": 400,
                            "message": f"Invalid image size: {image_size}. Supported: {list(GEMINI_IMAGE_SIZE_MAP.keys())}"
                        }
                    }
                )
            upsample = GEMINI_IMAGE_SIZE_MAP[image_size]
            if upsample:
                internal_model_id = f"{internal_model_id}-{image_size.lower()}"

        return internal_model_id, upsample

    @staticmethod
    def map_video_model(
        gemini_model: str,
        aspect_ratio: str = "16:9",
        resolution: Optional[str] = None
    ) -> Tuple[str, Optional[Dict[str, str]]]:
        """
        Map Gemini video model parameters to internal model configuration.

        Args:
            gemini_model: Gemini model name (e.g., "veo-3.1-generate-preview")
            aspect_ratio: Aspect ratio ("16:9" or "9:16")
            resolution: Resolution (e.g., "720p", "1080p", "4k")

        Returns:
            Tuple of (internal_model_key, upsample_config)

        Raises:
            HTTPException: If model or aspect ratio is not supported
        """
        if gemini_model not in GEMINI_VIDEO_MODEL_MAP:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": 400,
                        "message": f"Unsupported Gemini video model: {gemini_model}. "
                                   f"Supported: {list(GEMINI_VIDEO_MODEL_MAP.keys())}"
                    }
                }
            )

        model_config = GEMINI_VIDEO_MODEL_MAP[gemini_model]

        # Validate aspect ratio
        if aspect_ratio not in model_config["ratio_map"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": 400,
                        "message": f"Aspect ratio '{aspect_ratio}' not supported by {gemini_model}. "
                                   f"Supported: {list(model_config['ratio_map'].keys())}"
                    }
                }
            )

        # Get internal model key
        internal_model_id = model_config["ratio_map"][aspect_ratio]

        # Map resolution to upsample config
        upsample = None
        if resolution and resolution != "720p":
            if resolution not in GEMINI_VIDEO_RESOLUTION_MAP:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "code": 400,
                            "message": f"Invalid resolution: {resolution}. Supported: {list(GEMINI_VIDEO_RESOLUTION_MAP.keys())}"
                        }
                    }
                )
            upsample = GEMINI_VIDEO_RESOLUTION_MAP[resolution]
            # Append resolution suffix to model ID for MODEL_CONFIG lookup
            # e.g., veo_3_1_t2v_fast -> veo_3_1_t2v_fast_1080p
            internal_model_id = f"{internal_model_id}_{resolution.lower()}"

        return internal_model_id, upsample

    @staticmethod
    def get_model_info(gemini_model: str) -> Optional[Dict[str, Any]]:
        """Get model information for a Gemini model"""
        if gemini_model in GEMINI_IMAGE_MODEL_MAP:
            config = GEMINI_IMAGE_MODEL_MAP[gemini_model]
            return {
                "type": "image",
                "model_name": config["model_name"],
                "supported_ratios": config["supported_ratios"]
            }
        elif gemini_model in GEMINI_VIDEO_MODEL_MAP:
            config = GEMINI_VIDEO_MODEL_MAP[gemini_model]
            return {
                "type": "video",
                "video_type": config["video_type"],
                "supported_ratios": list(config["ratio_map"].keys())
            }
        return None


class GeminiResponseFormatter:
    """Format GenerationHandler responses to Gemini API format"""

    @staticmethod
    def format_image_response(base64_data: str, mime_type: str = "image/jpeg") -> Dict[str, Any]:
        """
        Format image generation response to Gemini API format.

        Returns:
            Dict matching Gemini generateContent response format
        """
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": base64_data
                                }
                            }
                        ]
                    },
                    "finishReason": "STOP",
                    "index": 0
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 0,
                "candidatesTokenCount": 0,
                "totalTokenCount": 0
            }
        }

    @staticmethod
    def format_video_operation(operation_name: str) -> Dict[str, Any]:
        """
        Format video generation operation response.

        Returns:
            Dict matching Gemini long-running operation format
        """
        return {
            "name": operation_name,
            "done": False,
            "metadata": {
                "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictOperationMetadata",
                "genericMetadata": {
                    "createTime": "",
                    "updateTime": ""
                }
            }
        }

    @staticmethod
    def format_video_result(video_url: str) -> Dict[str, Any]:
        """
        Format completed video operation result.

        Returns:
            Dict with completed operation containing video URI
        """
        return {
            "name": "",
            "done": True,
            "response": {
                "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictResponse",
                "predictions": [
                    {
                        "mimeType": "video/mp4",
                        "uri": video_url
                    }
                ]
            }
        }

    @staticmethod
    def format_operation_result(
        operation_name: str,
        done: bool,
        result_urls: Optional[List[str]] = None,
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format operation status response.

        Args:
            operation_name: The operation identifier
            done: Whether the operation is complete
            result_urls: List of result URLs (for completed operations)
            error_message: Error message (for failed operations)

        Returns:
            Dict matching Gemini operation format
        """
        response: Dict[str, Any] = {
            "name": operation_name,
            "done": done
        }

        if error_message:
            response["error"] = {
                "code": 500,
                "message": error_message,
                "status": "INTERNAL"
            }
        elif done and result_urls:
            response["response"] = {
                "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictResponse",
                "predictions": [
                    {
                        "mimeType": "video/mp4",
                        "uri": url
                    } for url in result_urls
                ]
            }
        else:
            # Still processing
            response["metadata"] = {
                "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictOperationMetadata",
                "genericMetadata": {
                    "createTime": "",
                    "updateTime": ""
                }
            }

        return response

    @staticmethod
    def format_model_info(
        model_name: str,
        display_name: str,
        description: str,
        generation_methods: List[str]
    ) -> Dict[str, Any]:
        """
        Format model information for list/get model endpoints.

        Returns:
            Dict matching Gemini model info format
        """
        return {
            "name": f"models/{model_name}",
            "version": "1.0",
            "displayName": display_name,
            "description": description,
            "inputTokenLimit": 8192,
            "outputTokenLimit": 2048,
            "supportedGenerationMethods": generation_methods
        }

    @staticmethod
    def format_error_response(message: str, code: int = 400) -> Dict[str, Any]:
        """Format error response in Gemini API format"""
        return {
            "error": {
                "code": code,
                "message": message,
                "status": "INVALID_ARGUMENT" if code == 400 else "INTERNAL"
            }
        }
