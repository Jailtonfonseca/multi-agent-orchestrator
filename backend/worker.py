import os
import io
import contextlib
import json
import redis
import uuid
import sys
import time
from celery import Celery
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
from duckduckgo_search import DDGS
import requests
from tavily import TavilyClient

# Configure Celery
app = Celery('autogen_tasks', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

# Redis Client
redis_client = redis.Redis(host='redis', port=6379, db=0)

# --- TOOLS ---
def search_web(query: str, tavily_key: str = None) -> str:
    """
    Searches the web for real-time information.
    Prioritizes Tavily API if a key is provided, otherwise falls back to DuckDuckGo.
    """
    if tavily_key and len(tavily_key) > 5:
        try:
            tavily = TavilyClient(api_key=tavily_key)
            response = tavily.search(query=query, search_depth="basic", max_results=5)
            results = response.get("results", [])
            if not results:
                return "No results found (Tavily)."

            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title')}\nURL: {r.get('url')}\nContent: {r.get('content')}\n---")
            return "\n".join(formatted_results)
        except Exception as e:
            return f"Error with Tavily Search: {str(e)}. Falling back to DuckDuckGo..."

    # Fallback to DuckDuckGo
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No results found (DuckDuckGo)."

            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title')}\nURL: {r.get('href')}\nSnippet: {r.get('body')}\n---")

            return "\n".join(formatted_results)
    except Exception as e:
        return f"Error searching web: {str(e)}"

def get_crypto_price(symbol: str) -> str:
    """
    Fetches the current price of a cryptocurrency from CoinGecko.
    Args:
        symbol: The ticker symbol (e.g., 'bitcoin', 'ethereum', 'solana').
    """
    try:
        # CoinGecko uses IDs, not symbols for free endpoint, but simple search helps
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": symbol.lower(),
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if symbol.lower() in data:
            price = data[symbol.lower()]["usd"]
            change = data[symbol.lower()].get("usd_24h_change", 0)
            return f"The current price of {symbol} is ${price} USD ({change:.2f}% in 24h)."
        else:
            return f"Could not find price for '{symbol}'. Try using the full name (e.g., 'bitcoin' instead of 'BTC')."
    except Exception as e:
        return f"Error fetching crypto price: {str(e)}"

class RedisOutputRedirector(io.StringIO):
    """
    Redirects stdout to a Redis Pub/Sub channel AND saves to a persistent Redis list.
    """
    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def write(self, s):
        if s.strip():
            msg = {
                "type": "log",
                "content": s,
                "timestamp": time.time()
            }
            msg_json = json.dumps(msg)

            try:
                redis_client.publish(self.session_id, msg_json)
            except Exception:
                pass

            try:
                redis_client.rpush(f"logs:{self.session_id}", msg_json)
            except Exception:
                pass

        return len(s)

class InteractiveUserProxy(autogen.UserProxyAgent):
    """
    A custom UserProxyAgent that waits for user input from a Redis channel.
    """
    def __init__(self, session_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.redis_sub = redis.Redis(host='redis', port=6379, db=0)
        self.input_channel = f"input_{session_id}"

    def get_human_input(self, prompt: str) -> str:
        print(f"WAITING FOR USER INPUT: {prompt}")

        status_msg = {
            "type": "status",
            "content": "WAITING_FOR_INPUT"
        }
        msg_json = json.dumps(status_msg)

        redis_client.publish(self.session_id, msg_json)
        redis_client.rpush(f"logs:{self.session_id}", msg_json)

        pubsub = self.redis_sub.pubsub()
        pubsub.subscribe(self.input_channel)

        try:
            for message in pubsub.listen():
                if message['type'] == 'message':
                    user_input = message['data'].decode('utf-8')

                    executing_msg = json.dumps({"type": "status", "content": "EXECUTING_TASK"})
                    redis_client.publish(self.session_id, executing_msg)
                    redis_client.rpush(f"logs:{self.session_id}", executing_msg)

                    return user_input
        finally:
            pubsub.unsubscribe(self.input_channel)
            pubsub.close()

        return ""

@app.task(name="worker.create_team_and_execute")
def create_team_and_execute(session_id, task, api_key, model, provider="openrouter", system_message=None, tavily_key=None):
    """
    Celery task to run the AutoGen process.
    """
    config_filename = f"OAI_{session_id}.json"

    session_data = {
        "id": session_id,
        "task": task[:50] + "..." if len(task) > 50 else task,
        "model": model,
        "created_at": time.time(),
        "status": "BUILDING_TEAM"
    }
    redis_client.hset(f"session:{session_id}", mapping=session_data)
    redis_client.lpush("all_sessions", session_id)

    try:
        start_msg = json.dumps({"type": "status", "content": "BUILDING_TEAM"})
        redis_client.publish(session_id, start_msg)
        redis_client.rpush(f"logs:{session_id}", start_msg)

        output_redirector = RedisOutputRedirector(session_id)

        # --- Provider Configuration ---
        base_url = "https://openrouter.ai/api/v1" # Default

        if provider == "openai":
            base_url = None # Standard OpenAI
        elif provider == "groq":
            base_url = "https://api.groq.com/openai/v1"
        elif provider == "deepseek":
            base_url = "https://api.deepseek.com"

        llm_config_entry = {
            "model": model,
            "api_key": api_key,
        }

        if base_url:
            llm_config_entry["base_url"] = base_url

        config_list = [llm_config_entry]

        with open(config_filename, "w") as f:
            json.dump(config_list, f)

        work_dir = f"/app/workspaces/{session_id}"
        os.makedirs(work_dir, exist_ok=True)

        with contextlib.redirect_stdout(output_redirector):
            print(f"Initializing AgentBuilder for model: {model} (Provider: {provider})...")
            builder = AgentBuilder(
                config_file_or_env=config_filename,
                builder_model=model,
                agent_model=model
            )

            print("Building agents based on task...")

            system_prompt_hint = (
                "You are a pragmatic team builder. "
                "The agents you create must be grounded in reality. "
                "You have access to a 'search_web' tool (powered by Tavily/DuckDuckGo) and 'get_crypto_price' tool. "
                "Prefer using these tools to find real-time information rather than assuming facts. "
                "Agents must use the provided python environment which has pandas, numpy, requests, duckduckgo-search, and matplotlib pre-installed. "
            )

            if system_message:
                system_prompt_hint += f"\n\nGlobal Instructions: {system_message}"

            enhanced_task = f"{system_prompt_hint}\n\nUser Task: {task}"

            try:
                agent_list, agent_configs = builder.build(
                    building_task=enhanced_task,
                    default_llm_config={"config_list": config_list},
                    coding=True
                )
            except Exception as build_err:
                print(f"AgentBuilder failed: {build_err}")
                raise build_err

            redis_client.hset(f"session:{session_id}", "status", "EXECUTING_TASK")
            exec_msg = json.dumps({"type": "status", "content": "EXECUTING_TASK"})
            redis_client.publish(session_id, exec_msg)
            redis_client.rpush(f"logs:{session_id}", exec_msg)

            print(f"Team built with {len(agent_list)} agents. configuring tools...")

            # --- REGISTER TOOLS ---
            user_proxy = InteractiveUserProxy(
                session_id=session_id,
                name="User_Proxy",
                human_input_mode="TERMINATE",
                code_execution_config={
                    "use_docker": False,
                    "work_dir": work_dir
                },
                is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
            )

            # Wrapper for search_web to inject API key without exposing it to the agent
            def search_web_wrapper(query: str) -> str:
                return search_web(query, tavily_key=tavily_key)

            # Register for User Proxy (Executor)
            user_proxy.register_for_execution(name="search_web")(search_web_wrapper)
            user_proxy.register_for_execution(name="get_crypto_price")(get_crypto_price)

            for agent in agent_list:
                # IMPORTANT: Check for llm_config to avoid crash on proxy agents
                if getattr(agent, 'llm_config', False):
                    # Register Search
                    autogen.agentchat.register_function(
                        search_web_wrapper,
                        caller=agent,
                        executor=user_proxy,
                        name="search_web",
                        description="Searches the web for real-time information. Use this to find news, articles, documentation, or verify facts."
                    )

                    # Register Crypto Price
                    autogen.agentchat.register_function(
                        get_crypto_price,
                        caller=agent,
                        executor=user_proxy,
                        name="get_crypto_price",
                        description="Gets the current price of a cryptocurrency (e.g. 'bitcoin', 'ethereum') in USD."
                    )
                    print(f"Registered tools for agent: {agent.name}")
                else:
                     print(f"Skipping tool registration for agent '{agent.name}' (no llm_config)")

            print("Starting conversation...")

            group_chat = autogen.GroupChat(
                agents=[user_proxy] + agent_list,
                messages=[],
                max_round=12
            )

            manager = autogen.GroupChatManager(
                groupchat=group_chat,
                llm_config={"config_list": config_list}
            )

            user_proxy.initiate_chat(manager, message=task)

        redis_client.hset(f"session:{session_id}", "status", "COMPLETED")
        comp_msg = json.dumps({"type": "status", "content": "COMPLETED"})
        redis_client.publish(session_id, comp_msg)
        redis_client.rpush(f"logs:{session_id}", comp_msg)

    except Exception as e:
        redis_client.hset(f"session:{session_id}", "status", "ERROR")
        error_msg = json.dumps({"type": "error", "content": str(e)})
        redis_client.publish(session_id, error_msg)
        redis_client.rpush(f"logs:{session_id}", error_msg)
    finally:
        if os.path.exists(config_filename):
            try:
                os.remove(config_filename)
            except:
                pass
