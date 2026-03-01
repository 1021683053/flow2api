# Flow2API Gemini API 兼容文档

本文档介绍 Flow2API 提供的 Google Gemini API 兼容接口。

## 概述

Flow2API 除了提供 OpenAI 兼容的 `/v1/chat/completions` 接口外，还提供 Gemini API 兼容接口，支持：

- **Gemini Image 生成** - 兼容 `generateContent` 接口，返回 base64 编码图片
- **Veo 视频生成** - 兼容 `predictLongRunning` 接口，支持异步轮询

所有 Gemini 兼容接口统一前缀为 `/v1beta`。

## 基础信息

- **Base URL**: `http://your-server:8000/v1beta`
- **认证方式**: 与原有接口相同，使用 `Authorization: Bearer YOUR_API_KEY` 或查询参数 `?key=YOUR_API_KEY`

## 模型列表

### 图片生成模型

| 模型名 | 内部模型 | 支持的比例 | 支持的尺寸 |
|-------|---------|-----------|-----------|
| `gemini-2.5-flash-image` | GEM_PIX | 16:9, 9:16 | 1K, 2K, 4K |
| `gemini-3-pro-image` | GEM_PIX_2 | 16:9, 9:16, 1:1, 4:3, 3:4 | 1K, 2K, 4K |
| `gemini-3.1-flash-image-preview` | NARWHAL | 16:9, 9:16, 1:1, 4:3, 3:4, 1:4, 4:1, 1:8, 8:1 | 1K, 2K, 4K |

### 视频生成模型

| 模型名 | 类型 | 支持的比例 | 支持的分辨率 |
|-------|------|-----------|-------------|
| `veo-3.1-generate-preview` | T2V | 16:9, 9:16 | 720p, 1080p, 4k |
| `veo-3.1-fast-generate-preview` | T2V | 16:9, 9:16 | 720p, 1080p, 4k |
| `veo-2.0-generate-001` | T2V | 16:9, 9:16 | 720p |

## API 端点

### 1. 列出模型

```http
GET /v1beta/models
```

返回所有可用的 Gemini 模型列表。

**响应示例**:
```json
{
  "models": [
    {
      "name": "models/gemini-3-pro-image",
      "version": "1.0",
      "displayName": "Gemini 3 Pro Image",
      "description": "Image generation model (GEM_PIX_2). Supported ratios: 16:9, 9:16, 1:1, 4:3, 3:4",
      "inputTokenLimit": 8192,
      "outputTokenLimit": 2048,
      "supportedGenerationMethods": ["generateContent"]
    },
    {
      "name": "models/veo-3.1-generate-preview",
      "version": "1.0",
      "displayName": "Veo 3.1 Generate Preview",
      "description": "Video generation model. Supported ratios: 16:9, 9:16",
      "inputTokenLimit": 8192,
      "outputTokenLimit": 2048,
      "supportedGenerationMethods": ["predictLongRunning"]
    }
  ]
}
```

---

### 2. 获取模型信息

```http
GET /v1beta/models/{model}
```

获取指定模型的详细信息。

**参数**:
- `model`: 模型名称，如 `gemini-3-pro-image` 或 `models/gemini-3-pro-image`

**响应示例**:
```json
{
  "name": "models/gemini-3-pro-image",
  "version": "1.0",
  "displayName": "Gemini 3 Pro Image",
  "description": "Image generation model (GEM_PIX_2). Supported ratios: 16:9, 9:16, 1:1, 4:3, 3:4",
  "inputTokenLimit": 8192,
  "outputTokenLimit": 2048,
  "supportedGenerationMethods": ["generateContent"]
}
```

---

### 3. 图片生成 (generateContent)

```http
POST /v1beta/models/{model}:generateContent
```

生成图片并返回 base64 编码结果。

**支持的模型**:
- `gemini-2.5-flash-image`
- `gemini-3-pro-image`
- `gemini-3.1-flash-image-preview`

