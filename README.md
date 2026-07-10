# OpenClaw Router API - Deployment Package

## Overview

This is a standalone Router API service that implements a cascade routing strategy for LLM model selection.

**Strategy:**
1. XGBoost multiclass classifier predicts model (small/mid/large)
2. If confidence >= 0.5: Direct routing to predicted model
3. If confidence < 0.5: Cascade from predicted model (small → mid → large)

## Files Included

```
deploy/
├── server.py              # Main API server
├── models/
│   └── router_xgboost_epsilon_0.2.pkl  # XGBoost model (3-class)
├── data/
│   └── pca_transformer.pkl             # PCA transformer (384→50 dim)
└── strategist-mvp/
    └── src/                          # Feature extraction utilities
        ├── feature/
        │   ├── __init__.py
        │   ├── extractor.py          # FeatureExtractor class
        │   ├── complexity.py         # ComplexityExtractor
        │   ├── reasoning.py          # ReasoningExtractor
        │   └── semantic.py           # SemanticExtractor
        └── __init__.py
```

## Requirements

- Python 3.8+
- numpy >= 1.24.0
- pandas >= 2.0.0
- scikit-learn >= 1.3.0
- xgboost >= 2.0.0
- sentence-transformers >= 2.2.0

## Installation

```bash
pip install -r requirements.txt
```

## Running the Server

```bash
cd deploy
python server.py
```

Server will run on: `http://localhost:3000`

## API Endpoints

### POST /predict

Get raw prediction (model + confidence + probabilities)

**Request:**
```json
{
  "query": "Your question here"
}
```

**Response:**
```json
{
  "model": "small",
  "confidence": 0.75,
  "probabilities": {
    "small": 0.75,
    "mid": 0.20,
    "large": 0.05
  },
  "features": {
    "token_count": 15,
    "char_count": 85,
    "sentence_count": 1,
    "reasoning_keyword_count": 0
  },
  "strategy": "XGBoost multiclass (small/mid/large)",
  "confidence_threshold": 0.5
}
```

### POST /route

Get cascade-aware routing decision

**Request:**
```json
{
  "query": "Your question here",
  "confidence_threshold": 0.5
}
```

**Response (Direct routing):**
```json
{
  "model": "small",
  "confidence": 0.85,
  "probabilities": {
    "small": 0.85,
    "mid": 0.10,
    "large": 0.05
  },
  "routing_mode": "direct",
  "reason": "Confidence (0.8500) >= threshold (0.5)",
  "features": {...},
  "strategy": "XGBoost + Cascade (confidence_threshold=0.5)"
}
```

**Response (Cascade routing):**
```json
{
  "model": "mid",
  "confidence": 0.60,
  "probabilities": {
    "small": 0.35,
    "mid": 0.60,
    "large": 0.05
  },
  "routing_mode": "cascade",
  "reason": "Confidence (0.3500) < threshold (0.5), escalated to mid",
  "escalation_path": ["small", "mid", "large"],
  "initial_prediction": "small",
  "features": {...},
  "strategy": "XGBoost + Cascade (confidence_threshold=0.5)"
}
```

## Model Mapping

The router returns model tiers:
- `small` → Qwen3.6-Flash
- `mid` → Qwen3.7-Plus
- `large` → Qwen3.7-Max

## Testing with curl

```bash
# Test raw prediction
curl -X POST http://localhost:3000/predict \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain quantum computing"}'

# Test cascade routing
curl -X POST http://localhost:3000/route \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain quantum computing"}'
```

## Benchmark Integration

To integrate with your benchmark framework:

1. Start the Router API server
2. Call `POST http://localhost:3000/route` with the user query
3. Use the returned `model` field to select the target LLM
4. Compare against baselines (Small Only, Mid Only, Large Only)

## Training Data

The model was trained on `train_data_v2.jsonl` (500 records) with:
- 25.8% small-labeled queries
- 34.5% mid-labeled queries
- 40.0% large-labeled queries

## Performance

| Metric | XGBoost + Cascade | Large Only | Mid Only |
|--------|-------------------|------------|----------|
| Accuracy | 57.7% | 63.4% | 45.3% |
| Avg Cost | $44.86 | $72.99 | $14.26 |
| Cost Reduction vs Large | 38.5% | - | - |
