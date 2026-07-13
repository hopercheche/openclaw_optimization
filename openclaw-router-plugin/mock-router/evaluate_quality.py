import json
import os
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(BASE_DIR, "dataset", "train_data.jsonl")
ROUTER_API = "http://localhost:3000/predict"

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
        return token_usage.get("total_tokens", 0)
    return 0

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

def evaluate_quality_and_cost(records, route_func, strategy_name):
    total_records = 0
    quality_wins = 0
    quality_losses = 0
    quality_ties = 0
    total_tokens_routed = 0
    total_tokens_large = 0
    
    for record in records:
        pairs = record.get("pairs", [])
        if not pairs:
            continue
        
        small_tokens = get_token_usage(record, "small")
        mid_tokens = get_token_usage(record, "mid")
        large_tokens = get_token_usage(record, "large")
        
        if small_tokens == 0 and mid_tokens == 0 and large_tokens == 0:
            continue
        
        total_records += 1
        
        try:
            routed_model = route_func(record)
        except:
            routed_model = "large"
        
        tokens = {"small": small_tokens, "mid": mid_tokens, "large": large_tokens}
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
    quality_tie_rate = quality_ties / total_records * 100 if total_records > 0 else 0
    
    token_ratio = total_tokens_routed / total_tokens_large if total_tokens_large > 0 else 0
    token_savings = (total_tokens_large - total_tokens_routed) / total_tokens_large * 100 if total_tokens_large > 0 else 0
    
    return {
        "strategy": strategy_name,
        "total_records": total_records,
        "quality_wins": quality_wins,
        "quality_losses": quality_losses,
        "quality_ties": quality_ties,
        "quality_win_rate": quality_win_rate,
        "quality_loss_rate": quality_loss_rate,
        "quality_tie_rate": quality_tie_rate,
        "total_tokens_routed": total_tokens_routed,
        "total_tokens_large": total_tokens_large,
        "token_ratio": token_ratio,
        "token_savings": token_savings
    }

def print_report(results):
    print("=" * 90)
    print("ROUTING STRATEGY COMPARISON (QUALITY vs COST)")
    print("=" * 90)
    print()
    
    print(f"{'Strategy':<25} {'Win Rate':<12} {'Loss Rate':<12} {'Tie Rate':<12} {'Token Ratio':<12} {'Token Savings':<15}")
    print("-" * 90)
    
    for r in results:
        print(f"{r['strategy']:<25} {r['quality_win_rate']:<12.2f}% {r['quality_loss_rate']:<12.2f}% {r['quality_tie_rate']:<12.2f}% {r['token_ratio']:<12.2f}x {r['token_savings']:<15.2f}%")
    
    print()
    
    print("=" * 90)
    print("INTERPRETATION")
    print("=" * 90)
    print()
    print("Win Rate: % of queries where routed model > large model quality")
    print("Loss Rate: % of queries where routed model < large model quality")
    print("Tie Rate: % of queries where routed model = large model quality")
    print("Token Ratio: routed tokens / large-only tokens (lower = better)")
    print("Token Savings: % reduction vs large-only (higher = better)")
    print()
    
    print("=" * 90)
    print("SCORE CARD")
    print("=" * 90)
    print()
    
    for r in results:
        quality_score = r['quality_win_rate'] - r['quality_loss_rate']
        cost_score = -r['token_ratio'] * 100
        combined_score = quality_score + cost_score * 0.1
        
        print(f"{r['strategy']:<25}")
        print(f"  Quality Score: {quality_score:+.2f} (wins - losses)")
        print(f"  Cost Score: {cost_score:+.2f} (-100 × token_ratio)")
        print(f"  Combined Score: {combined_score:+.2f}")
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
    
    results.append(evaluate_quality_and_cost(records, route_xgboost, "XGBoost (Raw)"))
    
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
        
        results.append(evaluate_quality_and_cost(records, route_with_threshold, f"XGBoost (threshold={threshold})"))
    
    def route_large_only(record):
        return "large"
    
    results.append(evaluate_quality_and_cost(records, route_large_only, "Large Only"))
    
    def route_mid_only(record):
        return "mid"
    
    results.append(evaluate_quality_and_cost(records, route_mid_only, "Mid Only"))
    
    print_report(results)
    
    output_path = os.path.join(BASE_DIR, "router", "quality_comparison.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_path}")