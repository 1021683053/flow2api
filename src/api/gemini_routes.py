"""Gemini API compatible routes

This module provides Google Gemini API compatible endpoints for image and video generation.
All endpoints are prefixed with /v1beta in main.py.

Endpoints:
- POST /models/{model}:generateContent - Image generation
- POST /models/{model}:predictLongRunning - Video generation
- GET /operations/{operation_id} - Get operation status
- GET /models - List available models
- GET /models/{model} - Get model information
"""

import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.auth import verify_api_key_header
from ..core.gemini_mapping import GEMINI_IMAGE_MODEL_MAP, GEMINI_VIDEO_MODEL_MAP
from ..core.logger import debug_logger
from ..services.generation_handler import GenerationHandler
from ..services.gemini_formatter import GeminiModelMapper, GeminiResponseFormatter

router = APIRouter()

# Dependencies (set in main.py)
generation_handler: Optional[GenerationHandler] = None
gemini_mapper = GeminiModelMapper()
response_formatter = GeminiResponseFormatter()


def set_generation_handler(handler: GenerationHandler):
    """Set generation handler instance"""
    global generation_handler
    generation_handler = handler


# ========== Pydantic Models ==========

class GeminiContentPart(BaseModel):
    """Single part of content (text or inline data)"""
    text: Optional[str] = None
    inlineData: Optional[Dict[str, Any]] = None  # {"mimeType": "...", "data": "base64..."}


class GeminiContent(BaseModel):
    """Content in Gemini format"""
    role: Optional[str] = "user"
    parts: List[GeminiContentPart]


class GeminiImageConfig(BaseModel):
    """Image generation configuration (nested in generationConfig)"""
    aspectRatio: Optional[str] = "1:1"  # 官方默认 1:1
    imageSize: Optional[str] = None  # "512px", "1K", "2K", "4K"


class GeminiGenerationConfig(BaseModel):
    """Generation configuration for image generation (官方格式)"""
    # 官方支持的字段（部分在本项目中不支持，但会验证）
    temperature: Optional[float] = None
    topP: Optional[float] = None
    topK: Optional[int] = None
    candidateCount: Optional[int] = None
    maxOutputTokens: Optional[int] = None
    stopSequences: Optional[List[str]] = None
    responseMimeType: Optional[str] = None
    responseModalities: Optional[List[str]] = None
    # 图像生成特有的配置（嵌套在 generationConfig 中）
    imageConfig: Optional[GeminiImageConfig] = None


class GeminiSafetySetting(BaseModel):
    """Safety setting for content generation"""
    category: str
    threshold: str


class GeminiGenerateContentRequest(BaseModel):
    """Gemini generateContent request body (官方格式)"""
    contents: List[GeminiContent]
    generationConfig: Optional[GeminiGenerationConfig] = None
    safetySettings: Optional[List[GeminiSafetySetting]] = None


class GeminiVideoImageInput(BaseModel):
    """Image input for video generation (i2v)"""
    bytesBase64Encoded: Optional[str] = None
    mimeType: Optional[str] = None


class GeminiPredictInstance(BaseModel):
    """Single prediction instance for video generation (官方格式)"""
    prompt: Optional[str] = None  # 对于 i2v 可能为空
    image: Optional[GeminiVideoImageInput] = None  # 可选，用于 i2v


class GeminiPredictParameters(BaseModel):
    """Parameters for video generation (官方格式)"""
    aspectRatio: Optional[str] = "16:9"  # "16:9", "9:16"
    resolution: Optional[str] = "720p"  # "720p", "1080p", "4k"
    duration: Optional[str] = "8s"  # "4s", "8s"
    negativePrompt: Optional[str] = None
    numberOfVideos: Optional[int] = 1
    personGeneration: Optional[str] = None  # "allow_adult", "dont_allow"


class GeminiPredictLongRunningRequest(BaseModel):
    """Gemini predictLongRunning request body (官方格式)"""
    instances: List[GeminiPredictInstance]
    parameters: Optional[GeminiPredictParameters] = None


# ========== Helper Functions ==========

