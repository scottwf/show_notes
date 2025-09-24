"""
LLM Service Abstraction Layer

This module provides a unified interface for interacting with various Large Language
Model (LLM) providers, such as OpenAI and Ollama. It abstracts the provider-specific
logic for sending prompts and handling responses, allowing the rest of the application
to use a single, consistent function to get LLM-generated content.

Key Features:
- **Provider Switching:** Dynamically selects the LLM provider based on application
  settings, allowing administrators to switch between services like OpenAI and a
  self-hosted Ollama instance without code changes.
- **Unified Response Handling:** The main `get_llm_response` function returns a
  consistent tuple `(response_text, error_message)`, regardless of the provider used.
- **API Usage Logging:** Automatically logs every LLM API call to the local database,
  capturing details like the provider, model, token counts, processing time, and
  estimated cost (for applicable services). This is crucial for monitoring and
  cost management.
- **Error Handling:** Gracefully handles common errors such as configuration issues
  (missing API keys/URLs), connection timeouts, and API-specific errors, providing
  clear log messages and error feedback.
"""
import json
import requests
from openai import OpenAI # Ensure 'openai>=1.0' (e.g., openai>=1.3.0) is in requirements.txt
from flask import current_app
from .database import get_db, get_setting # For settings and logging to api_usage

def _log_api_usage(db, provider, endpoint, prompt_tokens=None, completion_tokens=None, total_tokens=None, cost_usd=None, processing_time_ms=None):
    """
    Logs the details of an LLM API call to the database.

    This private helper function is called after every attempt to communicate with an
    LLM provider. It records key metrics for monitoring and analysis.

    Args:
        db (sqlite3.Connection): An active database connection object.
        provider (str): The name of the LLM provider (e.g., 'openai', 'ollama').
        endpoint (str): The specific model or endpoint used (e.g., 'gpt-3.5-turbo').
        prompt_tokens (int, optional): The number of tokens in the prompt.
        completion_tokens (int, optional): The number of tokens in the generated response.
        total_tokens (int, optional): The total tokens used in the API call.
        cost_usd (float, optional): The estimated cost of the API call in USD.
        processing_time_ms (int, optional): The time taken for the API call in milliseconds.
    """
    try:
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO api_usage (timestamp, provider, endpoint, prompt_tokens, completion_tokens, total_tokens, cost_usd, processing_time_ms)
               VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, endpoint, prompt_tokens, completion_tokens, total_tokens, cost_usd, processing_time_ms)
        )
        db.commit()
        current_app.logger.info(f"Logged API usage for {provider} - {endpoint}.")
    except Exception as e:
        current_app.logger.error(f"Failed to log API usage: {e}", exc_info=True)
        # Not rolling back here as logging failure shouldn't typically halt the main operation,
        # but the calling function might decide to based on its own error handling.