**请求体**:
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "一只戴着帽子的可爱猫咪，水彩风格"
        }
      ]
    }
  ],
  "generationConfig": {
    "aspectRatio": "16:9",
    "imageSize": "2K"
  }
}
```

**参数说明**:
- `contents`: 内容数组，包含文本提示
  - `parts[].text`: 图片生成提示词
  - `parts[].inlineData`: （可选）参考图片的 base64 数据
- `generationConfig`: 生成配置
  - `aspectRatio`: 宽高比，可选值见模型列表
  - `imageSize`: 输出尺寸，可选 `1K`, `2K`, `4K`

**响应示例**:
```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "inlineData": {
              "mimeType": "image/jpeg",
              "data": "/9j/4AAQSkZJRgABAQAAAQ..."
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
```

**错误响应**:
```json
{
  "error": {
    "code": 400,
    "message": "Aspect ratio '21:9' not supported by gemini-3-pro-image. Supported: ['16:9', '9:16', '1:1', '4:3', '3:4']",
    "status": "INVALID_ARGUMENT"
  }
}
```

**curl 示例**:
```bash
curl -X POST "http://localhost:8000/v1beta/models/gemini-3-pro-image:generateContent" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{"text": "一只戴着帽子的可爱猫咪，水彩风格"}]
    }],
    "generationConfig": {
      "aspectRatio": "16:9",
      "imageSize": "2K"
    }
  }'
```

---

### 4. 视频生成 (predictLongRunning)

```http
POST /v1beta/models/{model}:predictLongRunning
```

提交视频生成任务，返回 operation ID 用于轮询查询。

**支持的模型**:
- `veo-3.1-generate-preview`
- `veo-3.1-fast-generate-preview`
- `veo-2.0-generate-001`

**请求体**:
```json
{
  "instances": [
    {
      "prompt": "一只猫在草地上奔跑，阳光明媚",
      "aspectRatio": "16:9",
      "resolution": "1080p"
    }
  ],
  "parameters": {}
}
```

**参数说明**:
- `instances`: 实例数组（目前只使用第一个）
  - `prompt`: 视频生成提示词
  - `aspectRatio`: 宽高比，`16:9` 或 `9:16`
  - `resolution`: 分辨率，`720p`, `1080p`, `4k`
- `parameters`: （可选）额外参数

**响应示例**:
```json
{
  "name": "operations/a1b2c3d4e5f6",
  "done": false,
  "metadata": {
    "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictOperationMetadata",
    "genericMetadata": {
      "createTime": "",
      "updateTime": ""
    }
  }
}
```

**curl 示例**:
```bash
curl -X POST "http://localhost:8000/v1beta/models/veo-3.1-generate-preview:predictLongRunning" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "instances": [{
      "prompt": "一只猫在草地上奔跑，阳光明媚",
      "aspectRatio": "16:9",
      "resolution": "1080p"
    }]
  }'
```

---

### 5. 查询操作状态

```http
GET /v1beta/operations/{operation_id}
```

查询视频生成任务的状态和结果。

**参数**:
- `operation_id`: Operation ID，格式为 `operations/xxx`

**响应示例 - 处理中**:
```json
{
  "name": "operations/a1b2c3d4e5f6",
  "done": false,
  "metadata": {
    "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictOperationMetadata"
  }
}
```

**响应示例 - 已完成**:
```json
{
  "name": "operations/a1b2c3d4e5f6",
  "done": true,
  "response": {
    "@type": "type.googleapis.com/google.cloud.aiplatform.v1.PredictResponse",
    "predictions": [
      {
        "mimeType": "video/mp4",
        "uri": "http://localhost:8000/tmp/a1b2c3d4.mp4"
      }
    ]
  }
}
```

**响应示例 - 失败**:
```json
{
  "name": "operations/a1b2c3d4e5f6",
  "done": true,
  "error": {
    "code": 500,
    "message": "Video generation failed",
    "status": "INTERNAL"
  }
}
```

**curl 示例**:
```bash
curl "http://localhost:8000/v1beta/operations/a1b2c3d4e5f6" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## 比例与尺寸映射

### 图片比例映射