def extract_prompt_from_contents(contents: List[GeminiContent]) -> str:
    """Extract text prompt from Gemini contents"""
    if not contents:
        raise HTTPException(
            status_code=400,
            detail=response_formatter.format_error_response("contents cannot be empty", 400)
        )

    # Get last content (typically user message)
    last_content = contents[-1]

    # Extract text from parts
    prompt_parts = []
    for part in last_content.parts:
        if part.text:
            prompt_parts.append(part.text)

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail=response_formatter.format_error_response("prompt cannot be empty", 400)
        )

    return prompt


def extract_reference_images_from_contents(contents: List[GeminiContent]) -> Optional[List[bytes]]:
    """Extract reference images from Gemini contents (if any)"""
    images = []

    for content in contents:
        for part in content.parts:
            if part.inlineData and part.inlineData.get("data"):
                try:
                    image_bytes = base64.b64decode(part.inlineData["data"])
                    images.append(image_bytes)
                except Exception as e:
                    debug_logger.log_warning(f"[Gemini] Failed to decode inline image: {str(e)}")

    return images if images else None


async def get_base64_from_image_url(image_url: str) -> str:
    """
    Download image from URL and return base64 encoded data.
    Handles both local cached files and remote URLs.
    """
    # Check if it's a local cached file
    if "/tmp/" in image_url and generation_handler and generation_handler.file_cache:
        try:
            path = urlparse(image_url).path
            filename = path.split("/tmp/")[-1]
            local_path = generation_handler.file_cache.cache_dir / filename

            if local_path.exists():
                with open(local_path, "rb") as f:
                    image_bytes = f.read()
                    return base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            debug_logger.log_warning(f"[Gemini] Failed to read local cache: {str(e)}")

    # Download from remote URL
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession() as session:
            response = await session.get(image_url, timeout=30, impersonate="chrome120", verify=False)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode("utf-8")
            else:
                raise Exception(f"HTTP {response.status_code}")
    except Exception as e:
        debug_logger.log_error(f"[Gemini] Failed to download image: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=response_formatter.format_error_response(
                f"Failed to get image data: {str(e)}", 500
            )
        )


def is_image_model(model: str) -> bool:
    """Check if model is an image generation model"""
    return model in GEMINI_IMAGE_MODEL_MAP


def is_video_model(model: str) -> bool:
    """Check if model is a video generation model"""
    return model in GEMINI_VIDEO_MODEL_MAP


# ========== Image Generation Endpoint ==========

# 官方文档中 image 支持的 aspect ratio
GEMINI_SUPPORTED_IMAGE_ASPECT_RATIOS = [
    "1:1", "16:9", "9:16", "4:3", "3:4",
    "21:9", "2:3", "3:2", "4:5", "5:4",
    "1:4", "4:1", "1:8", "8:1"
]

# 官方文档中 image 支持的 size
GEMINI_SUPPORTED_IMAGE_SIZES = ["512px", "1K", "2K", "4K"]

# 官方视频支持的 aspect ratio
GEMINI_SUPPORTED_VIDEO_ASPECT_RATIOS = ["16:9", "9:16"]

# 官方视频支持的 resolution
GEMINI_SUPPORTED_VIDEO_RESOLUTIONS = ["720p", "1080p", "4k"]


