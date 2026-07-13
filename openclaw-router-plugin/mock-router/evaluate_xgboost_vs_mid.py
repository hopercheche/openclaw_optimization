#!/usr/bin/env python3
import json
import os
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(BASE_DIR, "dataset", "train_data_v2.jsonl")
ROUTER_API = "http://localhost:3000/predict"

PRICES = {
    "qwen3.6-flash": {"input": 0.0012, "output": 0.0072},
    "qwen3.7-plus": {"input": 0.002, "output": 0.008},
    "qwen3.7-max": {"input": 0.012, "output": 0.036}
}

MODEL_PRICE_MAP = {
    "small": PRICES["qwen3.6-flash"],
    "mid": PRICES["qwen3.7-plus"],
    "large": PRICES["qwen3.7-max"]
}

def load_data(file_path):
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def get_token_usage(record, model_name):
    outputs = record.get("outputs", {})
    model_key = f"{model_name}_model"
    if model_key in outputs:
        token_usage = outputs[model_key].get("token_usage", {})
        return {
            "input": token_usage.get("input_tokens", 0),
            "output": token_usage.get("output_tokens", 0),
            "total": token_usage.get("total_tokens", 0)
        }
    return {"input": 0, "output": 0, "total": 0}

def calculate_cost(record, model_name):
    token_usage = get_token_usage(record, model_name)
    price = MODEL_PRICE_MAP[model_name]
    return token_usage["input"] * price["input"] + token_usage["output"] * price["output"]

def get_model_name_from_key(key):
    return key.replace("_model", "")

def compare_models(record, model_a, model_b):
    pairs = record.get("pairs", [])
    for p in pairs:
        a = get_model_name_from_key(p["A"])
        b = get_model_name_from_key(p["B"])
        if (a == model_a and b == model_b):
            if p["label"] == "A>B":
                return 1
            elif p["label"] == "B>A":
                return -1
            else:
                return 0
        elif (a == model_b and b == model_a):
            if p["label"] == "A>B":
                return -1
            elif p["label"] == "B>A":
                return 1
            else:
                return 0
    return 0

def evaluate_vs_mid(records, route_func, strategy_name):
    total_records = 0
    wins = 0
    losses = 0
    ties = 0
    total_cost_routed = 0
    total_cost_mid = 0
    
    routing_decisions = {"small": 0, "mid": 0, "large": 0}
    
    for record in records:
        pairs = record.get("pairs", [])
        if not pairs:
            continue
        
        costs = {}
        tokens = {}
        has_data = False
        for m in ["small", "mid", "large"]:
            costs[m] = calculate_cost(record, m)
            tokens[m] = get_token_usage(record, m)["total"]
            if tokens[m] > 0:
                has_data = True
        
        if not has_data:
            continue
        
        total_records += 1
        
        try:
            routed_model = route_func(record)
        except:
            routed_model = "mid"
        
        routing_decisions[routed_model] += 1
        
        total_cost_routed += costs[routed_model]
        total_cost_mid += costs["mid"]
        
        comparison = compare_models(record, routed_model, "mid")
        if comparison > 0:
            wins += 1
        elif comparison < 0:
            losses += 1
        else:
            ties += 1
    
    win_rate = wins / total_records * 100 if total_records > 0 else 0
    loss_rate = losses / total_records * 100 if total_records > 0 else 0
    quality_net = win_rate - loss_rate
    
    cost_ratio = total_cost_routed / total_cost_mid if total_cost_mid > 0 else 0
    cost_savings = (total_cost_mid - total_cost_routed) / total_cost_mid * 100 if total_cost_mid > 0 else 0
    
    return {
        "strategy": strategy_name,
        "total_records": total_records,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "quality_net": quality_net,
        "cost_ratio": cost_ratio,
        "cost_savings": cost_savings,
        "routing_decisions": routing_decisions,
        "total_cost_routed": total_cost_routed,
        "total_cost_mid": total_cost_mid
    }

