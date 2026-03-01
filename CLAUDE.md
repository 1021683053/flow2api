# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Flow2API is a Python FastAPI-based service that provides an OpenAI-compatible API wrapper for Google Flow (VideoFX/Imagen image and video generation). It supports:

- Text-to-image and image-to-image generation
- Text-to-video and image-to-video generation
- Video upscaling (4K, 1080p)
- Multi-token load balancing with concurrency control
- Browser-based captcha solving for token management

## Development Commands

### Local Development

```bash
# Setup virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Install browser automation dependencies (for captcha solving)
playwright install chromium

# Run the server
python main.py
# Server starts at http://0.0.0.0:8000 by default
```

### Docker Development

```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Configuration

1. Copy `config/setting_example.toml` to `config/setting.toml`
2. Default admin credentials: `admin` / `admin` (change on first login)
3. Default API key: `han1234`

## Architecture Overview

### Service Layer Architecture

The application uses a layered service architecture with dependency injection:

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Routes (src/api/routes.py, src/api/admin.py)       │
├─────────────────────────────────────────────────────────────┤
│  Generation Handler (src/services/generation_handler.py)    │
│  ├── Handles OpenAI-compatible API format                   │
│  ├── Model configuration (MODEL_CONFIG dict)                │
│  └── Routes to image/video generation                       │
├─────────────────────────────────────────────────────────────┤
│  Core Services                                              │
│  ├── TokenManager (src/services/token_manager.py)           │
│  │   └── ST/AT token lifecycle, project management          │
│  ├── LoadBalancer (src/services/load_balancer.py)           │
│  │   └── Token selection strategy                           │
│  ├── ConcurrencyManager (src/services/concurrency_manager.py)│
│  │   └── Per-token concurrent request limits                │
│  └── FlowClient (src/services/flow_client.py)               │
│      └── Google Flow API HTTP client (curl_cffi)            │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure                                             │
│  ├── Database (src/core/database.py) - SQLite (aiosqlite)   │
│  ├── Config (src/core/config.py) - TOML-based settings      │
│  └── FileCache (src/services/file_cache.py)                 │
└─────────────────────────────────────────────────────────────┘
```

### Token System (ST/AT)

Google Flow uses a two-token authentication system:

1. **ST (Session Token)**: Long-lived cookie (`__Secure-next-auth.session-token`)
   - Stored in database as `tokens.st`
   - Used to obtain AT when expired
   - Can be refreshed via browser automation (personal mode) or captcha service

2. **AT (Access Token)**: Short-lived JWT for API calls
   - Converted from ST via `TokenManager.st_to_at()`
   - Expires after ~1 hour (`at_expires`)
   - Automatically refreshed when expired

### Model Configuration

Models are defined in `src/services/generation_handler.py` in the `MODEL_CONFIG` dictionary. Each model specifies:

- `type`: `"image"` or `"video"`
- `model_name`: e.g., `"GEM_PIX_2"`, `"veo_3_1_t2v_fast"`
- `aspect_ratio`: For images (e.g., `"IMAGE_ASPECT_RATIO_LANDSCAPE"`)
- `model_key`: For videos (e.g., `"veo_3_1_t2v_fast_landscape"`)
- `upsample`: Optional upscale config for 2K/4K

### Captcha Solving Modes

The system supports multiple captcha solving methods configured via `captcha_method`:

- `"yescaptcha"`: Third-party captcha service
- `"capmonster"`, `"ezcaptcha"`, `"capsolver"`: Alternative services
- `"browser"`: Headless browser automation (playwright)
- `"personal"`: Browser with persistent login (nodriver) - opens actual Chrome window

### Database Schema

SQLite database (`data/flow.db`) with tables:

- `tokens`: ST/AT credentials, credits, project associations
- `token_stats`: Usage statistics and consecutive error tracking
- `projects`: VideoFX project mappings
- `tasks`: Async generation tasks
- `admin_config`: API key, credentials, error threshold
- `proxy_config`, `cache_config`, `captcha_config`, `debug_config`: Feature settings

### Key Entry Points

| File | Purpose |
|------|---------|
| `main.py` | Entry point wrapper, runs uvicorn server |
| `src/main.py` | FastAPI app initialization, lifespan management |
| `src/api/routes.py` | OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/models`) |
| `src/api/admin.py` | Admin API for token/config management |

### Request Flow

1. Client sends OpenAI-compatible request to `POST /v1/chat/completions`
2. `routes.py` extracts prompt/images from messages array
3. `GenerationHandler.handle_generation()` selects token via load balancer
4. `FlowClient` makes request to Google Flow API with AT
5. Response is streamed back in SSE format (OpenAI compatible)
6. Generated files are cached locally in `/tmp/` directory

### Concurrency Control

Each token has configurable concurrency limits:
- `image_concurrency`: Max concurrent image generations (-1 = unlimited)
- `video_concurrency`: Max concurrent video generations (-1 = unlimited)

The `ConcurrencyManager` tracks active requests per token and rejects when limits exceeded.

### Debugging

Enable debug logging via admin panel or config:

```toml
[debug]
enabled = true
log_requests = true
log_responses = true
```

Logs written to `logs.txt` with masked tokens.