def get_llm_response(prompt_text, llm_model_name=None, provider=None):
    """
    Gets a response from the configured LLM provider.

    This is the primary function for interacting with LLMs. It determines which
    provider to use based on application settings, constructs the appropriate
    API request, sends the prompt, and logs the usage details.

    Args:
        prompt_text (str): The text prompt to send to the LLM.
        llm_model_name (str, optional): The specific model name to use (e.g., 'gpt-4', 'llama3').
                                         If None, the function will use the default model configured
                                         for the selected provider. Defaults to None.
        provider (str, optional): The specific provider to use ('openai' or 'ollama').
                                  If None, the function will use the `preferred_llm_provider`
                                  from the application settings. Defaults to None.

    Returns:
        tuple: A tuple containing `(response_text, error_message)`.
               - `response_text` (str or None): The content of the LLM's response.
                 This is None if an error occurred.
               - `error_message` (str or None): A description of the error if one
                 occurred, otherwise None.
    """
    db = get_db() # Ensure this is called within an active Flask app context
    if provider is None:
        provider = get_setting("preferred_llm_provider")
    openai_api_key = get_setting("openai_api_key")
    ollama_url = get_setting("ollama_url")

    # Default model names (could be moved to settings or config file later)
    default_openai_model = get_setting("openai_model_name") or "gpt-3.5-turbo"
    # Use the admin-configured model if present, else fallback
    default_ollama_model = get_setting("ollama_model_name") or "llama2" # Make sure this model is available in the user's Ollama instance

    response_text = None
    error_message = None

    import time
    if provider == "openai":
        if not openai_api_key:
            error_message = "OpenAI API key is not configured in settings."
            current_app.logger.error(error_message)
            return None, error_message

        client = OpenAI(api_key=openai_api_key)
        chosen_model = llm_model_name if llm_model_name else default_openai_model
        current_app.logger.info(f"Sending request to OpenAI API. Model: {chosen_model}")
        try:
            start_time = time.perf_counter()
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt_text}],
                model=chosen_model,
            )
            end_time = time.perf_counter()
            response_text = chat_completion.choices[0].message.content
            usage = chat_completion.usage
            # Cost calculation for different OpenAI models
            cost = 0
            if chosen_model == "gpt-3.5-turbo":
                cost = (usage.prompt_tokens * 0.0005 / 1000) + (usage.completion_tokens * 0.0015 / 1000)
            elif chosen_model == "gpt-4o":
                cost = (usage.prompt_tokens * 0.005 / 1000) + (usage.completion_tokens * 0.015 / 1000)
            elif chosen_model == "gpt-4":
                cost = (usage.prompt_tokens * 0.03 / 1000) + (usage.completion_tokens * 0.06 / 1000)
            elif chosen_model == "gpt-4-turbo":
                cost = (usage.prompt_tokens * 0.01 / 1000) + (usage.completion_tokens * 0.03 / 1000)
            processing_time_ms = int((end_time - start_time) * 1000)
            _log_api_usage(
                db, "openai", chosen_model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost_usd=cost if cost > 0 else None,
                processing_time_ms=processing_time_ms
            )
            current_app.logger.info(f"Received response from OpenAI. Model: {chosen_model}, Tokens: {usage.total_tokens}, Cost: ${cost:.5f}, Processing Time: {processing_time_ms}ms")
        except Exception as e:
            error_message = f"OpenAI API request failed: {e}"
            current_app.logger.error(error_message, exc_info=True)
            _log_api_usage(db, "openai", chosen_model, cost_usd=0) # Log attempt even on failure
            return None, error_message

    elif provider == "ollama":
        if not ollama_url:
            error_message = "Ollama URL is not configured in settings."
            current_app.logger.error(error_message)
            return None, error_message

        ollama_api_endpoint = ollama_url.rstrip('/') + "/api/generate"
        chosen_model = llm_model_name if llm_model_name else default_ollama_model
        current_app.logger.info(f"Sending request to Ollama API. Endpoint: {ollama_api_endpoint}, Model: {chosen_model}")

        payload = {
            "model": chosen_model,
            "prompt": prompt_text,
            "stream": False # Get full response at once
        }
        try:
            start_time = time.perf_counter()
            response = requests.post(ollama_api_endpoint, json=payload, timeout=120) # 120s timeout
            end_time = time.perf_counter()
            response.raise_for_status()

            ollama_data = response.json()
            response_text = ollama_data.get("response", "").strip()

            # Ollama token logging (approximate as Ollama provides eval counts, not exact token counts like OpenAI)
            # These are typically "evaluation counts" rather than standard "tokens".
            prompt_tokens = ollama_data.get("prompt_eval_count")
            completion_tokens = ollama_data.get("eval_count")
            total_tokens = None
            if prompt_tokens is not None and completion_tokens is not None:
                 total_tokens = prompt_tokens + completion_tokens
            processing_time_ms = int((end_time - start_time) * 1000)
            _log_api_usage(db, "ollama", chosen_model,
                           prompt_tokens=prompt_tokens,
                           completion_tokens=completion_tokens,
                           total_tokens=total_tokens, # This might be an approximation
                           cost_usd=0, # Ollama is typically self-hosted, cost is effectively 0 from API perspective
                           processing_time_ms=processing_time_ms)
            current_app.logger.info(f"Received response from Ollama for model {chosen_model}. Processing Time: {processing_time_ms}ms")

        except requests.exceptions.RequestException as e:
            error_message = f"Ollama API request failed: {e}"
            current_app.logger.error(error_message, exc_info=True)
            _log_api_usage(db, "ollama", chosen_model, cost_usd=0)
            return None, error_message
        except json.JSONDecodeError as e:
            error_message = f"Failed to parse Ollama response: {e}. Response text: {response.text[:200]}"
            current_app.logger.error(error_message, exc_info=True)
            _log_api_usage(db, "ollama", chosen_model, cost_usd=0)
            return None, error_message

    elif not provider or provider.lower() == "none" or provider == "":
        error_message = "No LLM provider selected or 'None' is chosen in settings. LLM functionality is disabled."
        current_app.logger.info(error_message)
        # This is not an error per se, but a state where LLM features are off.
        return None, error_message # No response, and an informational "error" message

    else:
        error_message = f"Unsupported LLM provider configured: {provider}"
        current_app.logger.error(error_message)
        return None, error_message

    if response_text:
        return response_text, None # Successful response
    else:
        # If response_text is None but no specific error was set by this point (should be rare)
        if not error_message:
            error_message = "LLM provider returned an empty or invalid response."
            current_app.logger.warning(f"Empty response from {provider} for model {chosen_model or 'default'}")
        return None, error_message