@router.post("/models/{model}:generateContent")
async def gemini_generate_content(
    model: str = Path(..., description="Gemini model name"),
    request: GeminiGenerateContentRequest = None,
    api_key: str = Depends(verify_api_key_header)
):
    """
    Gemini API compatible image generation endpoint.

    Supported models (official names):
    - gemini-2.5-flash-image (aspect ratios: 16:9, 9:16)
    - gemini-3-pro-image-preview (aspect ratios: 16:9, 9:16, 1:1, 4:3, 3:4)
    - gemini-3.1-flash-image-preview (aspect ratios: 16:9, 9:16, 1:1, 4:3, 3:4, 1:4, 4:1, 1:8, 8:1)

    Official API request format:
    {
        "contents": [{"parts": [{"text": "prompt"}]}],
        "generationConfig": {
            "imageConfig": {
                "aspectRatio": "1:1",  // default
                "imageSize": "1K"      // optional: 512px, 1K, 2K, 4K
            }
        }
    }

    Note: Other generationConfig parameters (temperature, topP, topK, etc.) are NOT supported.
    """
    try:
        # Validate this is an image model
        if not is_image_model(model):
            if is_video_model(model):
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Model {model} is a video model. Use :predictLongRunning endpoint for video generation.",
                        400
                    )
                )
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Unknown model: {model}. Supported image models: {list(GEMINI_IMAGE_MODEL_MAP.keys())}",
                    400
                )
            )

        # Validate unsupported parameters in generationConfig
        if request.generationConfig:
            unsupported_params = []
            if request.generationConfig.temperature is not None:
                unsupported_params.append("temperature")
            if request.generationConfig.topP is not None:
                unsupported_params.append("topP")
            if request.generationConfig.topK is not None:
                unsupported_params.append("topK")
            if request.generationConfig.candidateCount is not None:
                unsupported_params.append("candidateCount")
            if request.generationConfig.maxOutputTokens is not None:
                unsupported_params.append("maxOutputTokens")
            if request.generationConfig.stopSequences is not None:
                unsupported_params.append("stopSequences")
            if request.generationConfig.responseMimeType is not None:
                unsupported_params.append("responseMimeType")
            if request.generationConfig.responseModalities is not None:
                # responseModalities 包含 IMAGE 是可以的，其他值不支持
                modalities = request.generationConfig.responseModalities
                if modalities and not all(m in ["TEXT", "IMAGE"] for m in modalities):
                    unsupported_params.append("responseModalities (only TEXT and IMAGE are supported)")

            if unsupported_params:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Unsupported generationConfig parameters: {', '.join(unsupported_params)}. "
                        f"This API only supports imageConfig for image generation.",
                        400
                    )
                )

        # Validate unsupported safetySettings
        if request.safetySettings:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    "safetySettings is not supported by this API.",
                    400
                )
            )

        # Extract prompt from contents
        prompt = extract_prompt_from_contents(request.contents)

        # Extract reference images (if any)
        images = extract_reference_images_from_contents(request.contents)

        # Extract generation config (官方格式：嵌套在 imageConfig 中)
        aspect_ratio = "1:1"  # 官方默认 1:1
        image_size = None
        if request.generationConfig and request.generationConfig.imageConfig:
            config = request.generationConfig.imageConfig
            aspect_ratio = config.aspectRatio or "1:1"
            image_size = config.imageSize

            # Validate aspect ratio
            if aspect_ratio not in GEMINI_SUPPORTED_IMAGE_ASPECT_RATIOS:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Invalid aspectRatio: {aspect_ratio}. "
                        f"Supported values: {GEMINI_SUPPORTED_IMAGE_ASPECT_RATIOS}",
                        400
                    )
                )

            # Validate image size
            if image_size and image_size not in GEMINI_SUPPORTED_IMAGE_SIZES:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Invalid imageSize: {image_size}. "
                        f"Supported values: {GEMINI_SUPPORTED_IMAGE_SIZES}",
                        400
                    )
                )

        # Map to internal model
        internal_model_id, upsample = gemini_mapper.map_image_model(
            gemini_model=model,
            aspect_ratio=aspect_ratio,
            image_size=image_size
        )

        debug_logger.log_info(
            f"[Gemini] Image generation: model={model}, internal={internal_model_id}, "
            f"prompt={prompt[:50]}..., aspect_ratio={aspect_ratio}, size={image_size}"
        )

        # Call generation handler with stream=True to get actual generation result
        # Then collect all chunks and extract the final result
        result_chunks = []
        async for chunk in generation_handler.handle_generation(
            model=internal_model_id,
            prompt=prompt,
            images=images,
            stream=True
        ):
            result_chunks.append(chunk)

        if not result_chunks:
            raise HTTPException(
                status_code=500,
                detail=response_formatter.format_error_response("Generation failed: No response", 500)
            )

        # Parse result - GenerationHandler returns JSON string in OpenAI format
        final_result = result_chunks[-1]

        # DEBUG: Log chunk count
        debug_logger.log_info(f"[Gemini] Total chunks received: {len(result_chunks)}")

        try:
            # Parse streaming chunks - each chunk is in SSE format: data: {...}\n\n
            # Collect all content from chunks
            full_content = ""
            for chunk in result_chunks:
                chunk_str = chunk.strip()
                if chunk_str.startswith("data: "):
                    chunk_str = chunk_str[6:]  # Remove 'data: ' prefix
                try:
                    chunk_data = json.loads(chunk_str)
                    # Stream chunk uses 'delta', final response uses 'message'
                    delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        full_content += delta["content"]
                    if delta.get("reasoning_content"):
                        full_content += delta["reasoning_content"]
                except (json.JSONDecodeError, IndexError):
                    continue

            # Also check the last chunk for 'message' format (non-streaming style)
            try:
                last_data = json.loads(final_result.strip()[6:] if final_result.strip().startswith("data: ") else final_result)
                message_content = last_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if message_content:
                    full_content = message_content
            except:
                pass

            # Check for error in response (handle both SSE format and plain JSON)
            if not full_content:
                # Collect all error messages from chunks
                error_messages = []
                for chunk in result_chunks:
                    chunk_str = chunk.strip()
                    # Try to parse as SSE format first (data: {...})
                    if chunk_str.startswith("data: "):
                        chunk_str = chunk_str[6:]
                    try:
                        chunk_data = json.loads(chunk_str)
                        if "error" in chunk_data:
                            error_msg = chunk_data["error"].get("message", "Unknown error")
                            error_messages.append(error_msg)
                    except (json.JSONDecodeError, TypeError):
                        # Include non-JSON chunks that might contain error text
                        if chunk_str and len(chunk_str) < 500:
                            error_messages.append(chunk_str[:200])
                        continue

                if error_messages:
                    combined_error = "; ".join(error_messages[:3])  # Limit to first 3 errors
                    raise HTTPException(
                        status_code=500,
                        detail=response_formatter.format_error_response(f"Generation failed: {combined_error}", 500)
                    )

                raise HTTPException(
                    status_code=500,
                    detail=response_formatter.format_error_response(
                        f"Empty response from generation handler. Chunks received: {len(result_chunks)}", 500
                    )
                )

            # Extract image URL from markdown format ![...](url)
            url_match = re.search(r'!\[.*?\]\((.*?)\)', full_content)
            if not url_match:
                # Check if response contains error indicators
                error_indicators = ["error", "失败", "错误", "captcha", "验证码", "reCAPTCHA", "403", "401", "429"]
                content_lower = full_content.lower()
                for indicator in error_indicators:
                    if indicator.lower() in content_lower:
                        raise HTTPException(
                            status_code=500,
                            detail=response_formatter.format_error_response(
                                f"Image generation failed: {full_content[:500]}", 500
                            )
                        )
                # Return full content for debugging if no image found
                raise HTTPException(
                    status_code=500,
                    detail=response_formatter.format_error_response(
                        f"No image URL found in response. Raw content: {full_content[:500]}", 500
                    )
                )

            image_url = url_match.group(1)

            # Convert to base64
            base64_data = await get_base64_from_image_url(image_url)

            # Return Gemini format response
            response_data = response_formatter.format_image_response(base64_data)
            return JSONResponse(content=response_data)

        except json.JSONDecodeError as e:
            debug_logger.log_error(f"[Gemini] Invalid JSON response: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=response_formatter.format_error_response("Invalid response format from generation handler", 500)
            )

    except HTTPException:
        raise
    except Exception as e:
        debug_logger.log_error(f"[Gemini] Image generation error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=response_formatter.format_error_response(str(e), 500)
        )


