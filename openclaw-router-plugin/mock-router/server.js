import http from "http";

const PORT = 3000;

function decideModel(query) {
  if (!query || typeof query !== "string") {
    return "small";
  }

  const length = query.length;
  
  if (length > 150) {
    return "large";
  } else if (length > 50) {
    return "mid";
  } else {
    return "small";
  }
}

const server = http.createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  if (req.method !== "POST") {
    res.writeHead(405, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Method not allowed" }));
    return;
  }

  let body = "";
  req.on("data", (chunk) => {
    body += chunk.toString();
  });

  req.on("end", () => {
    try {
      const data = JSON.parse(body);
      const query = data.query || "";
      const model = decideModel(query);

      console.log(`[Mock Router] Query: "${query.substring(0, 50)}${query.length > 50 ? "..." : ""}" (length: ${query.length}) -> Model: ${model}`);

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ model }));
    } catch (error) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Invalid request body" }));
    }
  });
});

server.listen(PORT, () => {
  console.log(`Mock Router API running on http://localhost:${PORT}`);
  console.log("Routes:");
  console.log("  POST /predict - Route LLM requests");
  console.log("");
  console.log("Routing rules:");
  console.log("  Query length > 150 chars -> large");
  console.log("  Query length 50-150 chars -> mid");
  console.log("  Query length < 50 chars -> small");
});