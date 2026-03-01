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

from fastapi import APIRouter, Depends, HTTPException, Path
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


class GeminiGenerationConfig(BaseModel):
    """Generation configuration for image generation"""
    aspectRatio: Optional[str] = "16:9"
    imageSize: Optional[str] = None  # "1K", "2K", "4K"


class GeminiGenerateContentRequest(BaseModel):
    """Gemini generateContent request body"""
    contents: List[GeminiContent]
    generationConfig: Optional[GeminiGenerationConfig] = None


class GeminiPredictInstance(BaseModel):
    """Single prediction instance for video generation"""
    prompt: str
    aspectRatio: Optional[str] = "16:9"
    resolution: Optional[str] = "720p"  # "720p", "1080p", "4k"


class GeminiPredictLongRunningRequest(BaseModel):
    """Gemini predictLongRunning request body"""
    instances: List[GeminiPredictInstance]
    parameters: Optional[Dict[str, Any]] = None


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

@router.post("/models/{model}:generateContent")
async def gemini_generate_content(
    model: str = Path(..., description="Gemini model name"),
    request: GeminiGenerateContentRequest = None,
    api_key: str = Depends(verify_api_key_header)
):
    """
    Gemini API compatible image generation endpoint.

    Supported models:
    - gemini-2.5-flash-image (aspect ratios: 16:9, 9:16)
    - gemini-3-pro-image (aspect ratios: 16:9, 9:16, 1:1, 4:3, 3:4)
    - gemini-3.1-flash-image-preview (aspect ratios: 16:9, 9:16, 1:1, 4:3, 3:4, 1:4, 4:1, 1:8, 8:1)

    Supported sizes: 1K, 2K, 4K
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

        # Extract prompt from contents
        prompt = extract_prompt_from_contents(request.contents)

        # Extract reference images (if any)
        images = extract_reference_images_from_contents(request.contents)

        # Extract generation config
        aspect_ratio = "16:9"
        image_size = None
        if request.generationConfig:
            aspect_ratio = request.generationConfig.aspectRatio or "16:9"
            image_size = request.generationConfig.imageSize

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

        # Call generation handler (non-streaming for Gemini format)
        result_chunks = []
        async for chunk in generation_handler.handle_generation(
            model=internal_model_id,
            prompt=prompt,
            images=images,
            stream=False
        ):
            result_chunks.append(chunk)

        if not result_chunks:
            raise HTTPException(
                status_code=500,
                detail=response_formatter.format_error_response("Generation failed: No response", 500)
            )

        # Parse result - GenerationHandler returns JSON string in OpenAI format
        final_result = result_chunks[-1]

        try:
            result_data = json.loads(final_result)
            # Extract content from OpenAI format
            content = result_data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Extract image URL from markdown format ![...](url)
            url_match = re.search(r'!\[.*?\]\((.*?)\)', content)
            if not url_match:
                raise HTTPException(
                    status_code=500,
                    detail=response_formatter.format_error_response("No image found in generation result", 500)
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
    api_key: str = Depends(verify_api_key_header)
):
    """
    Gemini API compatible video generation endpoint.

    Supported models:
    - veo-3.1-generate-preview (aspect ratios: 16:9, 9:16; resolutions: 720p, 1080p, 4k)
    - veo-3.1-fast-generate-preview (aspect ratios: 16:9, 9:16; resolutions: 720p, 1080p, 4k)
    - veo-2.0-generate-001 (aspect ratios: 16:9, 9:16; resolutions: 720p)

    Returns an operation that must be polled via GET /operations/{operation_id}
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

        # Extract parameters
        prompt = instance.prompt
        aspect_ratio = instance.aspectRatio or "16:9"
        resolution = instance.resolution or "720p"

        if not prompt:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response("prompt cannot be empty", 400)
            )

        # Map to internal model
        internal_model_key, upsample = gemini_mapper.map_video_model(
            gemini_model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution
        )

        # Build internal model ID for MODEL_CONFIG lookup
        ratio_suffix = aspect_ratio.replace(":", "-")
        internal_model_id = f"{model}-{ratio_suffix}"
        if resolution and resolution != "720p":
            internal_model_id = f"{internal_model_id}-{resolution.lower()}"

        debug_logger.log_info(
            f"[Gemini] Video generation: model={model}, internal={internal_model_id}, "
            f"prompt={prompt[:50]}..., aspect_ratio={aspect_ratio}, resolution={resolution}"
        )

        # Generate unique operation ID
        operation_id = f"operations/{uuid.uuid4().hex}"

        # Store operation in database for polling
        # For video generation, we create a placeholder task
        # The actual task ID will be updated when the video generation starts
        from ..core.database import Database
        db = generation_handler.db

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
            prompt=prompt,
            status="pending",
            progress=0,
            scene_id=None
        )
        await db.create_task(task)

        # Start video generation in background
        import asyncio
        asyncio.create_task(
            _process_video_generation(
                operation_id=operation_id,
                internal_model_id=internal_model_id,
                prompt=prompt,
                token=token
            )
        )

        # Return operation response immediately
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
    token: Any
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

        # Call generation handler
        result_url = None
        async for chunk in generation_handler.handle_generation(
            model=internal_model_id,
            prompt=prompt,
            images=None,
            stream=False
        ):
            # Parse result to extract video URL
            try:
                result_data = json.loads(chunk)
                content = result_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                # Extract video URL from HTML format
                url_match = re.search(r"src='([^']+)'", content)
                if url_match:
                    result_url = url_match.group(1)
            except:
                pass

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
            await generation_handler.db.update_task(
                operation_id,
                status="failed",
                error_message="No video URL in generation result",
                completed_at=time.time()
            )
            debug_logger.log_error(f"[Gemini] Video generation failed for operation {operation_id}: No URL")

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