def print_report(results):
    print("=" * 90)
    print("XGBoost vs Mid Only: STRATEGIC COMPARISON")
    print("=" * 90)
    print()
    
    print(f"{'Strategy':<30} {'Quality Net':<12} {'Cost Savings':<15} {'Small%':<8} {'Mid%':<8} {'Large%':<8} {'Verdict':<12}")
    print("-" * 90)
    
    for r in results:
        small_pct = r["routing_decisions"]["small"] / r["total_records"] * 100 if r["total_records"] > 0 else 0
        mid_pct = r["routing_decisions"]["mid"] / r["total_records"] * 100 if r["total_records"] > 0 else 0
        large_pct = r["routing_decisions"]["large"] / r["total_records"] * 100 if r["total_records"] > 0 else 0
        
        if r["cost_savings"] > 0 and r["quality_net"] >= 0:
            verdict = "✅ BEATS Mid"
        elif r["cost_savings"] > 0 and r["quality_net"] < 0:
            verdict = "⚠️ Trade-off"
        elif r["cost_savings"] < 0 and r["quality_net"] > 0:
            verdict = "📈 Better Quality"
        else:
            verdict = "❌ LOSES to Mid"
        
        print(f"{r['strategy']:<30} {r['quality_net']:<12.1f}% {r['cost_savings']:<15.1f}% {small_pct:<8.1f}% {mid_pct:<8.1f}% {large_pct:<8.1f}% {verdict:<12}")
    
    print()
    
    print("=" * 90)
    print("KEY INSIGHTS")
    print("=" * 90)
    print()
    
    for r in results:
        print(f"  {r['strategy']}:")
        print(f"    - Routes {r['routing_decisions']['small']} queries to small, {r['routing_decisions']['mid']} to mid, {r['routing_decisions']['large']} to large")
        
        if r["strategy"] != "Mid Only":
            small_wins = 0
            small_losses = 0
            mid_wins = 0
            mid_losses = 0
            large_wins = 0
            large_losses = 0
            
            for record in load_data(DATA_PATH):
                pairs = record.get("pairs", [])
                if not pairs:
                    continue
                
                try:
                    routed_model = (lambda r: (lambda x: route_xgboost(x)) if "XGBoost" in r["strategy"] else (lambda x: "mid"))(r)(record)
                except:
                    routed_model = "mid"
                
                comparison = compare_models(record, routed_model, "mid")
                if routed_model == "small":
                    if comparison > 0:
                        small_wins += 1
                    elif comparison < 0:
                        small_losses += 1
                elif routed_model == "large":
                    if comparison > 0:
                        large_wins += 1
                    elif comparison < 0:
                        large_losses += 1
            
            print(f"    - Small vs Mid: {small_wins} wins, {small_losses} losses")
            print(f"    - Large vs Mid: {large_wins} wins, {large_losses} losses")
    
    print()
    
    print("=" * 90)
    print("STRATEGIC RECOMMENDATIONS")
    print("=" * 90)
    print()
    
    print("  To beat Mid Only, your router needs to:")
    print("  1. Route more queries to small WITHOUT losing quality")
    print("  2. Route fewer queries to large (it's expensive!)")
    print("  3. Learn to distinguish 'small-sufficient' vs 'mid-required' queries")
    print()
    
    print("  Current limitations:")
    print("  - Only 133 training samples")
    print("  - Too few 'small' labeled samples (47/133 = 35%)")
    print("  - Conservative epsilon (0.1) means most queries labeled as mid")
    print()
    
    print("  Recommended improvements:")
    print("  1. Increase training data to 500-1000 samples")
    print("  2. Use larger epsilon (0.2-0.3) in cost-aware labeling")
    print("  3. Add discriminative features (query type, difficulty)")
    print("  4. Try two-stage routing: first decide 'need large?', then 'small vs mid'")

if __name__ == "__main__":
    print(f"Loading data from {DATA_PATH}...")
    records = load_data(DATA_PATH)
    print(f"Loaded {len(records)} records")
    print()
    
    results = []
    
    def route_xgboost(record):
        try:
            response = requests.post(ROUTER_API, json={"query": record["query"]}, timeout=5)
            result = response.json()
            model = result.get("model", "").lower()
            if model not in ["small", "mid", "large"]:
                return "mid"
            return model
        except:
            return "mid"
    
    results.append(evaluate_vs_mid(records, route_xgboost, "XGBoost (Raw)"))
    
    for threshold in [0.4, 0.45, 0.5, 0.55, 0.6]:
        def route_with_threshold(record, t=threshold):
            try:
                response = requests.post(ROUTER_API, json={"query": record["query"]}, timeout=5)
                result = response.json()
                model = result.get("model", "").lower()
                confidence = result.get("confidence", 0)
                
                if model in ["small", "mid"] and confidence >= t:
                    return model
                return "large"
            except:
                return "mid"
        
        results.append(evaluate_vs_mid(records, route_with_threshold, f"XGBoost (threshold={threshold})"))
    
    def route_mid_only(record):
        return "mid"
    
    results.append(evaluate_vs_mid(records, route_mid_only, "Mid Only"))
    
    def route_small_only(record):
        return "small"
    
    results.append(evaluate_vs_mid(records, route_small_only, "Small Only"))
    
    def route_large_only(record):
        return "large"
    
    results.append(evaluate_vs_mid(records, route_large_only, "Large Only"))
    
    print_report(results)
    
    output_path = os.path.join(BASE_DIR, "router", "xgboost_vs_mid.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_path}")