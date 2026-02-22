import os
import io
import contextlib
import json
import redis
import time
import sys
import traceback
import tempfile
from celery import Celery
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
from duckduckgo_search import DDGS
from tavily import TavilyClient
import requests
from sqlmodel import Session, select
from database import engine
from models import Session as DBSession, Log

# ── Celery & Redis ─────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
WORKSPACES_DIR = os.getenv("WORKSPACES_DIR", "/tmp/workspaces")
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "12"))

app = Celery('autogen_tasks', broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.from_url(REDIS_URL)


# ── Tools ──────────────────────────────────────────────────────────────────────
def search_web(query: str, tavily_key: str = None) -> str:
    """Search the web using Tavily (preferred) or DuckDuckGo as fallback."""
    if tavily_key and len(tavily_key) > 5:
        try:
            tavily = TavilyClient(api_key=tavily_key)
            response = tavily.search(query=query, search_depth="basic", max_results=5)
            results = response.get("results", [])
            if not results:
                return "No results found (Tavily)."
            return "\n".join(
                f"Title: {r.get('title')}\nURL: {r.get('url')}\nContent: {r.get('content')}\n---"
                for r in results
            )
        except Exception as e:
            sys.stderr.write(f"Tavily error: {e}. Falling back to DuckDuckGo.\n")

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No results found (DDG)."
            return "\n".join(
                f"Title: {r.get('title')}\nURL: {r.get('href')}\nSnippet: {r.get('body')}\n---"
                for r in results
            )
    except Exception as e:
        return f"Error searching web: {str(e)}"


def get_crypto_price(symbol: str) -> str:
    """Fetch current cryptocurrency price from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": symbol.lower(), "vs_currencies": "usd", "include_24hr_change": "true"}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if symbol.lower() in data:
            price = data[symbol.lower()]["usd"]
            change = data[symbol.lower()].get("usd_24h_change", 0)
            return f"{symbol}: ${price:,.2f} USD (24h: {change:+.2f}%)"
        return f"Could not find price for '{symbol}'."
    except Exception as e:
        return f"Error fetching crypto price: {str(e)}"


# ── Output Redirector ──────────────────────────────────────────────────────────
class DBOutputRedirector(io.StringIO):
    """Writes stdout to Redis Pub/Sub (real-time) AND PostgreSQL (persistence)."""

    def __init__(self, session_id: str):
        super().__init__()
        self.session_id = session_id

    def write(self, s: str) -> int:
        if s.strip():
            # Always echo to actual stderr so it shows up in docker logs
            sys.stderr.write(f"[AGENT OUT] {s}\n")

            msg = {"type": "log", "content": s, "timestamp": time.time()}
            try:
                redis_client.publish(self.session_id, json.dumps(msg))
            except Exception:
                pass
            try:
                with Session(engine) as session:
                    log = Log(
                        session_id=self.session_id,
                        type="log",
                        content=s,
                        timestamp=time.time()
                    )
                    session.add(log)
                    session.commit()
            except Exception as e:
                sys.stderr.write(f"DB Log Error: {e}\n")
        return len(s)

    def flush(self):
        pass


# ── Interactive User Proxy ─────────────────────────────────────────────────────
class InteractiveUserProxy(autogen.UserProxyAgent):
    """Pauses agent execution and waits for human input via Redis Pub/Sub."""

    def __init__(self, session_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.input_channel = f"input_{session_id}"

    def get_human_input(self, prompt: str) -> str:
        print(f"WAITING FOR USER INPUT: {prompt}")

        redis_client.publish(
            self.session_id,
            json.dumps({"type": "status", "content": "WAITING_FOR_INPUT"})
        )
        _update_db_status(self.session_id, "WAITING_FOR_INPUT")

        sub = redis_client.pubsub()
        sub.subscribe(self.input_channel)
        try:
            for message in sub.listen():
                if message['type'] == 'message':
                    user_input = message['data'].decode('utf-8')
                    if user_input == "TERMINATE":
                        return "exit"
                    redis_client.publish(
                        self.session_id,
                        json.dumps({"type": "status", "content": "EXECUTING_TASK"})
                    )
                    _update_db_status(self.session_id, "EXECUTING_TASK")
                    return user_input
        finally:
            sub.unsubscribe(self.input_channel)
            sub.close()
        return ""


# ── DB Helpers ─────────────────────────────────────────────────────────────────
def _update_db_status(session_id: str, status: str):
    try:
        with Session(engine) as session:
            db_sess = session.get(DBSession, session_id)
            if db_sess:
                db_sess.status = status
                session.add(db_sess)
                session.commit()
    except Exception as e:
        sys.stderr.write(f"DB Status Update Error: {e}\n")


def _publish(session_id: str, payload: dict):
    try:
        redis_client.publish(session_id, json.dumps(payload))
    except Exception as e:
        sys.stderr.write(f"Redis Publish Error: {e}\n")


# ── Celery Task ────────────────────────────────────────────────────────────────
@app.task(name="worker.create_team_and_execute", bind=True, max_retries=0)
def create_team_and_execute(
    self,
    session_id: str,
    task: str,
    api_key: str,
    model: str,
    provider: str = "openrouter",
    system_message: str = None,
    tavily_key: str = None
):
    sys.stderr.write(f"\n{'='*60}\n")
    sys.stderr.write(f"[TASK START] session={session_id} model={model} provider={provider}\n")
    sys.stderr.write(f"[TASK] {task[:120]}\n")
    sys.stderr.write(f"{'='*60}\n")

    output_redirector = DBOutputRedirector(session_id)
    work_dir = os.path.join(WORKSPACES_DIR, session_id)
    os.makedirs(work_dir, exist_ok=True)

    # Write config to a temp file — never use CWD (permission issues)
    config_fd, config_filename = tempfile.mkstemp(suffix=".json", prefix="OAI_")

    try:
        _publish(session_id, {"type": "status", "content": "BUILDING_TEAM"})

        # Build provider base URL
        base_url = None
        if provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
        elif provider == "groq":
            base_url = "https://api.groq.com/openai/v1"
        elif provider == "deepseek":
            base_url = "https://api.deepseek.com"
        elif provider == "anthropic":
            base_url = "https://api.anthropic.com/v1"

        config_list = [{"model": model, "api_key": api_key}]
        if base_url:
            config_list[0]["base_url"] = base_url

        with os.fdopen(config_fd, "w") as f:
            json.dump(config_list, f)
        config_fd = -1  # Mark as closed

        llm_config = {"config_list": config_list, "timeout": 120, "cache_seed": None}

        with contextlib.redirect_stdout(output_redirector):
            sys.stderr.write(f"[WORKER] Initializing AgentBuilder for {model}...\n")
            print(f"🔨 Initializing agent team for model: {model} via {provider}...")

            try:
                builder = AgentBuilder(
                    config_file_or_env=config_filename,
                    builder_model=model,
                    agent_model=model
                )

                system_prompt_hint = (
                    "You are a pragmatic team builder. Agents must use the provided python environment. "
                    "Use the search_web tool to look up information online. "
                    "Always produce concrete, actionable results."
                )
                if system_message:
                    system_prompt_hint += f"\n\nAdditional Instructions: {system_message}"

                enhanced_task = f"{system_prompt_hint}\n\nUser Task: {task}"

                sys.stderr.write("[WORKER] Calling builder.build()...\n")
                agent_list, _agent_configs = builder.build(
                    building_task=enhanced_task,
                    default_llm_config=llm_config,
                    coding=True
                )
                sys.stderr.write(f"[WORKER] Built {len(agent_list)} agents.\n")

            except Exception as builder_err:
                # AgentBuilder failed (often due to flaml or API issues)
                # Fall back to a simple single-agent setup
                sys.stderr.write(f"[WORKER] AgentBuilder failed: {builder_err}\n")
                sys.stderr.write("[WORKER] Falling back to simple AssistantAgent...\n")
                print(f"⚠️ AgentBuilder failed ({type(builder_err).__name__}: {builder_err})")
                print("🔄 Falling back to simple assistant mode...")

                assistant = autogen.AssistantAgent(
                    name="Assistant",
                    llm_config=llm_config,
                    system_message=(
                        "You are a highly capable AI assistant. Complete the given task thoroughly. "
                        + (system_message or "")
                    )
                )
                agent_list = [assistant]

            _update_db_status(session_id, "EXECUTING_TASK")
            _publish(session_id, {"type": "status", "content": "EXECUTING_TASK"})
            print("✅ Team ready. Starting task execution...")

            user_proxy = InteractiveUserProxy(
                session_id=session_id,
                name="User_Proxy",
                human_input_mode="TERMINATE",
                code_execution_config={"use_docker": False, "work_dir": work_dir},
                max_consecutive_auto_reply=MAX_ROUNDS
            )

            def search_web_wrapper(query: str) -> str:
                return search_web(query, tavily_key=tavily_key)

            user_proxy.register_for_execution(name="search_web")(search_web_wrapper)
            user_proxy.register_for_execution(name="get_crypto_price")(get_crypto_price)

            for agent in agent_list:
                if getattr(agent, 'llm_config', False):
                    try:
                        autogen.agentchat.register_function(
                            search_web_wrapper,
                            caller=agent,
                            executor=user_proxy,
                            name="search_web",
                            description="Search the web for real-time information using Tavily or DuckDuckGo."
                        )
                        autogen.agentchat.register_function(
                            get_crypto_price,
                            caller=agent,
                            executor=user_proxy,
                            name="get_crypto_price",
                            description="Get current USD price of a cryptocurrency by its CoinGecko ID (e.g. bitcoin, ethereum)."
                        )
                    except Exception as tool_err:
                        sys.stderr.write(f"[WORKER] Tool registration warning: {tool_err}\n")

            if len(agent_list) == 1:
                # Simple two-agent chat
                sys.stderr.write("[WORKER] Starting two-agent chat...\n")
                user_proxy.initiate_chat(agent_list[0], message=task)
            else:
                # Group chat
                sys.stderr.write(f"[WORKER] Starting group chat with {len(agent_list)+1} participants...\n")
                group_chat = autogen.GroupChat(
                    agents=[user_proxy] + agent_list,
                    messages=[],
                    max_round=MAX_ROUNDS
                )
                manager = autogen.GroupChatManager(
                    groupchat=group_chat,
                    llm_config=llm_config
                )
                user_proxy.initiate_chat(manager, message=task)

        _update_db_status(session_id, "COMPLETED")
        _publish(session_id, {"type": "status", "content": "COMPLETED"})
        sys.stderr.write(f"[WORKER] Task COMPLETED for session {session_id}\n")
        print("🎉 Task completed successfully!")

    except Exception as e:
        full_traceback = traceback.format_exc()
        sys.stderr.write(f"[WORKER ERROR] session={session_id}\n{full_traceback}\n")

        error_msg = f"{type(e).__name__}: {str(e)}"
        _update_db_status(session_id, "ERROR")
        _publish(session_id, {"type": "error", "content": error_msg})
        _publish(session_id, {"type": "log", "content": f"\n**ERROR:** {error_msg}\n\nSee worker logs for full traceback."})

    finally:
        # Always clean up temp config file
        try:
            if config_fd != -1:
                os.close(config_fd)
        except Exception:
            pass
        if os.path.exists(config_filename):
            os.remove(config_filename)
