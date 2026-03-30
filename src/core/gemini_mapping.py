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
    "gemini-3-pro-image-preview": {
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

# All supported Gemini models for listing
GEMINI_SUPPORTED_MODELS = list(GEMINI_IMAGE_MODEL_MAP.keys())
