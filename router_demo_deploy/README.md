# OpenClaw Router Demo - 部署说明

## 项目简介

OpenClaw Router Demo 是一个用于展示智能模型路由系统的 Web 演示应用。

## 文件结构

```
router_demo_deploy/
├── app.py                    # Flask 应用主文件
├── requirements.txt          # Python 依赖
├── start.sh                  # 启动脚本（Linux/macOS）
├── templates/
│   └── index.html            # 前端页面
├── models/
│   ├── router_xgboost_epsilon_0.2.pkl  # XGBoost 路由模型
│   └── pca_transformer.pkl            # PCA 降维模型
└── src/
    └── feature/
        ├── __init__.py
        ├── extractor.py      # 特征提取器
        ├── complexity.py     # 复杂度特征
        ├── reasoning.py      # 推理特征
        ├── semantic.py       # 语义特征
        └── keywords.py       # 关键词列表
```

## 快速启动

### 方式一：使用启动脚本（推荐）

```bash
chmod +x start.sh
./start.sh
```

### 方式二：手动启动

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python app.py
```

服务启动后，访问 http://localhost:8080

## 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| PORT | 8080 | 服务监听端口 |
| DEBUG | false | 是否开启调试模式 |
| EMBEDDING_MODE | hash | 嵌入模型模式（hash/bge/auto） |

## 使用 Docker 部署（可选）

创建 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
```

构建并运行：

```bash
docker build -t router-demo .
docker run -p 8080:8080 router-demo
```

## 使用 Gunicorn 部署生产环境

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8080 app:app
```

## API 接口

### 1. 路由决策

```
POST /api/route
Content-Type: application/json

{
  "query": "你的问题"
}
```

### 2. 特征提取

```
POST /api/features
Content-Type: application/json

{
  "query": "你的问题"
}
```

### 3. 健康检查

```
GET /health
```

## 功能说明

- **智能路由**：基于 XGBoost 模型自动选择最优模型（small/mid/large）
- **特征可视化**：展示复杂度、推理、语义等特征
- **级联策略**：低置信度时自动升级模型
- **置信度展示**：显示各模型的选择概率
- **模型信息**：展示模型名称、价格等信息

## 注意事项

1. 默认使用 `hash` 模式生成嵌入向量，无需下载模型
2. 如需更高质量的嵌入，设置 `EMBEDDING_MODE=bge`（需下载模型）
3. 模型文件较大，确保服务器有足够磁盘空间
4. 生产环境建议使用 Gunicorn 或 uWSGI

## 故障排查

### 端口被占用
```bash
lsof -ti:8080 | xargs kill -9
```

### 依赖安装失败
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 模型加载失败
检查 `models/` 目录下是否存在以下文件：
- `router_xgboost_epsilon_0.2.pkl`
- `pca_transformer.pkl`