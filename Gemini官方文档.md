# Google Gemini API 官方技术文档

> 本文档仅包含 Gemini API 官方接口定义，用于开发参考
> 最后更新：2026-03-03

---

## 目录

1. [模型列表](#一模型列表)
2. [图像生成 API](#二图像生成-api)
3. [视频生成 API (Veo)](#三视频生成-api-veo)
4. [配置参数](#四配置参数)
5. [错误码参考](#五错误码参考)

---

## 一、模型列表

### 1.1 图像生成模型

| 模型 ID | 分辨率支持 | 输出格式 |
|---------|-----------|---------|
| `gemini-2.5-flash-image` | 标准分辨率 | PNG/JPEG |
| `gemini-3.1-flash-image-preview` | 最高 2K | PNG/JPEG |
| `gemini-3-pro-image-preview` | 最高 2K | PNG/JPEG |

### 1.2 视频生成模型

| 模型 ID | 分辨率 | 时长 | 音频 |
|---------|-------|------|------|
| `veo-3.1-generate-preview` | 720p/1080p | 4-8秒 | 原生音频 |
| `veo-3.1-fast-preview` | 720p/1080p | 4-8秒 | 原生音频 |
| `veo-3` | 1080p | 8秒 | 原生音频 |
| `veo-2` | 最高4K | 更长片段 | 无 |

---

## 二、图像生成 API

### 2.1 端点

```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
```

### 2.2 请求头

```
Content-Type: application/json
x-goog-api-key: {YOUR_API_KEY}
```

### 2.3 请求体

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "string"
        }
      ]
    }
  ],
  "generationConfig": {
    "temperature": number,
    "topP": number,
    "topK": integer,
    "candidateCount": integer,
    "maxOutputTokens": integer,
    "stopSequences": ["string"],
    "responseMimeType": "string",
    "responseModalities": ["TEXT", "IMAGE"],
    "imageConfig": {
      "aspectRatio": "string",
      "imageSize": "string"
    }
  },
  "safetySettings": [
    {
      "category": "HARM_CATEGORY_xxx",
      "threshold": "BLOCK_xxx"
    }
  ]
}
```

### 2.4 响应体

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "text": "string"
          },
          {
            "inlineData": {
              "mimeType": "image/png",
              "data": "base64-encoded-string"
            }
          }
        ]
      },
      "finishReason": "STOP",
      "index": 0,
      "safetyRatings": [
        {
          "category": "HARM_CATEGORY_xxx",
          "probability": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
          "blocked": boolean
        }
      ]
    }
  ],
  "usageMetadata": {
    "promptTokenCount": integer,
    "candidatesTokenCount": integer,
    "totalTokenCount": integer
  }
}
```

### 2.5 ImageConfig 参数

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `aspectRatio` | string | 否 | "1:1" | 图像宽高比 |
| `imageSize` | string | 否 | "1K" | 图像分辨率 |

**支持的 aspectRatio 值：**
- `"1:1"` - 正方形
- `"16:9"` - 宽屏横版
- `"9:16"` - 竖屏
- `"4:3"` - 标准横版
- `"3:4"` - 标准竖版
- `"21:9"` - 超宽屏
- `"2:3"` - 竖版
- `"3:2"` - 横版
- `"4:5"` - 竖版
- `"5:4"` - 横版
- `"1:4"` - 长竖版
- `"4:1"` - 长横版
- `"1:8"` - 极长竖版
- `"8:1"` - 极长横版

**支持的 imageSize 值：**
- `"512px"`
- `"1K"`
- `"2K"`
- `"4K"`

---

## 三、视频生成 API (Veo)

### 3.1 端点

**创建生成任务：**
```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning
```

**查询操作状态：**
```
GET https://generativelanguage.googleapis.com/v1beta/{operation_name}
```

### 3.2 请求体

```json
{
  "instances": [
    {
      "prompt": "string",
      "image": {
        "bytesBase64Encoded": "string",
        "mimeType": "string"
      }
    }
  ],
  "parameters": {
    "aspectRatio": "string",
    "resolution": "string",
    "duration": "string",
    "negativePrompt": "string",
    "numberOfVideos": integer,
    "personGeneration": "string"
  }
}
```

### 3.3 响应体（提交）

```json
{
  "name": "operations/operation-id",
  "done": false,
  "metadata": {
    "@type": "type.googleapis.com/google.ai.generativelanguage.v1beta.PredictLongRunningMetadata",
    "predictedOutputTokenCount": integer
  }
}
```

### 3.4 响应体（完成）

```json
{
  "name": "operations/operation-id",
  "done": true,
  "response": {
    "@type": "type.googleapis.com/google.ai.generativelanguage.v1beta.GenerateVideosResponse",
    "generatedVideos": [
      {
        "video": {
          "uri": "string",
          "mimeType": "video/mp4",
          "videoBytes": "base64-encoded-string"
        }
      }
    ]
  }
}
```

