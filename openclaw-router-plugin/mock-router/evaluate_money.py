import json
import os
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(BASE_DIR, "dataset", "train_data.jsonl")
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

def evaluate(records, route_func, strategy_name):
    total_records = 0
    quality_wins = 0
    quality_losses = 0
    quality_ties = 0
    total_cost_routed = 0
    total_cost_large = 0
    total_tokens_routed = 0
    total_tokens_large = 0
    
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
            routed_model = "large"
        
        total_cost_routed += costs[routed_model]
        total_cost_large += costs["large"]
        total_tokens_routed += tokens[routed_model]
        total_tokens_large += tokens["large"]
        
        comparison = compare_models(record, routed_model, "large")
        if comparison > 0:
            quality_wins += 1
        elif comparison < 0:
            quality_losses += 1
        else:
            quality_ties += 1
    
    quality_win_rate = quality_wins / total_records * 100 if total_records > 0 else 0
    quality_loss_rate = quality_losses / total_records * 100 if total_records > 0 else 0
    quality_net = quality_win_rate - quality_loss_rate
    
    cost_ratio = total_cost_routed / total_cost_large if total_cost_large > 0 else 0
    cost_savings = (total_cost_large - total_cost_routed) / total_cost_large * 100 if total_cost_large > 0 else 0
    
    token_ratio = total_tokens_routed / total_tokens_large if total_tokens_large > 0 else 0
    token_savings = (total_tokens_large - total_tokens_routed) / total_tokens_large * 100 if total_tokens_large > 0 else 0
    
    return {
        "strategy": strategy_name,
        "total_records": total_records,
        "quality_wins": quality_wins,
        "quality_losses": quality_losses,
        "quality_net": quality_net,
        "cost_ratio": cost_ratio,
        "cost_savings": cost_savings,
        "token_ratio": token_ratio,
        "token_savings": token_savings,
        "total_cost_routed": total_cost_routed,
        "total_cost_large": total_cost_large
    }

def print_report(results):
    print("=" * 90)
    print("ROUTING STRATEGY COMPARISON (MONETARY COST)")
    print("=" * 90)
    print()
    
    print("Price Configuration:")
    print(f"  small (qwen3.6-flash): ${PRICES['qwen3.6-flash']['input']}/1k input, ${PRICES['qwen3.6-flash']['output']}/1k output")
    print(f"  mid (qwen3.7-plus): ${PRICES['qwen3.7-plus']['input']}/1k input, ${PRICES['qwen3.7-plus']['output']}/1k output")
    print(f"  large (qwen3.7-max): ${PRICES['qwen3.7-max']['input']}/1k input, ${PRICES['qwen3.7-max']['output']}/1k output")
    print()
    
    print(f"{'Strategy':<25} {'Quality Net':<12} {'Cost Ratio':<12} {'Cost Savings':<15} {'Token Ratio':<12}")
    print("-" * 80)
    
    for r in results:
        print(f"{r['strategy']:<25} {r['quality_net']:<12.2f}% {r['cost_ratio']:<12.2f}x {r['cost_savings']:<15.2f}% {r['token_ratio']:<12.2f}x")
    
    print()
    
    print("=" * 90)
    print("DOLLAR SAVINGS DETAILS")
    print("=" * 90)
    print()
    
    print(f"{'Strategy':<25} {'Total Cost':<15} {'Cost vs Large'}")
    print("-" * 55)
    
    for r in results:
        diff = r["total_cost_routed"] - r["total_cost_large"]
        sign = "+" if diff > 0 else ""
        print(f"{r['strategy']:<25} ${r['total_cost_routed']:<15.2f} {sign}${diff:.2f}")
    
    print()
    
    print("=" * 90)
    print("STRATEGY RECOMMENDATION")
    print("=" * 90)
    print()
    
    for r in results:
        if r['cost_savings'] > 0 and r['quality_net'] >= 0:
            print(f"✅ {r['strategy']}: Saves {r['cost_savings']:.1f}% cost with {r['quality_net']:.1f}% quality gain")
        elif r['cost_savings'] > 0 and r['quality_net'] < 0:
            print(f"⚠️ {r['strategy']}: Saves {r['cost_savings']:.1f}% cost but loses {abs(r['quality_net']):.1f}% quality")
        elif r['cost_savings'] < 0 and r['quality_net'] > 0:
            print(f"📈 {r['strategy']}: Costs {abs(r['cost_savings']):.1f}% more but gains {r['quality_net']:.1f}% quality")
        else:
            print(f"❌ {r['strategy']}: Costs {abs(r['cost_savings']):.1f}% more with {abs(r['quality_net']):.1f}% quality loss")
    print()

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
    
    results.append(evaluate(records, route_xgboost, "XGBoost (Raw)"))
    
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
                return "large"
        
        results.append(evaluate(records, route_with_threshold, f"XGBoost (threshold={threshold})"))
    
    def route_large_only(record):
        return "large"
    
    results.append(evaluate(records, route_large_only, "Large Only"))
    
    def route_mid_only(record):
        return "mid"
    
    results.append(evaluate(records, route_mid_only, "Mid Only"))
    
    def route_small_only(record):
        return "small"
    
    results.append(evaluate(records, route_small_only, "Small Only"))
    
    print_report(results)
    
    output_path = os.path.join(BASE_DIR, "router", "money_comparison.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_path}")