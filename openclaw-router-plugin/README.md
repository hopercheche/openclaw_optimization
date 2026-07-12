# OpenClaw LLM Router Plugin

A plugin for OpenClaw that routes LLM requests to different model tiers (small/mid/large) based on an external Router API.

## Features

- Routes user requests to appropriate model based on external Router API decision
- Supports three model tiers: small, mid, large
- Configurable model mappings
- Graceful fallback when router API fails
- Preserves OpenClaw's native streaming response mechanism

## Architecture

```
User Query
    ↓
OpenClaw Agent
    ↓
wrapStreamFn Hook (Router Plugin)
    ↓
Router Client → POST /predict { query: "..." }
    ↓
Router API Response → { model: "small/mid/large" }
    ↓
Model Override → small/mid/large model
    ↓
Response (streaming)
```

## Installation

### Option 1: Install from local directory

```bash
cd openclaw-router-plugin
npm install
npm run build
openclaw plugins install /path/to/openclaw-router-plugin
```

### Option 2: Install from GitHub

```bash
openclaw plugins install git+https://github.com/your-username/openclaw-router-plugin.git
```

### Option 3: Install from npm

```bash
openclaw plugins install openclaw-router-plugin
```

## Configuration

Add the following configuration to your `openclaw.json`:

```json
{
  "models": {
    "providers": {
      "openclaw-router": {
        "endpoint": "https://your-router-api.com",
        "apiKey": "your-api-key",
        "models": {
          "small": "openai/gpt-4o-mini",
          "mid": "openai/gpt-4o",
          "large": "openai/gpt-4o-turbo"
        }
      }
    }
  }
}
```

### Configuration Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `endpoint` | string | Yes | URL of the external Router API (without `/predict`) |
| `apiKey` | string | No | API key for authentication (Bearer token) |
| `models.small` | string | Yes | Model ID for small tier routing |
| `models.mid` | string | Yes | Model ID for mid tier routing |
| `models.large` | string | Yes | Model ID for large tier routing |

## Router API Specification

The external Router API must accept a POST request with the following format:

**Request:**
```json
POST /predict
Content-Type: application/json

{
  "query": "user prompt text"
}
```

**Response:**
```json
{
  "model": "small" | "mid" | "large"
}
```

## Development

### Build

```bash
npm install
npm run build
```

### Watch

```bash
npm run watch
```

### Run Mock Router API

```bash
npm run start-mock
```

### Test Router Client

1. Start the mock router first:
```bash
npm run start-mock
```

2. In another terminal, run the test:
```bash
npm test
```

## Usage

Once installed and configured, the plugin will automatically:

1. Wrap the LLM stream function
2. Extract the user's prompt from the context
3. Call the external Router API
4. Override the model based on the router's decision
5. Fall back to original model if the router API fails

## License

MIT