# ========== Video Generation Endpoints ==========

@router.post("/models/{model}:predictLongRunning")
async def gemini_predict_long_running(
    model: str = Path(..., description="Gemini video model name"),
    request: GeminiPredictLongRunningRequest = None,
    wait: bool = Query(False, description="Wait for generation to complete (synchronous mode)"),
    timeout: int = Query(300, description="Timeout in seconds for wait mode (max 600)"),
    api_key: str = Depends(verify_api_key_header)
):
    """
    Gemini API compatible video generation endpoint.

    Supported models (official names):
    - veo-3.1-generate-preview (aspect ratios: 16:9, 9:16; resolutions: 720p, 1080p, 4k)
    - veo-3.1-fast-preview (aspect ratios: 16:9, 9:16; resolutions: 720p, 1080p, 4k)
    - veo-3 (aspect ratios: 16:9, 9:16; resolutions: 720p, 1080p, 4k)
    - veo-2 (aspect ratios: 16:9, 9:16; resolutions: 720p, 1080p, 4k)

    Returns an operation that must be polled via GET /operations/{operation_id}

    Official API parameters (in request.parameters):
    - aspectRatio: "16:9" or "9:16" (default: "16:9")
    - resolution: "720p", "1080p", or "4k" (default: "720p")
    - duration: "4s" or "8s" (default: "8s") - NOT SUPPORTED, will throw error
    - negativePrompt: string - NOT SUPPORTED, will throw error
    - numberOfVideos: integer (default: 1) - NOT SUPPORTED, will throw error
    - personGeneration: "allow_adult" or "dont_allow" - NOT SUPPORTED, will throw error

    Note: Image-to-video (i2v) is supported by providing image in instances[0].image.bytesBase64Encoded

    Extension (non-official):
    - wait: If true, wait for generation to complete before returning (synchronous mode)
    - timeout: Max wait time in seconds (10-600, default: 300) when wait=true

    Example with wait:
        POST /v1beta/models/veo-3:predictLongRunning?wait=true&timeout=300
    """
    try:
        # Validate this is a video model
        if not is_video_model(model):
            if is_image_model(model):
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Model {model} is an image model. Use :generateContent endpoint for image generation.",
                        400
                    )
                )
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Unknown model: {model}. Supported video models: {list(GEMINI_VIDEO_MODEL_MAP.keys())}",
                    400
                )
            )

        if not request.instances:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response("instances cannot be empty", 400)
            )

        # Get first instance (Gemini video API typically uses single instance)
        instance = request.instances[0]

        # Extract prompt from instance
        prompt = instance.prompt or ""

        # Extract image for i2v (image-to-video) if provided
        image_bytes = None
        if instance.image and instance.image.bytesBase64Encoded:
            try:
                image_bytes = base64.b64decode(instance.image.bytesBase64Encoded)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Invalid base64 image data: {str(e)}", 400
                    )
                )

        # Validate prompt is provided for t2v (text-to-video)
        # For i2v, prompt is optional
        if not prompt and not image_bytes:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    "Either prompt or image must be provided", 400
                )
            )

        # Extract parameters from parameters field (official API format)
        aspect_ratio = "16:9"
        resolution = "720p"

        if request.parameters:
            aspect_ratio = request.parameters.aspectRatio or "16:9"
            resolution = request.parameters.resolution or "720p"

            # Validate unsupported parameters
            unsupported_params = []

            if request.parameters.duration and request.parameters.duration != "8s":
                # duration is not supported - we always generate 8s videos
                unsupported_params.append(f"duration={request.parameters.duration} (only 8s is supported)")

            if request.parameters.negativePrompt:
                unsupported_params.append("negativePrompt")

            if request.parameters.numberOfVideos and request.parameters.numberOfVideos != 1:
                unsupported_params.append(f"numberOfVideos={request.parameters.numberOfVideos} (only 1 is supported)")

            if request.parameters.personGeneration:
                unsupported_params.append(f"personGeneration={request.parameters.personGeneration}")

            if unsupported_params:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Unsupported parameters: {', '.join(unsupported_params)}",
                        400
                    )
                )

        # Validate aspect ratio
        if aspect_ratio not in GEMINI_SUPPORTED_VIDEO_ASPECT_RATIOS:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Invalid aspectRatio: {aspect_ratio}. "
                    f"Supported values: {GEMINI_SUPPORTED_VIDEO_ASPECT_RATIOS}",
                    400
                )
            )

        # Validate resolution
        if resolution not in GEMINI_SUPPORTED_VIDEO_RESOLUTIONS:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Invalid resolution: {resolution}. "
                    f"Supported values: {GEMINI_SUPPORTED_VIDEO_RESOLUTIONS}",
                    400
                )
            )

        # Map to internal model
        internal_model_id, upsample = gemini_mapper.map_video_model(
            gemini_model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution
        )

        debug_logger.log_info(
            f"[Gemini] Video generation: model={model}, internal={internal_model_id}, "
            f"prompt={prompt[:50] if prompt else '(empty)'}..., "
            f"aspect_ratio={aspect_ratio}, resolution={resolution}, "
            f"has_image={image_bytes is not None}"
        )

        # Generate unique operation ID
        operation_id = f"operations/{uuid.uuid4().hex}"

        # Get a token for the operation
        token = await generation_handler.load_balancer.select_token(for_video_generation=True)
        if not token:
            raise HTTPException(
                status_code=503,
                detail=response_formatter.format_error_response(
                    "No available token for video generation", 503
                )
            )

        # Create a pending task entry
        from ..core.models import Task
        task = Task(
            task_id=operation_id,
            token_id=token.id,
            model=internal_model_id,
            prompt=prompt if prompt else "(image-to-video)",
            status="pending",
            progress=0,
            scene_id=None
        )
        await generation_handler.db.create_task(task)

        # Start video generation in background
        import asyncio
        asyncio.create_task(
            _process_video_generation(
                operation_id=operation_id,
                internal_model_id=internal_model_id,
                prompt=prompt,
                token=token,
                image_bytes=image_bytes
            )
        )

        # If wait=true, wait for completion
        if wait:
            debug_logger.log_info(f"[Gemini] Wait mode enabled, waiting for {operation_id} to complete...")

            # Validate timeout
            timeout = min(max(timeout, 10), 600)  # Clamp between 10s and 600s

            start_time = asyncio.get_event_loop().time()
            poll_interval = 2  # Poll every 2 seconds

            while True:
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    # Return operation (still processing) with timeout warning
                    response_data = response_formatter.format_video_operation(operation_id)
                    response_data["metadata"]["waitTimeout"] = True
                    debug_logger.log_warning(f"[Gemini] Wait timeout for {operation_id} after {timeout}s")
                    return JSONResponse(content=response_data)

                # Query task status
                task = await generation_handler.db.get_task(operation_id)
                if not task:
                    raise HTTPException(
                        status_code=500,
                        detail=response_formatter.format_error_response(
                            "Task disappeared during wait", 500
                        )
                    )

                if task.status == "completed":
                    # Return completed result
                    result_urls = task.result_urls or []
                    response_data = response_formatter.format_operation_result(
                        operation_name=operation_id,
                        done=True,
                        result_urls=result_urls
                    )
                    debug_logger.log_info(f"[Gemini] Wait completed for {operation_id} in {elapsed:.1f}s")
                    return JSONResponse(content=response_data)

                elif task.status == "failed":
                    # Return error
                    response_data = response_formatter.format_operation_result(
                        operation_name=operation_id,
                        done=True,
                        error_message=task.error_message or "Video generation failed"
                    )
                    debug_logger.log_error(f"[Gemini] Wait failed for {operation_id}: {task.error_message}")
                    return JSONResponse(content=response_data)

                # Still processing, wait and poll again
                await asyncio.sleep(poll_interval)

        # Return operation response immediately (官方格式)
        response_data = response_formatter.format_video_operation(operation_id)
        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        debug_logger.log_error(f"[Gemini] Video generation error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=response_formatter.format_error_response(str(e), 500)
        )


