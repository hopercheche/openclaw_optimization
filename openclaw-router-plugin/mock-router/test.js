class RouterClient {
  constructor(endpoint, apiKey) {
    this.endpoint = endpoint.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  async predict(prompt) {
    const headers = {
      "Content-Type": "application/json",
    };

    if (this.apiKey) {
      headers["Authorization"] = `Bearer ${this.apiKey}`;
    }

    const response = await fetch(`${this.endpoint}/predict`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        query: prompt,
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
      model,
      confidence: data.confidence,
      probabilities: data.probabilities,
      features: data.features,
    };
  }
}

function toFixed(val, digits) {
  if (val === undefined || val === null) return "N/A";
  return Number(val).toFixed(digits);
}

async function testRouterClient() {
  console.log("Testing Router Client with REAL XGBoost Router API...\n");

  const client = new RouterClient("http://localhost:3000", "test-api-key");

  const testCases = [
    {
      name: "Simple fact question",
      query: "北京是中国的首都吗？",
    },
    {
      name: "Explaining a concept",
      query: "解释一下Transformer为什么有效",
    },
    {
      name: "Complex technical question",
      query: "请详细解释Transformer架构的核心原理，包括自注意力机制、编码器-解码器结构、位置编码的作用，以及残差连接和层归一化的重要性。同时说明为什么Transformer在自然语言处理任务中表现出色，相比传统的RNN和CNN模型有哪些优势。",
    },
    {
      name: "Math reasoning",
      query: "一个水池有两个进水管和一个出水管。单开甲管6小时注满，单开乙管4小时注满，单开丙管3小时放完。三管同时打开，几小时注满水池？",
    },
    {
      name: "Creative writing",
      query: "写一段关于未来城市的科幻短文，描述人工智能如何改变人们的日常生活，以及可能带来的社会问题。",
    },
    {
      name: "Code generation",
      query: "用Python写一个快速排序算法，要求有详细的注释和时间复杂度分析。",
    },
    {
      name: "Deep analysis",
      query: "分析GPT-4相比GPT-3.5在技术架构上的主要改进，包括模型规模、训练数据、推理机制、上下文窗口等方面的变化，并评估这些改进对实际应用场景的影响。",
    },
    {
      name: "Multi-step reasoning",
      query: "假设你有100元人民币，去超市买水果。苹果每斤5元，香蕉每斤3元，橙子每斤4元。你想买2斤苹果，3斤香蕉，剩下的钱全部买橙子，请问能买多少斤橙子？",
    },
  ];

  console.log("=" .repeat(80));
  console.log("Test Results (Real XGBoost Model)");
  console.log("=" .repeat(80));
  console.log();

  for (const testCase of testCases) {
    console.log(`Test: ${testCase.name}`);
    console.log(`Query: "${testCase.query.substring(0, 60)}${testCase.query.length > 60 ? "..." : ""}"`);

    try {
      const result = await client.predict(testCase.query);
      
      console.log(`Model: ${result.model.toUpperCase()}`);
      console.log(`Confidence: ${toFixed(result.confidence, 4)}`);
      
      if (result.probabilities) {
        console.log(`Probabilities: small=${toFixed(result.probabilities.small, 4)}, mid=${toFixed(result.probabilities.mid, 4)}, large=${toFixed(result.probabilities.large, 4)}`);
      }
      
      if (result.features) {
        console.log(`Features: tokens=${result.features.token_count}, chars=${result.features.char_count}, sentences=${result.features.sentence_count}, reasoning_keywords=${result.features.reasoning_keyword_count}`);
      }
      
      console.log("✓ SUCCESS");
    } catch (error) {
      console.log(`✗ ERROR: ${error.message}`);
    }
    console.log("-" .repeat(60));
  }

  console.log("=" .repeat(80));
  console.log("All tests completed!");
  console.log("=" .repeat(80));
}

testRouterClient();