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

# Configure Celery
app = Celery('autogen_tasks', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

# Redis Client
redis_client = redis.Redis(host='redis', port=6379, db=0)

# --- TOOLS ---
def search_web(query: str) -> str:
    """
    Searches the web using DuckDuckGo and returns the top 5 results with snippets.
    Useful for finding real-time information, news, documentation, or facts.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No results found."

            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title')}\nURL: {r.get('href')}\nSnippet: {r.get('body')}\n---")

            return "\n".join(formatted_results)
    except Exception as e:
        return f"Error searching web: {str(e)}"

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
def create_team_and_execute(session_id, task, api_key, model):
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

        config_list = [{
            "model": model,
            "api_key": api_key,
            "base_url": "https://openrouter.ai/api/v1",
        }]

        with open(config_filename, "w") as f:
            json.dump(config_list, f)

        work_dir = f"/app/workspaces/{session_id}"
        os.makedirs(work_dir, exist_ok=True)

        with contextlib.redirect_stdout(output_redirector):
            print(f"Initializing AgentBuilder for model: {model}...")
            builder = AgentBuilder(
                config_file_or_env=config_filename,
                builder_model=model,
                agent_model=model
            )

            print("Building agents based on task...")

            system_prompt_hint = (
                "You are a pragmatic team builder. "
                "The agents you create must be grounded in reality. "
                "You have access to a 'search_web' tool. Prefer using this tool to find real-time information rather than assuming facts. "
                "Agents must use the provided python environment which has pandas, numpy, requests, duckduckgo-search, and matplotlib pre-installed. "
            )

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
            # Create User Proxy first
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

            # Register 'search_web' for all agents and user_proxy
            # This allows any agent to call the function, and user_proxy to execute it

            # Register for User Proxy (Executor)
            user_proxy.register_for_execution(name="search_web")(search_web)

            # Register for Assistants (Callers)
            for agent in agent_list:
                autogen.agentchat.register_function(
                    search_web,
                    caller=agent,
                    executor=user_proxy,
                    name="search_web",
                    description="Searches the web using DuckDuckGo. Use this to find real-time information, check facts, or get documentation."
                )
                print(f"Registered tool 'search_web' for agent: {agent.name}")

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