async def _process_video_generation(
    operation_id: str,
    internal_model_id: str,
    prompt: str,
    token: Any,
    image_bytes: Optional[bytes] = None
):
    """Background task to process video generation"""
    try:
        debug_logger.log_info(f"[Gemini] Starting video generation for operation {operation_id}")

        # Update task status to processing
        await generation_handler.db.update_task(
            operation_id,
            status="processing",
            progress=10
        )

        # Call generation handler with stream=True to get actual generation result
        result_url = None
        error_messages = []
        all_chunks = []

        async for chunk in generation_handler.handle_generation(
            model=internal_model_id,
            prompt=prompt,
            images=[image_bytes] if image_bytes else None,
            stream=True
        ):
            all_chunks.append(chunk)

            # Parse result to extract video URL
            chunk_str = chunk.strip()
            if chunk_str.startswith("data: "):
                chunk_str = chunk_str[6:]

            try:
                result_data = json.loads(chunk_str)
                # Check for error in chunk
                if "error" in result_data:
                    error_msg = result_data["error"].get("message", "Unknown error")
                    error_messages.append(error_msg)
                    continue

                # Try to extract video URL
                delta = result_data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if not content:
                    content = result_data.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Extract video URL from HTML format
                url_match = re.search(r"src='([^']+)'", content)
                if url_match:
                    result_url = url_match.group(1)
            except (json.JSONDecodeError, IndexError):
                # Check if raw chunk contains error indicators
                chunk_lower = chunk.lower()
                if any(err in chunk_lower for err in ["error", "失败", "错误", "captcha", "验证码", "403", "401"]):
                    error_messages.append(chunk[:200])
                continue

        # Update task with result
        if result_url:
            await generation_handler.db.update_task(
                operation_id,
                status="completed",
                progress=100,
                result_urls=[result_url],
                completed_at=time.time()
            )
            debug_logger.log_info(f"[Gemini] Video generation completed for operation {operation_id}: {result_url}")
        else:
            # Build detailed error message
            if error_messages:
                combined_error = "; ".join(error_messages[:3])
                error_detail = f"Video generation failed: {combined_error}"
            else:
                # Include raw chunks for debugging
                raw_preview = " | ".join([c[:100] for c in all_chunks[-3:]])
                error_detail = f"No video URL found. Raw response preview: {raw_preview[:500]}"

            await generation_handler.db.update_task(
                operation_id,
                status="failed",
                error_message=error_detail,
                completed_at=time.time()
            )
            debug_logger.log_error(f"[Gemini] Video generation failed for operation {operation_id}: {error_detail}")

    except Exception as e:
        debug_logger.log_error(f"[Gemini] Background video generation error: {str(e)}")
        try:
            await generation_handler.db.update_task(
                operation_id,
                status="failed",
                error_message=str(e),
                completed_at=time.time()
            )
        except:
            pass


