# OpenClaw Router Plugin

智能多模型路由插件，基于 XGBoost + Cascade 策略，根据用户请求的语义、复杂度和推理特征动态选择小/中/大模型。

## 目录结构

```
openclaw-router-plugin/
├── openclaw-plugin.json      # 插件清单
├── package.json              # Node.js 依赖
├── tsconfig.json             # TypeScript 配置
├── src/
│   ├── index.ts              # 插件入口（注册 Provider）
│   └── router-client.ts      # 路由 API 客户端
├── deploy/                   # Python 路由服务
│   ├── server.py             # 路由服务主程序
│   ├── requirements.txt      # Python 依赖
│   ├── models/               # XGBoost 模型文件
│   │   └── router_xgboost_epsilon_0.2.pkl
│   ├── data/                 # 数据预处理模型
│   │   └── pca_transformer.pkl
│   └── strategist-mvp/       # 特征提取模块
│       └── src/feature/      # 复杂度/推理/语义特征提取器
├── mock-router/              # 测试用 Mock 服务
└── example-config.json       # 配置示例
```

## 部署步骤

### 1. 安装到 OpenClaw

将整个插件文件夹复制到 OpenClaw 的 `extensions/` 目录下：

```bash
# 在 OpenClaw 项目根目录执行
cp -r openclaw-router-plugin/ extensions/openclaw-router/
```

### 2. 构建插件

```bash
cd extensions/openclaw-router
npm install
npm run build
```

### 3. 启动路由服务（后端）

路由服务基于 Python Flask，需要先安装依赖：

```bash
cd extensions/openclaw-router/deploy

# 安装 Python 依赖
pip install -r requirements.txt

# 启动路由服务（默认端口 8080）
python server.py
```

服务启动后访问 `http://localhost:8080` 验证是否正常运行。

### 4. 配置 OpenClaw

在 OpenClaw 配置文件 `openclaw.json` 中启用插件：

```json
{
  "plugins": {
    "entries": {
      "openclaw-router": {
        "enabled": true,
        "config": {
          "endpoint": "http://localhost:8080",
          "apiKey": "",
          "models": {
            "small": "qwen3.6-flash",
            "mid": "qwen3.7-plus",
            "large": "qwen3.7-max"
          }
        }
      }
    }
  }
}
```

### 5. 配置模型提供者

确保在 `models.providers` 中配置了对应的模型提供者：

```json
{
  "models": {
    "providers": {
      "qwen": {
        "api": "openai-completions",
        "baseUrl": "https://api.qwenlm.com/v1"
      }
    }
  }
}
```

## 配置说明

| 配置项 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `endpoint` | string | 是 | 路由服务的 URL（不含 `/predict`） |
| `apiKey` | string | 否 | 路由服务的 API Key（可选） |
| `models.small` | string | 是 | 小型模型的 ID |
| `models.mid` | string | 是 | 中型模型的 ID |
| `models.large` | string | 是 | 大型模型的 ID |

## 路由策略

### XGBoost + Cascade

1. **特征提取**：对用户请求提取语义嵌入、复杂度特征（token/char/sentence count）、推理关键词
2. **初始预测**：使用 XGBoost 模型预测最适合的模型，并输出置信度
3. **级联验证**：
   - 置信度 ≥ 0.5：直接使用预测模型
   - 置信度 < 0.5：触发级联模式，从 small → mid → large 逐层验证

## 路由服务 API

### POST /predict

请求体：
```json
{
  "prompt": "用户的请求内容"
}
```

响应：
```json
{
  "model": "small|mid|large",
  "confidence": 0.75,
  "probabilities": {
    "small": 0.1,
    "mid": 0.15,
    "large": 0.75
  },
  "routing_mode": "direct|cascade",
  "features": {
    "complexity": {
      "token_count": 100,
      "char_count": 500,
      "sentence_count": 5
    },
    "reasoning": {
      "reasoning_keyword_count": 2,
      "reasoning_keywords": ["explain", "prove"]
    }
  }
}
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | 路由服务端口 | 8080 |
| `EMBEDDING_MODE` | 嵌入模式（hash/bge） | hash |
| `CONFIDENCE_THRESHOLD` | 置信度阈值 | 0.5 |

## 技术栈

- **前端插件**：TypeScript + OpenClaw Plugin SDK
- **后端服务**：Python Flask
- **路由模型**：XGBoost
- **特征提取**：语义嵌入 + 复杂度 + 推理关键词

## 测试

```bash
# 启动 Mock 服务
npm run start-mock

# 运行测试
npm test
```

## 许可证

MIT