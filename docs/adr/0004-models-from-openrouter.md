# 4. Models come from OpenRouter, through a Foundry gateway connection

Date: 26 October 2026. Status: accepted.

## Context

PRD 14.13 planned a model deployment per tier in the Foundry project. The team has an OpenRouter key and wants the agents' model calls to go through it. Foundry Agent Service can call models behind a bring-your-own AI gateway, and Agent Framework's OpenAI-compatible clients can call OpenRouter directly.

## Decision

- The Foundry project holds a bring-your-own-model gateway connection to OpenRouter, with the key stored only in that connection. The agents stay prompt agents in Foundry Agent Service and use OpenRouter's models through it.
- If OpenRouter doesn't work as a gateway connection (PRD open question 13), Agent Framework calls OpenRouter directly from the VM, with the key in the VM's secrets directory. `offball/agents/llm.py` already builds an `OpenAIChatClient`, today on the Foundry endpoint; the direct route changes only its endpoint and key, or switches to the Chat Completions client if a model isn't served on the Responses API.
- OpenRouter is restricted to providers that neither train on prompts nor keep them.
- Each agent's model is chosen by evaluation from OpenRouter's catalogue.

## Consequences

- Foundry's model router isn't used, so the Pundit runs on the reasoning tier.
- Foundry's AI-assisted evaluators need a judge model: an OpenRouter model if they accept one, or else one small deployment in Foundry (PRD open question 19).
- Each call goes through Foundry and then OpenRouter, which adds latency to measure against the 3 s budget (PRD section 24).
- Model spending is capped by the key's credit limit. Foundry bills only Speech, Content Safety and evaluations.
- The optional reinforcement-learning track would deploy its trained Scout in Foundry, the one model hosted there.
