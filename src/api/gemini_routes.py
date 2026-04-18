"""Gemini API compatible routes

This module provides Google Gemini API compatible endpoints for image and video generation.
All endpoints are prefixed with /v1beta in main.py.

Endpoints:
- POST /models/{model}:generateContent - Image generation
- POST /models/{model}:predictLongRunning - Video generation
- GET /models - List available models
- GET /models/{model} - Get model information
"""

import base64
import json
import re
import uuid
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.auth import verify_api_key_header
from ..core.gemini_mapping import GEMINI_IMAGE_MODEL_MAP
from ..core.logger import debug_logger
from ..services.generation_handler import GenerationHandler, MODEL_CONFIG
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


def _ensure_generation_handler() -> GenerationHandler:
    if generation_handler is None:
        raise HTTPException(
            status_code=503,
            detail=response_formatter.format_error_response("Generation handler not initialized", 503)
        )
    return generation_handler


class _GeminiRiskAcceptingFlowClientProxy:
    """仅供 v1beta 路由使用：参考图上传时忽略 project_id，接受 legacy fallback 风险。"""

    def __init__(self, base_flow_client):
        self._base_flow_client = base_flow_client

    def __getattr__(self, name: str):
        return getattr(self._base_flow_client, name)

    async def upload_image(
        self,
        at: str,
        image_bytes: bytes,
        aspect_ratio: str = "IMAGE_ASPECT_RATIO_LANDSCAPE",
        project_id: Optional[str] = None
    ) -> str:
        return await self._base_flow_client.upload_image(
            at=at,
            image_bytes=image_bytes,
            aspect_ratio=aspect_ratio,
            project_id=None,
        )


def _get_request_generation_handler(reference_images: Optional[List[bytes]]) -> GenerationHandler:
    base_handler = _ensure_generation_handler()
    if not reference_images:
        return base_handler

    debug_logger.log_warning(
        "[Gemini] v1beta 检测到参考图输入，启用兼容上传适配："
        "上传时忽略 project_id，允许 legacy fallback，存在素材归属到错误项目的风险。"
    )

    compat_flow_client = _GeminiRiskAcceptingFlowClientProxy(base_handler.flow_client)
    proxy_manager = getattr(base_handler.file_cache, "proxy_manager", None) if getattr(base_handler, "file_cache", None) else None
    return GenerationHandler(
        flow_client=compat_flow_client,
        token_manager=base_handler.token_manager,
        load_balancer=base_handler.load_balancer,
        db=base_handler.db,
        concurrency_manager=base_handler.concurrency_manager,
        proxy_manager=proxy_manager,
    )


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


class GeminiVideoConfig(BaseModel):
    """Video generation configuration (nested in generationConfig)"""
    aspectRatio: Optional[str] = None
    resolution: Optional[str] = None


class GeminiVideoGenerationConfig(BaseModel):
    """Generation configuration for video generation"""
    videoConfig: Optional[GeminiVideoConfig] = None


