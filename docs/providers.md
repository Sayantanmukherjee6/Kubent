# LLM Providers

## Overview

Providers wrap LLM API calls and return structured `AnalysisResult` dataclasses. Swap backends by changing one env var.

## Interface

```python
class BaseLlmProvider(ABC):
    async def analyze(self, log_context: str) -> AnalysisResult: ...
```

## Implementations

### LlamaCppProvider (`src/providers/llama_cpp.py`)

Communicates with a local llama.cpp server via OpenAI-compatible API.

**Setup:**
```bash
llama-server --model ./models/your-model.gguf --host 127.0.0.1 --port 8080 --ctx-size 4096
```

**.env:**
```env
LLM_PROVIDER=llama_cpp
LLAMA_CPP_BASE_URL=http://localhost:8080/v1
LLAMA_CPP_MODEL_NAME=./models/your-model.gguf
```

**Recommended models:** Mistral 7B Instruct, Llama 3 8B Instruct, Phi-3 Mini.

### OpenAiProvider (`src/providers/openai.py`)

Sends requests to OpenAI API or any OpenAI-compatible endpoint (vLLM, Ollama, Together AI).

**.env:**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL_NAME=gpt-4o
```

**Other endpoints example:**
```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.together.xyz/v1
OPENAI_MODEL_NAME=mistralai/Mixtral-8x7B-Instruct-v0.1
OPENAI_API_KEY=your-together-api-key
```

## Factory

`create_llm_provider(settings)` in `src/providers/factory.py` instantiates the correct provider based on `LLM_PROVIDER`.

## Request Flow

1. Logs are sent as a `user` message in a chat completion request.
2. A system prompt instructs the model to return structured JSON with: `root_cause`, `severity` (critical/high/medium/low), `remediation_suggestions`, `preventive_actions`.
3. The provider parses JSON and returns an `AnalysisResult` dataclass.
