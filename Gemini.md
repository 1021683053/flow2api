# Flow2API Gemini 兼容接口说明

本文档描述 Flow2API 当前提供的 Gemini 兼容接口行为。

更新时间：2026-03-06

## 1. 基础信息

- Base URL: `http://your-host:8000/v1beta`
- 认证方式：
  - `Authorization: Bearer YOUR_API_KEY`
  - 或 `?key=YOUR_API_KEY`

## 2. 当前可用端点

### 图片相关

- `GET /v1beta/models`
- `GET /v1beta/models/{model}`
- `POST /v1beta/models/{model}:generateContent`

### 视频相关

- `POST /v1beta/models/{model}:predictLongRunning`

当前代码中已经没有视频轮询端点：

- `GET /v1beta/operations/{operation_id}` 不再支持

## 3. 模型现状

### 4.1 图片模型

图片接口继续使用 Gemini 风格模型名。

| Gemini 模型名 | 当前实际可用比例 | 当前实际可用尺寸 | 内部模型 |
| --- | --- | --- | --- |
| `gemini-2.5-flash-image` | `16:9`、`9:16` | `1K` | `GEM_PIX` |
| `gemini-3-pro-image-preview` | `16:9`、`9:16`、`1:1`、`4:3`、`3:4` | `1K`、`2K`、`4K` | `GEM_PIX_2` |
| `gemini-3.1-flash-image-preview` | `16:9`、`9:16`、`1:1`、`4:3`、`3:4` | `1K`、`2K`、`4K` | `NARWHAL` |

注意：

- 路由层允许校验的 `aspectRatio` 范围比实际后端更大，但真正可用能力以 `MODEL_CONFIG` 中存在的模型为准。
- `gemini-3.1-flash-image-preview` 在映射表里声明了 `1:4`、`4:1`、`1:8`、`8:1`，但当前后端没有对应模型，实际调用会报不支持。
- 路由层把 `512px` 列为可校验值，但当前映射只支持 `1K`、`2K`、`4K`，因此 `512px` 目前并不能成功生成。

### 4.2 视频模型

视频接口当前不再使用官方 Veo 模型名，而是直接使用本地 `MODEL_CONFIG` 中的模型键。

可通过 `GET /v1beta/models` 获取完整列表。当前视频模型大致分为三类：

| 类型 | 说明 | 示例模型名 |
| --- | --- | --- |
| `t2v` | 文生视频，不接收图片 | `veo_3_1_t2v_fast_landscape` |
| `i2v` | 图生视频，通常要求 1-2 张图片 | `veo_3_1_i2v_s_fast_fl` |
| `r2v` | 多参考图视频，可传多张图片 | `veo_3_1_r2v_fast` |

另外，`1080p` / `4k` 当前也是通过独立模型名暴露，而不是仅靠请求参数切换，例如：

- `veo_3_1_t2v_fast_1080p`
- `veo_3_1_t2v_fast_4k`
- `veo_3_1_i2v_s_fast_ultra_fl_1080p`

注意：

- `generationConfig.videoConfig.resolution` 当前只做合法性校验，不负责把基础模型自动切换到 `1080p` / `4k` 版本。
- `generationConfig.videoConfig.aspectRatio` 当前也只是和模型自身横竖屏属性做一致性校验，不负责自动改模型。
- 因此，视频分辨率和横竖屏的主控制项是“模型名本身”。

## 4. 图片接口

### 5.1 请求格式

```http
POST /v1beta/models/{model}:generateContent
```

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "一只戴帽子的猫，水彩风格"
        }
      ]
    }
  ],
  "generationConfig": {
    "imageConfig": {
      "aspectRatio": "1:1",
      "imageSize": "2K"
    }
  }
}
```

### 5.2 当前支持情况

- 支持文本提示词
- 支持在 `contents.parts[].inlineData` 中附带参考图
- 默认比例是 `1:1`
- 图片返回为 Gemini 风格 `inlineData.data` base64

### 5.3 当前不支持或有限支持

- `safetySettings`：直接返回 400
- `generationConfig` 中除 `imageConfig` 之外的大部分字段：
  - `temperature`
  - `topP`
  - `topK`
  - `candidateCount`
  - `maxOutputTokens`
  - `stopSequences`
  - `responseMimeType`
- `responseModalities` 仅允许 `TEXT` / `IMAGE`

### 5.4 响应示例

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "inlineData": {
              "mimeType": "image/png",
              "data": "base64..."
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

### 5.5 curl 示例

```bash
curl -X POST "http://localhost:8000/v1beta/models/gemini-3-pro-image-preview:generateContent" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "一只戴帽子的猫，水彩风格"
          }
        ]
      }
    ],
    "generationConfig": {
      "imageConfig": {
        "aspectRatio": "1:1",
        "imageSize": "2K"
      }
    }
  }'
