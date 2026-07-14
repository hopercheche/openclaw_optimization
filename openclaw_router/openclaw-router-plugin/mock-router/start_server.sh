#!/bin/bash
set -e

echo "Starting OpenClaw Router API..."
echo "=============================="

if [ ! -f "server.py" ]; then
    echo "Error: server.py not found"
    exit 1
fi

if [ ! -f "../../models/router_xgboost_epsilon_0.2.pkl" ]; then
    echo "Error: Model file not found at ../../models/router_xgboost_epsilon_0.2.pkl"
    exit 1
fi

if [ ! -f "../../router/data/pca_transformer.pkl" ]; then
    echo "Error: PCA file not found at ../../router/data/pca_transformer.pkl"
    exit 1
fi

echo "Dependencies:"
echo "- Python 3.8+"
echo "- numpy, pandas, scikit-learn, xgboost, sentence-transformers"
echo ""
echo "Starting server on http://localhost:3000..."
echo ""

python3 server.py