class GeminiPredictLongRunningRequest(BaseModel):
    """Gemini predictLongRunning request body (简化格式，contents 对齐 image)"""
    contents: List[GeminiContent]
    generationConfig: Optional[GeminiVideoGenerationConfig] = None


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
    return model in MODEL_CONFIG and MODEL_CONFIG[model].get("type") == "video"


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
    _api_key: str = Depends(verify_api_key_header)
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
        internal_model_id, _upsample = gemini_mapper.map_image_model(
            gemini_model=model,
            aspect_ratio=aspect_ratio,
            image_size=image_size
        )

        debug_logger.log_info(
            f"[Gemini] Image generation: model={model}, internal={internal_model_id}, "
            f"prompt={prompt[:50]}..., aspect_ratio={aspect_ratio}, size={image_size}"
        )

        request_handler = _get_request_generation_handler(images)

        # Call generation handler with stream=True to get actual generation result
        # Then collect all chunks and extract the final result
        result_chunks = []
        async for chunk in request_handler.handle_generation(
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
    model: str = Path(..., description="Local video model name"),
    request: GeminiPredictLongRunningRequest = None,
    _api_key: str = Depends(verify_api_key_header)
):
    """
    Gemini API compatible video generation endpoint (synchronous only).

    Request format (aligned with image endpoint):
    {
      "contents": [{"parts": [{"text": "..."}, {"inlineData": {"mimeType": "image/jpeg", "data": "..."}}]}]
    }
    """
    try:
        # Validate this is a local video model
        if model not in MODEL_CONFIG or MODEL_CONFIG[model].get("type") != "video":
            if is_image_model(model):
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Model {model} is an image model. Use :generateContent endpoint for image generation.",
                        400
                    )
                )

            supported_video_models = sorted([
                model_name for model_name, config in MODEL_CONFIG.items()
                if config.get("type") == "video"
            ])
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Unknown video model: {model}. Supported local video models: {supported_video_models}",
                    400
                )
            )

        if not request.contents:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response("contents cannot be empty", 400)
            )

        # Extract prompt (optional for i2v)
        prompt_parts: List[str] = []
        for content in request.contents:
            for part in content.parts:
                if part.text:
                    prompt_parts.append(part.text)
        prompt = " ".join(prompt_parts).strip()

        # Extract image input from inlineData (optional)
        images = extract_reference_images_from_contents(request.contents)
        request_handler = _get_request_generation_handler(images)

        # Parse generationConfig.videoConfig (optional, validated but not mapped)
        aspect_ratio = None
        resolution = None
        if request.generationConfig and request.generationConfig.videoConfig:
            video_config = request.generationConfig.videoConfig
            aspect_ratio = video_config.aspectRatio
            resolution = video_config.resolution

            if aspect_ratio and aspect_ratio not in GEMINI_SUPPORTED_VIDEO_ASPECT_RATIOS:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Invalid aspectRatio: {aspect_ratio}. "
                        f"Supported values: {GEMINI_SUPPORTED_VIDEO_ASPECT_RATIOS}",
                        400
                    )
                )

            if resolution and resolution not in GEMINI_SUPPORTED_VIDEO_RESOLUTIONS:
                raise HTTPException(
                    status_code=400,
                    detail=response_formatter.format_error_response(
                        f"Invalid resolution: {resolution}. "
                        f"Supported values: {GEMINI_SUPPORTED_VIDEO_RESOLUTIONS}",
                        400
                    )
                )

        # Must have at least one input type
        if not prompt and not images:
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    "Either text or inlineData image must be provided in contents.parts",
                    400
                )
            )

        debug_logger.log_info(
            f"[Gemini] Video generation: model={model}, "
            f"prompt={prompt[:50] if prompt else '(empty)'}..., "
            f"image_count={len(images) if images else 0}, "
            f"aspect_ratio={aspect_ratio}, resolution={resolution}"
        )

        # Run generation synchronously and parse stream chunks
        operation_id = f"operations/{uuid.uuid4().hex}"

        # Optional consistency check: if model ratio is fixed, validate against request config
        model_aspect_ratio = MODEL_CONFIG[model].get("aspect_ratio")
        if aspect_ratio and model_aspect_ratio == "VIDEO_ASPECT_RATIO_LANDSCAPE" and aspect_ratio != "16:9":
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Model {model} only supports aspectRatio 16:9", 400
                )
            )
        if aspect_ratio and model_aspect_ratio == "VIDEO_ASPECT_RATIO_PORTRAIT" and aspect_ratio != "9:16":
            raise HTTPException(
                status_code=400,
                detail=response_formatter.format_error_response(
                    f"Model {model} only supports aspectRatio 9:16", 400
                )
            )
        result_url = None
        error_messages = []
        all_chunks = []

        async for chunk in request_handler.handle_generation(
            model=model,
            prompt=prompt,
            images=images,
            stream=True
        ):
            all_chunks.append(chunk)

            chunk_str = chunk.strip()
            if chunk_str.startswith("data: "):
                chunk_str = chunk_str[6:]

            try:
                result_data = json.loads(chunk_str)

                if "error" in result_data:
                    error_msg = result_data["error"].get("message", "Unknown error")
                    error_messages.append(error_msg)
                    continue

                delta = result_data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if not content:
                    content = result_data.get("choices", [{}])[0].get("message", {}).get("content", "")

                url_match = re.search(r"src='([^']+)'", content)
                if url_match:
                    result_url = url_match.group(1)
            except (json.JSONDecodeError, IndexError, TypeError):
                chunk_lower = chunk.lower()
                if any(err in chunk_lower for err in ["error", "失败", "错误", "captcha", "验证码", "403", "401", "429"]):
                    error_messages.append(chunk[:200])
                continue

        if result_url:
            response_data = response_formatter.format_operation_result(
                operation_name=operation_id,
                done=True,
                result_urls=[result_url]
            )
            return JSONResponse(content=response_data)

        if error_messages:
            combined_error = "; ".join(error_messages[:3])
            response_data = response_formatter.format_operation_result(
                operation_name=operation_id,
                done=True,
                error_message=f"Video generation failed: {combined_error}"
            )
            return JSONResponse(content=response_data)

        raw_preview = " | ".join([c[:100] for c in all_chunks[-3:]]) if all_chunks else ""
        response_data = response_formatter.format_operation_result(
            operation_name=operation_id,
            done=True,
            error_message=f"No video URL found. Raw response preview: {raw_preview[:500]}"
        )
        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        debug_logger.log_error(f"[Gemini] Video generation error: {str(e)}")
        response_data = response_formatter.format_operation_result(
            operation_name=f"operations/{uuid.uuid4().hex}",
            done=True,
            error_message=str(e)
        )
        return JSONResponse(content=response_data)


