"""
LLM Service Abstraction Layer

Provides a unified interface for interacting with LLM providers (OpenAI, Ollama,
OpenRouter). Handles provider switching, API usage logging, and summary generation
for TV show seasons and episodes.
"""
import json
import time
import requests
from openai import OpenAI
from flask import current_app
from .database import get_db, get_setting


def _log_api_usage(db, provider, endpoint, prompt_tokens=None, completion_tokens=None,
                   total_tokens=None, cost_usd=None, processing_time_ms=None):
    """Log an LLM API call to the api_usage table."""
    try:
        db.execute(
            """INSERT INTO api_usage (timestamp, provider, endpoint, prompt_tokens,
               completion_tokens, total_tokens, cost_usd, processing_time_ms)
               VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, endpoint, prompt_tokens, completion_tokens, total_tokens,
             cost_usd, processing_time_ms)
        )
        db.commit()
    except Exception as e:
        current_app.logger.error(f"Failed to log API usage: {e}", exc_info=True)


def get_llm_response(prompt_text, llm_model_name=None, provider=None):
    """
    Get a response from the configured LLM provider.

    Args:
        prompt_text: The prompt to send.
        llm_model_name: Specific model name override.
        provider: Specific provider override ('openai', 'ollama', 'openrouter').

    Returns:
        tuple: (response_text, error_message) - one will be None.
    """
    db = get_db()
    if provider is None:
        provider = get_setting("preferred_llm_provider")

    if not provider or provider.lower() == "none" or provider == "":
        return None, "No LLM provider configured. Set one in Admin > AI settings."

    if provider == "openai":
        return _call_openai(db, prompt_text, llm_model_name)
    elif provider == "ollama":
        return _call_ollama(db, prompt_text, llm_model_name)
    elif provider == "openrouter":
        return _call_openrouter(db, prompt_text, llm_model_name)
    else:
        return None, f"Unsupported LLM provider: {provider}"


def _call_openai(db, prompt_text, llm_model_name=None):
    """Call OpenAI API."""
    api_key = get_setting("openai_api_key")
    if not api_key:
        return None, "OpenAI API key is not configured."

    model = llm_model_name or get_setting("openai_model_name") or "gpt-4o-mini"
    current_app.logger.info(f"Sending request to OpenAI. Model: {model}")

    try:
        client = OpenAI(api_key=api_key)
        start = time.perf_counter()
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_text}],
            model=model,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        text = completion.choices[0].message.content
        usage = completion.usage
        cost = _estimate_openai_cost(model, usage.prompt_tokens, usage.completion_tokens)

        _log_api_usage(db, "openai", model,
                       prompt_tokens=usage.prompt_tokens,
                       completion_tokens=usage.completion_tokens,
                       total_tokens=usage.total_tokens,
                       cost_usd=cost if cost > 0 else None,
                       processing_time_ms=elapsed_ms)
        current_app.logger.info(f"OpenAI response: {model}, {usage.total_tokens} tokens, ${cost:.5f}, {elapsed_ms}ms")
        return text, None
    except Exception as e:
        msg = f"OpenAI API request failed: {e}"
        current_app.logger.error(msg, exc_info=True)
        _log_api_usage(db, "openai", model, cost_usd=0)
        return None, msg


def _call_ollama(db, prompt_text, llm_model_name=None):
    """Call Ollama API."""
    url = get_setting("ollama_url")
    if not url:
        return None, "Ollama URL is not configured."

    model = llm_model_name or get_setting("ollama_model_name") or "llama3"
    endpoint = url.rstrip('/') + "/api/generate"
    current_app.logger.info(f"Sending request to Ollama. Model: {model}")

    try:
        start = time.perf_counter()
        resp = requests.post(endpoint, json={"model": model, "prompt": prompt_text, "stream": False}, timeout=180)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        resp.raise_for_status()

        data = resp.json()
        text = data.get("response", "").strip()
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        total = (prompt_tokens or 0) + (completion_tokens or 0) if prompt_tokens or completion_tokens else None

        _log_api_usage(db, "ollama", model,
                       prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                       total_tokens=total, cost_usd=0, processing_time_ms=elapsed_ms)
        current_app.logger.info(f"Ollama response: {model}, {elapsed_ms}ms")
        return text, None
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        msg = f"Ollama API request failed: {e}"
        current_app.logger.error(msg, exc_info=True)
        _log_api_usage(db, "ollama", model, cost_usd=0)
        return None, msg


def _call_openrouter(db, prompt_text, llm_model_name=None):
    """Call OpenRouter API (OpenAI-compatible)."""
    api_key = get_setting("openrouter_api_key")
    if not api_key:
        return None, "OpenRouter API key is not configured."

    model = llm_model_name or get_setting("openrouter_model_name") or "openai/gpt-4o-mini"
    current_app.logger.info(f"Sending request to OpenRouter. Model: {model}")

    try:
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        start = time.perf_counter()
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_text}],
            model=model,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        text = completion.choices[0].message.content
        usage = completion.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        total_tokens = usage.total_tokens if usage else None

        _log_api_usage(db, "openrouter", model,
                       prompt_tokens=prompt_tokens,
                       completion_tokens=completion_tokens,
                       total_tokens=total_tokens,
                       cost_usd=None,  # OpenRouter reports cost separately
                       processing_time_ms=elapsed_ms)
        current_app.logger.info(f"OpenRouter response: {model}, {total_tokens} tokens, {elapsed_ms}ms")
        return text, None
    except Exception as e:
        msg = f"OpenRouter API request failed: {e}"
        current_app.logger.error(msg, exc_info=True)
        _log_api_usage(db, "openrouter", model, cost_usd=0)
        return None, msg


def _estimate_openai_cost(model, prompt_tokens, completion_tokens):
    """Estimate cost in USD for an OpenAI API call."""
    rates = {
        "gpt-4o": (0.005 / 1000, 0.015 / 1000),
        "gpt-4o-mini": (0.00015 / 1000, 0.0006 / 1000),
        "gpt-4-turbo": (0.01 / 1000, 0.03 / 1000),
        "gpt-4": (0.03 / 1000, 0.06 / 1000),
        "gpt-3.5-turbo": (0.0005 / 1000, 0.0015 / 1000),
    }
    if model in rates:
        input_rate, output_rate = rates[model]
        return (prompt_tokens * input_rate) + (completion_tokens * output_rate)
    return 0


def get_prompt_template(prompt_key):
    """Load a prompt template from the llm_prompts table."""
    db = get_db()
    row = db.execute("SELECT prompt_template FROM llm_prompts WHERE prompt_key = ?", (prompt_key,)).fetchone()
    return row['prompt_template'] if row else None


def generate_episode_summary(show_title, season_number, episode_number, episode_title, episode_overview):
    """
    Generate an AI summary for a single episode.

    Returns:
        tuple: (summary_text, error_message)
    """
    template = get_prompt_template("episode_summary")
    if not template:
        return None, "Episode summary prompt template not found."

    prompt = template.format(
        show_title=show_title,
        season_number=season_number,
        episode_number=episode_number,
        episode_title=episode_title or "Unknown",
        episode_overview=episode_overview or "No description available."
    )
    return get_llm_response(prompt)


def generate_season_recap(show_title, season_number, episode_summaries_text):
    """
    Generate an AI recap for an entire season.

    Args:
        episode_summaries_text: Pre-formatted text of episode summaries for context.

    Returns:
        tuple: (recap_text, error_message)
    """
    template = get_prompt_template("season_recap")
    if not template:
        return None, "Season recap prompt template not found."

    prompt = template.format(
        show_title=show_title,
        season_number=season_number,
        episode_summaries=episode_summaries_text or "No individual episode summaries available."
    )
    return get_llm_response(prompt)
