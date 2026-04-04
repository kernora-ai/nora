# Acknowledgements

Nora is built on the shoulders of these open source projects and frameworks.
We are grateful to their maintainers and contributors.

---

## Python Dependencies

| Project | License | Used For |
|---------|---------|----------|
| [Flask](https://flask.palletsprojects.com/) | BSD-3-Clause | Dashboard web server (localhost:2742) |
| [LiteLLM](https://github.com/BerriAI/litellm) | MIT | Multi-provider LLM abstraction (Anthropic, Bedrock, OpenAI, Google, Ollama) |
| [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | Model Context Protocol server for IDE tool integration |
| [Hypothesis](https://hypothesis.readthedocs.io/) | MPL-2.0 | Property-based testing framework |
| [pytest](https://pytest.org/) | MIT | Test runner |

## Swift Dependencies

| Project | License | Used For |
|---------|---------|----------|
| [MLX Swift LM](https://github.com/ml-explore/mlx-swift-lm) | MIT | On-device LLM inference via Apple MLX framework |
| [MLX](https://github.com/ml-explore/mlx) | MIT | Apple's machine learning framework for Apple Silicon |

## Models

| Model | Provider | License | Used For |
|-------|----------|---------|----------|
| Apple FoundationModels (~3B) | Apple | Ships with macOS 26 | On-device session analysis (zero download) |
| [Qwen2.5-Coder-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct) | Alibaba/Qwen | Apache-2.0 | MLX-LM fallback for session analysis |

## Frameworks & Platforms

| Framework | Provider | Used For |
|-----------|----------|----------|
| [VS Code Extension API](https://code.visualstudio.com/api) | Microsoft | Extension host for Kiro, VS Code, Cursor |
| [HTMX](https://htmx.org/) | htmx.org (BSD-2-Clause) | Dashboard partial page updates |
| [SQLite](https://sqlite.org/) | Public Domain | Local session database (echo.db) |
| [Apple FoundationModels](https://developer.apple.com/documentation/foundationmodels) | Apple | On-device structured LLM inference |
| [Apple Network Framework](https://developer.apple.com/documentation/network) | Apple | Local HTTP server (NWListener) |

## Cloud Infrastructure (Team Mode)

| Service | Provider | Used For |
|---------|----------|----------|
| [AWS CDK](https://aws.amazon.com/cdk/) | Amazon | Infrastructure as code for team backend |
| [AWS Lambda](https://aws.amazon.com/lambda/) | Amazon | Serverless ingestion and analytics |
| [AWS S3](https://aws.amazon.com/s3/) | Amazon | Customer-controlled team data storage |
| [Litestream](https://litestream.io/) | Ben Johnson (Apache-2.0) | SQLite WAL streaming to S3 |
| [Cloudflare Workers](https://workers.cloudflare.com/) | Cloudflare | Telemetry endpoint |

## Research & Inspiration

| Source | Attribution |
|--------|------------|
| [Foundation Capital — "Context Graphs: AI's Trillion-Dollar Opportunity"](https://foundationcapital.com/ideas/context-graphs-ais-trillion-dollar-opportunity) | Ashu Garg & Jaya Gupta. Informed our context graph and decision trace architecture. |
| [METR Randomized Controlled Trial on AI Developer Productivity (2025)](https://metr.org/) | Informed our AI Leverage Score methodology and executive business case. |
| [DORA Metrics](https://dora.dev/) | Inspired our approach to standardizing AI effectiveness measurement. |

---

*If we've missed attributing your project, please let us know at hello@kernora.ai.*