# ========== List Models Endpoints ==========

@router.get("/models")
async def gemini_list_models(
    _api_key: str = Depends(verify_api_key_header)
):
    """List available Gemini models"""
    models: List[Dict[str, Any]] = []

    # Image models (official Gemini names)
    for model_name, config in GEMINI_IMAGE_MODEL_MAP.items():
        models.append(response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("-", " ").title(),
            description=f"Image generation model ({config['model_name']}). "
                       f"Supported ratios: {', '.join(config['supported_ratios'])}",
            generation_methods=["generateContent"]
        ))

    # Video models (local model names)
    for model_name in sorted([k for k, v in MODEL_CONFIG.items() if v.get("type") == "video"]):
        model_config = MODEL_CONFIG[model_name]
        aspect_ratio = model_config.get("aspect_ratio")
        supported_ratios: List[str] = []
        if aspect_ratio == "VIDEO_ASPECT_RATIO_LANDSCAPE":
            supported_ratios = ["16:9"]
        elif aspect_ratio == "VIDEO_ASPECT_RATIO_PORTRAIT":
            supported_ratios = ["9:16"]

        ratio_desc = f" Supported ratios: {', '.join(supported_ratios)}" if supported_ratios else ""
        models.append(response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("_", " ").title(),
            description=f"Local video generation model ({model_config.get('video_type', 'video')}).{ratio_desc}",
            generation_methods=["predictLongRunning"]
        ))

    return JSONResponse(content={"models": models})


@router.get("/models/{model}")
async def gemini_get_model(
    model: str = Path(..., description="Model name"),
    _api_key: str = Depends(verify_api_key_header)
):
    """Get specific model information"""
    # Remove 'models/' prefix if present
    model_name = model.replace("models/", "")

    if model_name in GEMINI_IMAGE_MODEL_MAP:
        model_info = gemini_mapper.get_model_info(model_name)
        response_data = response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("-", " ").title(),
            description=f"Image generation model ({model_info['model_name']}). "
                       f"Supported ratios: {', '.join(model_info['supported_ratios'])}",
            generation_methods=["generateContent"]
        )
        return JSONResponse(content=response_data)

    if model_name in MODEL_CONFIG and MODEL_CONFIG[model_name].get("type") == "video":
        model_config = MODEL_CONFIG[model_name]
        aspect_ratio = model_config.get("aspect_ratio")
        supported_ratios: List[str] = []
        if aspect_ratio == "VIDEO_ASPECT_RATIO_LANDSCAPE":
            supported_ratios = ["16:9"]
        elif aspect_ratio == "VIDEO_ASPECT_RATIO_PORTRAIT":
            supported_ratios = ["9:16"]

        ratio_desc = f" Supported ratios: {', '.join(supported_ratios)}" if supported_ratios else ""
        response_data = response_formatter.format_model_info(
            model_name=model_name,
            display_name=model_name.replace("_", " ").title(),
            description=f"Local video generation model ({model_config.get('video_type', 'video')}).{ratio_desc}",
            generation_methods=["predictLongRunning"]
        )
        return JSONResponse(content=response_data)

    raise HTTPException(
        status_code=404,
        detail=response_formatter.format_error_response(f"Model {model} not found", 404)
    )