```

## 5. 视频接口

### 6.1 请求格式

```http
POST /v1beta/models/{local_video_model}:predictLongRunning
```

当前视频请求体已经改成与图片接口一致的 `contents` 格式，而不是官方 Veo 的 `instances` / `parameters` 格式。

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "一只猫在草地上奔跑"
        }
      ]
    }
  ],
  "generationConfig": {
    "videoConfig": {
      "aspectRatio": "16:9",
      "resolution": "1080p"
    }
  }
}
```

如果是图生视频，可在 `parts` 中加入 `inlineData`：

```json
{
  "inlineData": {
    "mimeType": "image/jpeg",
    "data": "base64..."
  }
}
```

### 6.2 当前行为

- 接口名仍叫 `predictLongRunning`
- 但当前实现是同步执行
- 返回体通常直接是：
  - `done: true` + `response.generatedVideos`
  - 或 `done: true` + `error`
- 不需要再调用 `GET /operations/{id}` 轮询

### 6.3 当前限制

- 模型名必须是本地视频模型名，不能再传旧的官方 `veo-*` 别名
- `aspectRatio` 只能是 `16:9` 或 `9:16`
- `resolution` 只能是 `720p`、`1080p`、`4k`
- 这些参数当前主要用于校验，不负责自动选模型
- 文本和图片至少要提供一种

### 6.4 成功响应示例

```json
{
  "name": "operations/1234567890abcdef",
  "done": true,
  "response": {
    "@type": "type.googleapis.com/google.ai.generativelanguage.v1beta.GenerateVideosResponse",
    "generatedVideos": [
      {
        "video": {
          "uri": "https://example.com/video.mp4",
          "mimeType": "video/mp4"
        }
      }
    ]
  }
}
```

### 6.5 失败响应示例

```json
{
  "name": "operations/1234567890abcdef",
  "done": true,
  "error": {
    "code": 500,
    "message": "Video generation failed: ...",
    "status": "INTERNAL"
  }
}
```

### 6.6 curl 示例

```bash
curl -X POST "http://localhost:8000/v1beta/models/veo_3_1_t2v_fast_landscape:predictLongRunning" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "一只猫在草地上奔跑，镜头平稳推进"
          }
        ]
      }
    ],
    "generationConfig": {
      "videoConfig": {
        "aspectRatio": "16:9",
        "resolution": "1080p"
      }
    }
  }'
```

## 6. 模型查询接口说明

### `GET /v1beta/models`

当前返回内容由两部分组成：

- 图片模型：Gemini 风格官方名
- 视频模型：本地 `MODEL_CONFIG` 视频模型名

这意味着返回列表不是“纯官方 Gemini 模型集合”，而是“本项目当前 Gemini 兼容层可调用模型集合”。

### `GET /v1beta/models/{model}`

当前支持：

- 图片：`gemini-2.5-flash-image` 这类 Gemini 名称
- 视频：`veo_3_1_t2v_fast_landscape` 这类本地模型名

## 7. 已知差异与注意事项

### 与官方 Gemini API 的主要差异

1. 图片接口较接近官方，但不是完整实现。
2. 视频接口当前已经不是官方 Veo 原始协议：
   - 不再用官方视频模型名
   - 不再用 `instances` / `parameters`
   - 不再提供轮询查询
3. `/models` 返回的是“兼容层可用模型”，不是“官方 Gemini 全量模型”。

### 调用建议

1. 图片场景优先按本文档中的实际可用比例和尺寸调用，不要只看官方文档。
2. 视频场景先请求 `GET /v1beta/models` 获取当前服务暴露的真实模型名。
3. 如果要选 `1080p` / `4k`，优先直接选择带对应后缀的本地视频模型。

## 8. 推荐的最小心智模型

- 图片：`Gemini 风格模型名 + Gemini 风格请求体`
- 视频：`Flow2API 本地模型名 + Gemini 风格外壳`

如果后续要把视频接口重新对齐官方 Veo 协议，需要同时恢复三部分能力：

- 官方视频模型别名映射
- `instances` / `parameters` 请求结构
- `GET /v1beta/operations/{id}` 异步轮询
