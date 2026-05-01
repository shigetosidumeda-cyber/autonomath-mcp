# Token pricing research note

Date: 2026-04-30

Scope: current public input-token and web-search/tool pricing signals for OpenAI, Anthropic Claude, and Google Gemini. Sources are official pricing/docs pages only. Prices below are public list prices observed on 2026-04-30 and should not be treated as durable configuration.

## Practical conclusion

jpcite should not hard-code provider prices in production code. Provider cost is now a function of provider, model, route or processing mode, context length, cache state, modality, tool version, server-side tool behavior, and sometimes geography. Treat pricing as data with source URL, retrieval date, effective date if known, and confidence. Runtime cost estimation should use configurable provider price tables or provider-reported usage and billing exports where available.

## OpenAI

Official source: https://developers.openai.com/api/docs/pricing

Signals observed:

- OpenAI lists flagship prices per 1M tokens with distinct standard, batch, flex, and priority processing modes.
- Example standard flagship input pricing: `gpt-5.5` is listed at `$5.00 / 1M` short-context input tokens and `$10.00 / 1M` long-context input tokens; `gpt-5.4` is listed at `$2.50 / 1M` short-context and `$5.00 / 1M` long-context input tokens.
- Batch and Flex show lower input prices for the same models. Priority shows higher input prices.
- OpenAI notes a 10% uplift for regional processing/data residency endpoints for listed GPT-5.4/GPT-5.5 model families.
- Web search has separate tool-call pricing plus search-content token pricing: web search is listed at `$10.00 / 1k calls` for all models, web search preview is `$10.00 / 1k calls` for reasoning models, and web search preview is `$25.00 / 1k calls` for non-reasoning models.
- OpenAI states web search content tokens are billed at model rates, except `gpt-4o-mini` and `gpt-4.1-mini` with the non-preview web search tool, where search content tokens are billed as a fixed 8,000 input-token block per call.

Implication: a hard-coded OpenAI “input price” misses context length, processing mode, model version, regional processing, cached input, and search-tool adders.

## Anthropic Claude

Official source: https://platform.claude.com/docs/en/about-claude/pricing

Signals observed:

- Anthropic lists prices per MTok with separate columns for base input, 5-minute cache writes, 1-hour cache writes, cache hits/refreshes, and output.
- Example base input pricing: Claude Opus 4.7/4.6/4.5 are listed at `$5 / MTok`; Claude Opus 4.1/4 are `$15 / MTok`; Claude Sonnet 4.6/4.5/4/3.7 are `$3 / MTok`; Claude Haiku 4.5 is `$1 / MTok`; Claude Haiku 3.5 is `$0.80 / MTok`; Claude Haiku 3 is `$0.25 / MTok`.
- Prompt caching uses multipliers relative to base input pricing: 5-minute cache writes are 1.25x, 1-hour cache writes are 2x, and cache reads are 0.1x.
- Anthropic states Opus 4.7 uses a new tokenizer that may use up to 35% more tokens for the same fixed text.
- Data residency can apply a 1.1x multiplier for Claude Opus 4.7, Claude Opus 4.6, and newer models when US-only inference is specified.
- Fast mode for Claude Opus 4.6 has premium pricing, listed as `$30 / MTok` input and `$150 / MTok` output, and stacks with other pricing modifiers.
- Tool-use requests include normal input and output tokens, tool definitions and results, Anthropic-added tool system-prompt tokens, and possible server-side usage pricing.
- Web search is listed at `$10 / 1,000 searches` plus standard token costs for search-generated content. Web fetch has no additional charge beyond standard token costs for fetched content.

Implication: Anthropic cost depends not only on model but also on cache operation, data residency, fast mode, tokenizer changes, tool prompt overhead, and server-side tool usage.

## Google Gemini

Official sources:

- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/google-search

Signals observed:

- Google lists Gemini API prices per 1M tokens in USD, but the exact rate varies by model, paid/free tier, standard/batch/flex/priority mode, modality, context caching, and preview status.
- Example Gemini 3 Flash Preview standard paid input pricing: `$0.50 / 1M` for text/image/video input and `$1.00 / 1M` for audio input. Batch/Flex paid input is lower at `$0.25 / 1M` for text/image/video and `$0.50 / 1M` for audio. Priority paid input is higher at `$0.90 / 1M` for text/image/video and `$1.80 / 1M` for audio.
- Example Gemini 2.5 Flash standard paid input pricing: `$0.30 / 1M` for text/image/video and `$1.00 / 1M` for audio. Gemini 2.5 Flash-Lite standard paid input pricing is `$0.10 / 1M` for text/image/video and `$0.30 / 1M` for audio.
- Grounding with Google Search varies by model generation. Gemini 3 pricing examples show 5,000 prompts/month free shared across Gemini 3, then `$14 / 1,000 search queries`; Gemini 2.5 Flash/Flash-Lite show 1,500 RPD free in the paid tier, then `$35 / 1,000 grounded prompts`.
- Google’s Search grounding docs say Gemini 3 is billed for each search query the model decides to execute, while Gemini 2.5 or older models are billed per prompt.
- Google states a customer request to Gemini may result in one or more Google Search queries. For Gemini 3 search grounding, retrieved context provided by Grounding with Google Search is not charged as input tokens.
- The Search grounding docs page observed here was last updated 2026-04-28 UTC.

Implication: Gemini search cost changes by model family and by whether billing is per model-decided search query or per grounded prompt. Hard-coding one Gemini search price would be wrong across current public models.

## Recommendation for jpcite

Use a provider-pricing registry, not constants embedded in application logic.

Minimum useful shape:

- `provider`
- `model`
- `api_surface` or `tool_name`
- `unit`, such as `input_mtok`, `cached_input_mtok`, `web_search_1k_calls`, `grounded_prompt_1k`, or `search_query_1k`
- `price_usd`
- `conditions`, such as `standard`, `batch`, `flex`, `priority`, `short_context`, `long_context`, `preview`, `reasoning`, `non_reasoning`, `data_residency`, `free_tier_exhausted`
- `source_url`
- `retrieved_at`
- `notes`

For user-visible estimates, show ranges or “estimate only” language unless the exact model, processing route, cache state, and tool usage are known. For billing reconciliation, prefer provider-reported usage metadata over local estimates.

## Verification limits

Exact current prices are always hard to verify as durable truth because provider pricing pages are live documents and may change without a versioned changelog on the same page. The numbers above were verified from official public pages on 2026-04-30, but they should be refreshed before any pricing-sensitive release or public claim.