| Gemini 比例 | 内部比例标识 |
|------------|-------------|
| `16:9` | IMAGE_ASPECT_RATIO_LANDSCAPE |
| `9:16` | IMAGE_ASPECT_RATIO_PORTRAIT |
| `1:1` | IMAGE_ASPECT_RATIO_SQUARE |
| `4:3` | IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE |
| `3:4` | IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR |
| `1:4` | IMAGE_ASPECT_RATIO_PORTRAIT_1_4 |
| `4:1` | IMAGE_ASPECT_RATIO_LANDSCAPE_4_1 |
| `1:8` | IMAGE_ASPECT_RATIO_PORTRAIT_1_8 |
| `8:1` | IMAGE_ASPECT_RATIO_LANDSCAPE_8_1 |

### 图片尺寸映射

| Gemini 尺寸 | 内部处理 |
|------------|---------|
| `1K` | 原始分辨率 |
| `2K` | UPSAMPLE_IMAGE_RESOLUTION_2K |
| `4K` | UPSAMPLE_IMAGE_RESOLUTION_4K |

### 视频分辨率映射

| Gemini 分辨率 | 内部处理 |
|-------------|---------|
| `720p` | 原始分辨率 |
| `1080p` | VIDEO_RESOLUTION_1080P + 放大模型 |
| `4k` | VIDEO_RESOLUTION_4K + 放大模型 |

---

## 错误码说明

| HTTP 状态码 | 错误场景 |
|-----------|---------|
| 400 | 无效请求参数（不支持的模型、比例、尺寸等） |
| 401 | 认证失败（API Key 无效） |
| 404 | Operation 不存在 |
| 500 | 服务器内部错误（生成失败等） |
| 503 | 无可用 Token |

---

## 与 OpenAI 兼容接口的区别

| 特性 | OpenAI 兼容接口 | Gemini 兼容接口 |
|-----|---------------|---------------|
| 端点前缀 | `/v1` | `/v1beta` |
| 图片输出 | URL (Markdown 格式) | base64 (inlineData) |
| 视频输出 | URL (HTML 格式) | 异步 Operation + URI |
| 模型选择 | 单一模型 ID | 模型 + 比例 + 尺寸/分辨率 |
| 参考图片 | 支持 | 支持 (inlineData) |

---

## 实现说明

### 架构设计

```
Client Request (Gemini Format)
    ↓
Gemini Routes (src/api/gemini_routes.py)
    ↓
GeminiModelMapper (参数映射)
    ↓
GenerationHandler (复用原有生成逻辑)
    ↓
GeminiResponseFormatter (响应格式转换)
    ↓
Client Response (Gemini Format)
```

### 非侵入式设计

- 所有 Gemini 兼容代码位于独立文件，不修改原有 `/v1/chat/completions` 逻辑
- 复用现有的 `GenerationHandler` 进行实际生成
- 复用现有的 `Task` 数据库存储视频 operation 状态
- 复用现有的文件缓存机制

---

## 测试示例

### 测试图片生成

```bash
# 测试基本图片生成
curl -X POST "http://localhost:8000/v1beta/models/gemini-3-pro-image:generateContent" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"parts": [{"text": "a beautiful sunset over the ocean"}]}]
  }'

# 测试 4K 图片生成
curl -X POST "http://localhost:8000/v1beta/models/gemini-3.1-flash-image-preview:generateContent" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"parts": [{"text": "futuristic cityscape"}]}],
    "generationConfig": {"aspectRatio": "1:1", "imageSize": "4K"}
  }'
```

### 测试视频生成

```bash
# 1. 提交视频生成任务
OPERATION=$(curl -s -X POST "http://localhost:8000/v1beta/models/veo-3.1-generate-preview:predictLongRunning" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "instances": [{"prompt": "a cat playing with a ball", "aspectRatio": "16:9", "resolution": "720p"}]
  }' | jq -r '.name')

echo "Operation: $OPERATION"

# 2. 轮询查询状态（循环执行直到 done: true）
curl "http://localhost:8000/v1beta/$OPERATION" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## 更新日志

### 2025-03-01
- 初始版本发布
- 支持 Gemini Image 生成 (generateContent)
- 支持 Veo 视频生成 (predictLongRunning)
- 支持模型列表查询
