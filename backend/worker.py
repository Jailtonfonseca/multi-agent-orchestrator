import os
import io
import contextlib
import json
import redis
import time
import sys
from celery import Celery
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
from duckduckgo_search import DDGS
from tavily import TavilyClient
import requests
from sqlmodel import Session, select
from database import engine
from models import Session as DBSession, Log

# Configure Celery
app = Celery('autogen_tasks', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

# Redis Client
redis_client = redis.Redis(host='redis', port=6379, db=0)

# --- TOOLS ---
def search_web(query: str, tavily_key: str = None) -> str:
    if tavily_key and len(tavily_key) > 5:
        try:
            tavily = TavilyClient(api_key=tavily_key)
            response = tavily.search(query=query, search_depth="basic", max_results=5)
            results = response.get("results", [])
            if not results: return "No results found (Tavily)."
            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title')}\nURL: {r.get('url')}\nContent: {r.get('content')}\n---")
            return "\n".join(formatted_results)
        except Exception as e:
            return f"Error with Tavily: {str(e)}. Falling back to DDG."
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results: return "No results found (DDG)."
            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title')}\nURL: {r.get('href')}\nSnippet: {r.get('body')}\n---")
            return "\n".join(formatted_results)
    except Exception as e:
        return f"Error searching web: {str(e)}"

def get_crypto_price(symbol: str) -> str:
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": symbol.lower(), "vs_currencies": "usd", "include_24hr_change": "true"}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if symbol.lower() in data:
            price = data[symbol.lower()]["usd"]
            return f"The current price of {symbol} is ${price} USD."
        else:
            return f"Could not find price for '{symbol}'."
    except Exception as e:
        return f"Error fetching crypto price: {str(e)}"

class DBOutputRedirector(io.StringIO):
    """
    Redirects stdout to Redis Pub/Sub (Realtime) AND PostgreSQL (Persistence).
    """
    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def write(self, s):
        if s.strip():
            # 1. Realtime via Redis
            msg = {"type": "log", "content": s, "timestamp": time.time()}
            try:
                redis_client.publish(self.session_id, json.dumps(msg))
            except Exception:
                pass

            # 2. Persistence via Postgres
            # Using try/except to prevent logging failures from crashing the task
            try:
                # Use a fresh session per log write.
                # Since engine has connection pooling, this is relatively cheap.
                # Ideally, we would batch this, but for real-time logs, immediate write is safer against crashes.
                with Session(engine) as session:
                    log = Log(session_id=self.session_id, type="log", content=s, timestamp=time.time())
                    session.add(log)
                    session.commit()
            except Exception as e:
                # Fallback to stderr if DB fails
                sys.stderr.write(f"DB Log Error: {e}\n")

        return len(s)

class InteractiveUserProxy(autogen.UserProxyAgent):
    def __init__(self, session_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.redis_sub = redis.Redis(host='redis', port=6379, db=0)
        self.input_channel = f"input_{session_id}"

    def get_human_input(self, prompt: str) -> str:
        print(f"WAITING FOR USER INPUT: {prompt}")

        status_msg = json.dumps({"type": "status", "content": "WAITING_FOR_INPUT"})
        redis_client.publish(self.session_id, status_msg)

        # Update DB Status
        with Session(engine) as session:
            db_sess = session.get(DBSession, self.session_id)
            if db_sess:
                db_sess.status = "WAITING_FOR_INPUT"
                session.add(db_sess)
                session.commit()

        pubsub = self.redis_sub.pubsub()
        pubsub.subscribe(self.input_channel)

        try:
            # Block until message received
            for message in pubsub.listen():
                if message['type'] == 'message':
                    user_input = message['data'].decode('utf-8')

                    if user_input == "TERMINATE":
                        return "exit"

                    executing_msg = json.dumps({"type": "status", "content": "EXECUTING_TASK"})
                    redis_client.publish(self.session_id, executing_msg)

                    with Session(engine) as session:
                        db_sess = session.get(DBSession, self.session_id)
                        if db_sess:
                            db_sess.status = "EXECUTING_TASK"
                            session.add(db_sess)
                            session.commit()

                    return user_input
        finally:
            pubsub.unsubscribe(self.input_channel)
            pubsub.close()
        return ""

@app.task(name="worker.create_team_and_execute")
def create_team_and_execute(session_id, task, api_key, model, provider="openrouter", system_message=None, tavily_key=None):
    output_redirector = DBOutputRedirector(session_id)
    config_filename = f"OAI_{session_id}.json"

    try:
        start_msg = json.dumps({"type": "status", "content": "BUILDING_TEAM"})
        redis_client.publish(session_id, start_msg)

        # ... Provider Config Logic ...
        base_url = "https://openrouter.ai/api/v1"
        if provider == "openai": base_url = None
        elif provider == "groq": base_url = "https://api.groq.com/openai/v1"
        elif provider == "deepseek": base_url = "https://api.deepseek.com"

        config_list = [{"model": model, "api_key": api_key}]
        if base_url: config_list[0]["base_url"] = base_url

        with open(config_filename, "w") as f:
            json.dump(config_list, f)

        work_dir = f"/app/workspaces/{session_id}"
        os.makedirs(work_dir, exist_ok=True)

        with contextlib.redirect_stdout(output_redirector):
            print(f"Initializing AgentBuilder for model: {model}...")
            builder = AgentBuilder(config_file_or_env=config_filename, builder_model=model, agent_model=model)

            system_prompt_hint = "You are a pragmatic team builder. Agents must use the provided python environment. Use search_web tool."
            if system_message: system_prompt_hint += f"\n\nInstructions: {system_message}"
            enhanced_task = f"{system_prompt_hint}\n\nUser Task: {task}"

            agent_list, agent_configs = builder.build(building_task=enhanced_task, default_llm_config={"config_list": config_list}, coding=True)

            # DB Status Update: EXECUTING_TASK
            with Session(engine) as session:
                db_sess = session.get(DBSession, session_id)
                if db_sess:
                    db_sess.status = "EXECUTING_TASK"
                    session.add(db_sess)
                    session.commit()

            redis_client.publish(session_id, json.dumps({"type": "status", "content": "EXECUTING_TASK"}))
            print("Team built. Configuring tools...")

            user_proxy = InteractiveUserProxy(session_id=session_id, name="User_Proxy", human_input_mode="TERMINATE", code_execution_config={"use_docker": False, "work_dir": work_dir})

            def search_web_wrapper(query: str) -> str: return search_web(query, tavily_key=tavily_key)
            user_proxy.register_for_execution(name="search_web")(search_web_wrapper)
            user_proxy.register_for_execution(name="get_crypto_price")(get_crypto_price)

            for agent in agent_list:
                if getattr(agent, 'llm_config', False):
                    autogen.agentchat.register_function(search_web_wrapper, caller=agent, executor=user_proxy, name="search_web", description="Web Search")
                    autogen.agentchat.register_function(get_crypto_price, caller=agent, executor=user_proxy, name="get_crypto_price", description="Crypto Price")

            group_chat = autogen.GroupChat(agents=[user_proxy] + agent_list, messages=[], max_round=12)
            manager = autogen.GroupChatManager(groupchat=group_chat, llm_config={"config_list": config_list})

            user_proxy.initiate_chat(manager, message=task)

        # DB Status Update: COMPLETED
        with Session(engine) as session:
            db_sess = session.get(DBSession, session_id)
            if db_sess:
                db_sess.status = "COMPLETED"
                session.add(db_sess)
                session.commit()
        redis_client.publish(session_id, json.dumps({"type": "status", "content": "COMPLETED"}))

    except Exception as e:
        # DB Status Update: ERROR
        with Session(engine) as session:
            db_sess = session.get(DBSession, session_id)
            if db_sess:
                db_sess.status = "ERROR"
                session.add(db_sess)
                session.commit()
        redis_client.publish(session_id, json.dumps({"type": "error", "content": str(e)}))
    finally:
        if os.path.exists(config_filename): os.remove(config_filename)
