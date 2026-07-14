export type RouterDecision = {
  model: "small" | "mid" | "large";
  confidence?: number;
  routingMode?: "direct" | "cascade";
  probabilities?: Record<string, number>;
};

export type RouterRequestContext = {
  confidenceThreshold: number;
  evalSampleId?: string;
  requestId: string;
};

export class RouterClient {
  private readonly endpoint: string;
  private readonly apiKey?: string;
  private readonly timeoutMs: number;

  constructor(endpoint: string, apiKey?: string, timeoutMs = 5000) {
    this.endpoint = endpoint.replace(/\/$/, "");
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  async predict(prompt: string, context: RouterRequestContext): Promise<RouterDecision> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (this.apiKey) {
      headers["Authorization"] = `Bearer ${this.apiKey}`;
    }

    const response = await fetch(`${this.endpoint}/route`, {
      method: "POST",
      headers,
      signal: AbortSignal.timeout(this.timeoutMs),
      body: JSON.stringify({
        query: prompt,
        confidence_threshold: context.confidenceThreshold,
        request_id: context.requestId,
        eval_sample_id: context.evalSampleId,
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