@router.get("/operations/{operation_id:path}")
async def gemini_get_operation(
    operation_id: str = Path(..., description="Operation ID (format: operations/xxx)"),
    api_key: str = Depends(verify_api_key_header)
):
    """
    Get long-running operation status and result.

    Use this endpoint to poll for video generation completion.
    """
    try:
        # Validate operation ID format
        if not operation_id.startswith("operations/"):
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    "Invalid operation ID format. Expected: operations/xxx", 400
                )
            )

        # Query task from database
        task = await generation_handler.db.get_task(operation_id)

        if not task:
            raise HTTPException(
                status_code=404,
                detail=response_formatter.format_error_response(
                    f"Operation {operation_id} not found", 404
                )
            )

        # Format response based on task status
        if task.status == "completed":
            result_urls = task.result_urls or []
            response_data = response_formatter.format_operation_result(
                operation_name=operation_id,
                done=True,
                result_urls=result_urls
            )
        elif task.status == "failed":
            response_data = response_formatter.format_operation_result(
                operation_name=operation_id,
                done=True,
                error_message=task.error_message or "Video generation failed"
            )
        else:
            # Still processing
            response_data = response_formatter.format_operation_result(
                operation_name=operation_id,
                done=False
            )

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        debug_logger.log_error(f"[Gemini] Get operation error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=response_formatter.format_error_response(str(e), 500)
        )


