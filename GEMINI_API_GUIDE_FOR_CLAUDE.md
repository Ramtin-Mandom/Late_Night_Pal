# Gemini API Integration Guide for Claude Code

This file gives Claude Code project-specific guidance for integrating the Gemini API into a hackathon application. It is based on the Google AI Studio documentation PDFs provided on November 7, 2026. Google’s SDKs, models, API features, and pricing can change, so check the official links at the end before choosing a model or adding a new API feature.

## Important distinction

Claude Code is the coding assistant. The Gemini API is a service the application can call at runtime. Adding `GEMINI_API_KEY` to the project does not switch Claude Code itself to Gemini. Claude should use this guide to build or update the app so that the app's backend calls Gemini.

If Claude needs current Gemini documentation while coding, use the Gemini documentation MCP server or Gemini Agent Skills described below. That is separate from the app's runtime integration.

## Instructions for Claude Code

Before changing code:

1. Read `AGENTS.md`, `CLAUDE.md`, `architecture.md` (or the repository's equivalent), and the relevant README instructions.
2. Identify the app's language, framework, backend entry point, and existing Gemini or AI integration. Follow the project's current structure instead of creating a second integration.
3. Put Gemini calls in one small service/module for the AI integration component. Keep UI components separate from API calls. Update `architecture.md` after changing component responsibilities or file connections.
4. Use the current Google GenAI SDK and the Interactions API for a new integration unless the existing app has a clear reason to use another supported endpoint. Do not add the deprecated `google-generativeai` Python package or copy old SDK patterns.
5. Keep the implementation focused on the requested feature. For hackathon work, run a focused smoke check and any directly relevant existing checks; do not spend time on a broad test suite unless the task asks for it or the change needs it.
6. Never print, commit, paste into source code, or return the real API key. Do not place it in frontend code, browser bundles, screenshots, logs, or error messages.

## How a request should flow

```text
User interface
    -> application backend / AI service
        -> Google GenAI SDK
            -> Gemini Interactions API
        <- generated result
    <- application response
```

The API key belongs in the backend environment. A React/Vite or other browser client must call the app's backend, not Gemini directly with a private key. Do not name a frontend-exposed variable `VITE_GEMINI_API_KEY`, `NEXT_PUBLIC_GEMINI_API_KEY`, or similar.

## 1. Create and configure the key

Create or view a key in [Google AI Studio API keys](https://aistudio.google.com/app/apikey). A new AI Studio user may get a project and key created automatically. The key authenticates requests; the associated project is used for quotas and billing.

Set the key in the environment as `GEMINI_API_KEY`. The Google GenAI SDKs detect this variable automatically. Keep local secrets in `.env` only if the project already uses dotenv, and ensure `.env` is ignored by Git. Commit a placeholder-only `.env.example`, never the real key.

### Windows PowerShell for the current terminal

```powershell
$env:GEMINI_API_KEY = "YOUR_KEY"
$env:GEMINI_MODEL = "gemini-3.8-flash"
```

For a persistent Windows setting, use Windows Environment Variables and open a new terminal afterward. On macOS/Linux, set `GEMINI_API_KEY` in the shell environment. Avoid putting the key in a command that will be saved in shell history if other people can access that machine.

Set `GEMINI_MODEL` to a model currently available to your AI Studio project. The model name in the examples below reflects the provided docs snapshot; verify it before relying on it.

## 2. Install the SDK

Choose the SDK that matches the app. Do not install both unless the project genuinely uses both languages.

### Python

```bash
pip install -U google-genai
```

### JavaScript / TypeScript

```bash
npm install @google/genai
```

The provided docs identify the Google GenAI SDK as the current SDK family. The Interactions API is supported by Python and JavaScript SDKs as well as REST. Check the current SDK docs for the minimum version before using a newly released Interactions API feature.

## 3. Make a basic request

### Python example

```python
import os

from google import genai


def ask_gemini(prompt: str) -> str:
    client = genai.Client()  # Reads GEMINI_API_KEY from the environment.
    interaction = client.interactions.create(
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        input=prompt,
    )
    return interaction.output_text
```

Install and run a minimal local example:

```bash
pip install -U google-genai
python your_example.py
```

### JavaScript example

```javascript
import { GoogleGenAI } from "@google/genai";

const ai = new GoogleGenAI({}); // Reads GEMINI_API_KEY from the environment.

export async function askGemini(prompt) {
  const interaction = await ai.interactions.create({
    model: process.env.GEMINI_MODEL ?? "gemini-3.8-flash",
    input: prompt,
  });
  return interaction.output_text;
}
```

Call this JavaScript example from a server-side module. Do not import it into browser UI code.

### Direct REST example

Use REST only if the project has a reason not to use an SDK. Keep the key in the environment and send it in the request header:

```bash
curl -X POST "https://generativelanguage.googleapis.com/v1beta/interactions" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.8-flash",
    "input": "Explain how AI works in one sentence."
  }'
```

For the SDK, read the result with `interaction.output_text`. The REST response contains the full Interaction object, including metadata, usage, and steps; use the official response documentation when parsing fields beyond the final text.

## 4. Handle errors and output

- Catch expected API errors in the service layer and return a useful, non-sensitive error to the UI.
- Do not expose raw stack traces, request headers, API keys, or provider internals to users.
- Give the UI a loading state and a clear error state for quota, network, or provider failures.
- Validate generated output before using it for consequential operations or inserting it into a database. Treat model output as untrusted input.
- Keep prompts and response sizes appropriate to the feature; usage is metered and large inputs/outputs can cost more on paid access.
- Use streaming only if the UI benefits from showing partial text. The SDK supports `stream=True`; follow the current event format in the official guide.

## 5. Free use, paid use, and usage checks

The provided pricing guide describes a free tier for getting started, with limited access to certain models and free input/output tokens, and a paid tier for higher limits and production features. Paid access requires Cloud Billing setup. Limits and prices vary by model and may change.

Creating a key does not mean usage is unlimited or that the hackathon has assigned extra credits to the project. Check the project's current limits and usage in Google AI Studio under **Dashboard → Usage**, and check the live pricing page before selecting a model. Avoid enabling paid billing unless the project owner intends to pay.

## 6. Optional: give Claude current Gemini docs

The Gemini docs recommend connecting coding agents to current developer resources because an agent may otherwise suggest deprecated models, SDKs, or patterns.

Options shown in the provided docs:

- Gemini Agent Skills: `npx skills add google-gemini/gemini-skills --skill gemini-api-dev`
- Gemini documentation MCP server: `npx add-mcp "https://gemini-api-docs-mcp.dev"`
- Gemini API CLI for shell use by Claude Code, Cursor, scripts, or CI

Use the skill/MCP when Claude needs to look up current Gemini API documentation. The CLI is a separate shell client; it is not required for an app that already calls Gemini through an SDK.

The provided CLI page shows macOS/Linux installation and example commands:

```bash
curl -fsSL https://raw.githubusercontent.com/google-gemini/gemini-api-cli/main/scripts/install.sh | bash
export GEMINI_API_KEY="YOUR_KEY"
gemini-api analyze -i ./docs/report.pdf "Summarize the key findings in three bullets."
```

Verify the install instructions on the official CLI page before running them. Do not ask Claude to run a remote install script without first reviewing what it will execute.

## 7. Hackathon implementation checklist

- [ ] Read the repository's architecture and instructions before editing.
- [ ] Confirm which backend service should own Gemini calls.
- [ ] Add one backend AI service/module and keep UI code independent.
- [ ] Add `GEMINI_API_KEY` to local environment setup; add only a placeholder to `.env.example`.
- [ ] Add `.env` to `.gitignore` if it is not already ignored.
- [ ] Use the current Google GenAI SDK and a model currently available to the project.
- [ ] Show a useful loading state and handle API errors without exposing secrets.
- [ ] Update architecture/setup docs to match the actual files and environment variables.
- [ ] Run a focused smoke check, not a broad suite by default for a hackathon change.
- [ ] Check AI Studio usage after testing.

## Official references

- [Get an API key](https://aistudio.google.com/app/apikey)
- [Gemini API getting started](https://ai.google.dev/gemini-api/docs/get-started)
- [Using Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Interactions API overview](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [Coding agent setup](https://ai.google.dev/gemini-api/docs/coding-agents)
- [Gemini API CLI](https://ai.google.dev/gemini-api/docs/cli)
