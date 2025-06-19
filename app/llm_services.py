import json
import requests
from openai import OpenAI # Ensure 'openai>=1.0' (e.g., openai>=1.3.0) is in requirements.txt
from flask import current_app
from .database import get_db, get_setting # For settings and logging to api_usage

def _log_api_usage(db, provider, endpoint, prompt_tokens=None, completion_tokens=None, total_tokens=None, cost_usd=None):
    """Helper function to log API usage to the database."""
    try:
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO api_usage (timestamp, provider, endpoint, prompt_tokens, completion_tokens, total_tokens, cost_usd)
               VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)""",
            (provider, endpoint, prompt_tokens, completion_tokens, total_tokens, cost_usd)
        )
        db.commit()
        current_app.logger.info(f"Logged API usage for {provider} - {endpoint}.")
    except Exception as e:
        current_app.logger.error(f"Failed to log API usage: {e}", exc_info=True)
        # Not rolling back here as logging failure shouldn't typically halt the main operation,
        # but the calling function might decide to based on its own error handling.

def get_llm_response(prompt_text, llm_model_name=None):
    """
    Gets a response from the configured LLM provider.

    Args:
        prompt_text (str): The text prompt to send to the LLM.
        llm_model_name (str, optional): Specific model name to use (e.g., 'gpt-4', 'llama3').
                                         If None, defaults will be used based on the provider.

    Returns:
        tuple: (response_text, error_message)
               response_text is the string from the LLM, or None if an error occurred.
               error_message is a string describing the error, or None if successful.
    """
    db = get_db() # Ensure this is called within an active Flask app context
    provider = get_setting("preferred_llm_provider")
    openai_api_key = get_setting("openai_api_key")
    ollama_url = get_setting("ollama_url")

    # Default model names (could be moved to settings or config file later)
    default_openai_model = "gpt-3.5-turbo"
    default_ollama_model = "llama2" # Make sure this model is available in the user's Ollama instance

    response_text = None
    error_message = None

    if provider == "openai":
        if not openai_api_key:
            error_message = "OpenAI API key is not configured in settings."
            current_app.logger.error(error_message)
            return None, error_message

        client = OpenAI(api_key=openai_api_key)
        chosen_model = llm_model_name if llm_model_name else default_openai_model
        current_app.logger.info(f"Sending request to OpenAI API. Model: {chosen_model}")
        try:
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt_text}],
                model=chosen_model,
            )
            response_text = chat_completion.choices[0].message.content
            usage = chat_completion.usage
            # Basic cost calculation for gpt-3.5-turbo (example, can be expanded)
            cost = 0
            if chosen_model == "gpt-3.5-turbo": # Example, expand for other models or use a pricing API/library
                cost = (usage.prompt_tokens * 0.0005 / 1000) + (usage.completion_tokens * 0.0015 / 1000)

            _log_api_usage(
                db, "openai", chosen_model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost_usd=cost if cost > 0 else None
            )
            current_app.logger.info(f"Received response from OpenAI. Model: {chosen_model}, Tokens: {usage.total_tokens}, Cost: ${cost:.5f}")
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
            response = requests.post(ollama_api_endpoint, json=payload, timeout=120) # 120s timeout
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

            _log_api_usage(db, "ollama", chosen_model,
                           prompt_tokens=prompt_tokens,
                           completion_tokens=completion_tokens,
                           total_tokens=total_tokens, # This might be an approximation
                           cost_usd=0) # Ollama is typically self-hosted, cost is effectively 0 from API perspective
            current_app.logger.info(f"Received response from Ollama for model {chosen_model}.")

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