# ========== List Models Endpoints ==========

@router.get("/models")
async def gemini_list_models(
    api_key: str = Depends(verify_api_key_header)
):
    """List available Gemini models"""
    models: List[Dict[str, Any]] = []

    # Image models
    for model_name, config in GEMINI_IMAGE_MODEL_MAP.items():
        models.append(response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("-", " ").title(),
            description=f"Image generation model ({config['model_name']}). "
                       f"Supported ratios: {', '.join(config['supported_ratios'])}",
            generation_methods=["generateContent"]
        ))

    # Video models
    for model_name, config in GEMINI_VIDEO_MODEL_MAP.items():
        models.append(response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("-", " ").title(),
            description=f"Video generation model. "
                       f"Supported ratios: {', '.join(config['ratio_map'].keys())}",
            generation_methods=["predictLongRunning"]
        ))

    return JSONResponse(content={"models": models})


@router.get("/models/{model}")
async def gemini_get_model(
    model: str = Path(..., description="Model name"),
    api_key: str = Depends(verify_api_key_header)
):
    """Get specific model information"""
    # Remove 'models/' prefix if present
    model_name = model.replace("models/", "")

    model_info = gemini_mapper.get_model_info(model_name)

    if not model_info:
        raise HTTPException(
            status_code=404,
            detail=response_formatter.format_error_response(f"Model {model} not found", 404)
        )

    if model_info["type"] == "image":
        response_data = response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("-", " ").title(),
            description=f"Image generation model ({model_info['model_name']}). "
                       f"Supported ratios: {', '.join(model_info['supported_ratios'])}",
            generation_methods=["generateContent"]
        )
    else:
        response_data = response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("-", " ").title(),
            description=f"Video generation model. "
                       f"Supported ratios: {', '.join(model_info['supported_ratios'])}",
            generation_methods=["predictLongRunning"]
        )

    return JSONResponse(content=response_data)