### 3.5 GenerateVideosConfig 参数

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `aspectRatio` | string | 否 | "16:9" | 视频宽高比 |
| `resolution` | string | 否 | "720p" | 视频分辨率 |
| `duration` | string | 否 | "8s" | 视频时长 |
| `negativePrompt` | string | 否 | - | 负面提示词 |
| `numberOfVideos` | integer | 否 | 1 | 生成视频数量 |
| `personGeneration` | string | 否 | - | 人物生成设置 |

**aspectRatio 可选值：**
- `"16:9"` - 横版（默认）
- `"9:16"` - 竖版

**resolution 可选值：**
- `"720p"` - 标准清晰度
- `"1080p"` - 全高清
- `"4k"` - 超高清（Veo 2 支持）

**duration 可选值：**
- `"4s"` - 4秒
- `"8s"` - 8秒

**personGeneration 可选值：**
- `"allow_adult"` - 允许生成成年人
- `"dont_allow"` - 禁止生成人物

---

## 四、配置参数

### 4.1 GenerationConfig 参数

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `temperature` | number | 否 | 1.0 | 随机性 (0.0-2.0) |
| `topP` | number | 否 | 0.95 | 核采样概率阈值 |
| `topK` | integer | 否 | 64 | 核采样候选数 |
| `candidateCount` | integer | 否 | 1 | 生成候选数 |
| `maxOutputTokens` | integer | 否 | 8192 | 最大输出 token 数 |
| `stopSequences` | array | 否 | [] | 停止序列 |
| `responseMimeType` | string | 否 | "text/plain" | 响应 MIME 类型 |
| `responseModalities` | array | 否 | ["TEXT"] | 响应模态 |

### 4.2 SafetySetting 参数

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `category` | string | 是 | - | 安全类别 |
| `threshold` | string | 是 | - | 拦截阈值 |

**category 可选值：**
- `HARM_CATEGORY_HARASSMENT`
- `HARM_CATEGORY_HATE_SPEECH`
- `HARM_CATEGORY_SEXUALLY_EXPLICIT`
- `HARM_CATEGORY_DANGEROUS_CONTENT`
- `HARM_CATEGORY_CIVIC_INTEGRITY`

**threshold 可选值：**
- `BLOCK_NONE` - 不拦截
- `BLOCK_ONLY_HIGH` - 仅拦截高风险
- `BLOCK_MEDIUM_AND_ABOVE` - 拦截中高风险
- `BLOCK_LOW_AND_ABOVE` - 拦截所有风险

---

## 五、错误码参考

### 5.1 HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| `200 OK` | 请求成功 |
| `400 Bad Request` | 请求参数错误 |
| `401 Unauthorized` | API 密钥无效 |
| `403 Forbidden` | 权限不足或配额已用完 |
| `404 Not Found` | 模型不存在 |
| `429 Too Many Requests` | 请求频率过高 |
| `500 Internal Server Error` | 服务器内部错误 |
| `503 Service Unavailable` | 服务暂不可用 |

### 5.2 错误响应体

```json
{
  "error": {
    "code": integer,
    "message": "string",
    "status": "string",
    "details": [
      {
        "@type": "string",
        "reason": "string",
        "domain": "string",
        "metadata": {
          "key": "value"
        }
      }
    ]
  }
}
```

### 5.3 常见错误码

| 错误码 | 说明 |
|--------|------|
| `INVALID_ARGUMENT` | 参数无效 |
| `PERMISSION_DENIED` | 权限被拒绝 |
| `RESOURCE_EXHAUSTED` | 资源耗尽（配额） |
| `INTERNAL` | 内部错误 |
| `UNAVAILABLE` | 服务不可用 |
| `DEADLINE_EXCEEDED` | 请求超时 |

---

## 六、调用示例

### 6.1 图像生成 (cURL)

```bash
curl -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key=$API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{
        "text": "一只穿着宇航服的猫在月球上"
      }]
    }],
    "generationConfig": {
      "responseModalities": ["TEXT", "IMAGE"],
      "imageConfig": {
        "aspectRatio": "16:9",
        "imageSize": "2K"
      }
    }
  }'
```

### 6.2 视频生成 (cURL)

**提交任务：**
```bash
curl -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate-preview:predictLongRunning?key=$API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "instances": [{
      "prompt": "大峡谷日落时的壮观无人机视角"
    }],
    "parameters": {
      "aspectRatio": "16:9",
      "resolution": "1080p"
    }
  }'
```

**查询状态：**
```bash
curl -X GET \
  "https://generativelanguage.googleapis.com/v1beta/operations/{operation_id}?key=$API_KEY"
```

---

## 参考链接

- [Gemini API 官方文档](https://ai.google.dev/gemini-api/docs)
- [REST API 参考](https://ai.google.dev/api/rest)
- [Python SDK](https://github.com/googleapis/python-genai)
- [JavaScript SDK](https://github.com/google/genai-sdk)

---

*本文档基于 Google Gemini API 官方文档整理*
