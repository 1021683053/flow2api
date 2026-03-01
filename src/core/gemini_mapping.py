"""Gemini API model mapping configuration

This module provides mapping configurations between Gemini API model names/parameters
and internal Flow2API model configurations.
"""

# Gemini Image Model Mapping
# Maps Gemini model names to internal model_name and supported aspect ratios
GEMINI_IMAGE_MODEL_MAP = {
    "gemini-2.5-flash-image": {
        "model_name": "GEM_PIX",
        "supported_ratios": ["16:9", "9:16"],
        "ratio_map": {
            "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
            "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
        }
    },
    "gemini-3-pro-image": {
        "model_name": "GEM_PIX_2",
        "supported_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "ratio_map": {
            "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
            "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
            "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
            "4:3": "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE",
            "3:4": "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR",
        }
    },
    "gemini-3.1-flash-image-preview": {
        "model_name": "NARWHAL",
        "supported_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "1:4", "4:1", "1:8", "8:1"],
        "ratio_map": {
            "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
            "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
            "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
            "4:3": "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE",
            "3:4": "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR",
            "1:4": "IMAGE_ASPECT_RATIO_PORTRAIT_1_4",
            "4:1": "IMAGE_ASPECT_RATIO_LANDSCAPE_4_1",
            "1:8": "IMAGE_ASPECT_RATIO_PORTRAIT_1_8",
            "8:1": "IMAGE_ASPECT_RATIO_LANDSCAPE_8_1",
        }
    }
}

# Image size mapping to upsample configuration
GEMINI_IMAGE_SIZE_MAP = {
    "1K": None,  # No upsample, original resolution
    "2K": "UPSAMPLE_IMAGE_RESOLUTION_2K",
    "4K": "UPSAMPLE_IMAGE_RESOLUTION_4K",
}

# Gemini Video Model Mapping
# Maps Gemini video model names to internal model keys and supported aspect ratios
GEMINI_VIDEO_MODEL_MAP = {
    "veo-3.1-generate-preview": {
        "video_type": "t2v",
        "ratio_map": {
            "16:9": "veo_3_1_t2v_fast",
            "9:16": "veo_3_1_t2v_fast_portrait",
        }
    },
    "veo-3.1-fast-generate-preview": {
        "video_type": "t2v",
        "ratio_map": {
            "16:9": "veo_3_1_t2v_fast_ultra",
            "9:16": "veo_3_1_t2v_fast_portrait_ultra",
        }
    },
    "veo-2.0-generate-001": {
        "video_type": "t2v",
        "ratio_map": {
            "16:9": "veo_2_0_t2v",
            "9:16": "veo_2_0_t2v_portrait",
        }
    }
}

# Video resolution mapping to upsample configuration
GEMINI_VIDEO_RESOLUTION_MAP = {
    "720p": None,  # No upsample, original resolution
    "1080p": {
        "resolution": "VIDEO_RESOLUTION_1080P",
        "model_key": "veo_3_1_upsampler_1080p"
    },
    "4k": {
        "resolution": "VIDEO_RESOLUTION_4K",
        "model_key": "veo_3_1_upsampler_4k"
    }
}

# All supported Gemini models for listing
GEMINI_SUPPORTED_MODELS = list(GEMINI_IMAGE_MODEL_MAP.keys()) + list(GEMINI_VIDEO_MODEL_MAP.keys())
