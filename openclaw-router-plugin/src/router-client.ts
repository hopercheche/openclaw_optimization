export type RouterDecision = {
  model: "small" | "mid" | "large";
  confidence?: number;
  routingMode?: "direct" | "cascade";
  probabilities?: Record<string, number>;
};

export class RouterClient {
  private readonly endpoint: string;
  private readonly apiKey?: string;

  constructor(endpoint: string, apiKey?: string) {
    this.endpoint = endpoint.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  async predict(prompt: string): Promise<RouterDecision> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (this.apiKey) {
      headers["Authorization"] = `Bearer ${this.apiKey}`;
    }

    const response = await fetch(`${this.endpoint}/route`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        query: prompt,
        confidence_threshold: 0.5,
      }),
    });

    if (!response.ok) {
      throw new Error(`Router API request failed: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();

    if (!data || typeof data.model !== "string") {
      throw new Error("Invalid router response: missing 'model' field");
    }

    const model = data.model.toLowerCase();
    if (model !== "small" && model !== "mid" && model !== "large") {
      throw new Error(`Invalid model tier: ${model}. Must be 'small', 'mid', or 'large'`);
    }

    return {
      model: model as RouterDecision["model"],
      confidence: typeof data.confidence === "number" ? data.confidence : undefined,
      routingMode: (data.routing_mode as RouterDecision["routingMode"]) || undefined,
      probabilities: typeof data.probabilities === "object" ? data.probabilities : undefined,
    };
  }
}