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

# Configure Celery
# Broker and backend should be set to the redis service
app = Celery('autogen_tasks', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

# Redis Client for publishing logs
# Use a global client to avoid reconnecting on every log
redis_client = redis.Redis(host='redis', port=6379, db=0)

class RedisOutputRedirector(io.StringIO):
    """
    Redirects stdout to a Redis Pub/Sub channel.
    """
    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def write(self, s):
        # We only care about publishing, not storing in memory like StringIO
        if s.strip():
            msg = {
                "type": "log",
                "content": s
            }
            try:
                redis_client.publish(self.session_id, json.dumps(msg))
            except Exception as e:
                # Fallback to sys.stderr if redis fails, but don't crash
                sys.stderr.write(f"Redis publish error: {e}\n")
        return len(s)

@app.task(name="worker.create_team_and_execute")
def create_team_and_execute(session_id, task, api_key, model):
    """
    Celery task to run the AutoGen process.
    """
    # Create temp config file
    config_filename = f"OAI_{session_id}.json"

    try:
        # Publish START status
        redis_client.publish(session_id, json.dumps({"type": "status", "content": "BUILDING_TEAM"}))

        output_redirector = RedisOutputRedirector(session_id)

        # Ensure config setup
        config_list = [{
            "model": model,
            "api_key": api_key,
            "base_url": "https://openrouter.ai/api/v1",
        }]

        with open(config_filename, "w") as f:
            json.dump(config_list, f)

        # Ensure workspace exists
        work_dir = f"/app/workspaces/{session_id}"
        os.makedirs(work_dir, exist_ok=True)

        # Capture stdout
        with contextlib.redirect_stdout(output_redirector):
            print(f"Initializing AgentBuilder for model: {model}...")
            builder = AgentBuilder(
                config_file_or_env=config_filename,
                builder_model=model,
                agent_model=model
            )

            print("Building agents based on task...")
            try:
                agent_list, agent_configs = builder.build(
                    building_task=task,
                    default_llm_config={"config_list": config_list},
                    coding=True
                )
            except Exception as build_err:
                print(f"AgentBuilder failed: {build_err}")
                raise build_err

            # Publish EXECUTION status
            redis_client.publish(session_id, json.dumps({"type": "status", "content": "EXECUTING_TASK"}))
            print(f"Team built with {len(agent_list)} agents. Starting conversation...")

            # Setup GroupChat
            user_proxy = autogen.UserProxyAgent(
                name="User_Proxy",
                human_input_mode="NEVER",
                code_execution_config={
                    "use_docker": False,
                    "work_dir": work_dir
                },
                is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
            )

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

        # Publish COMPLETED status
        redis_client.publish(session_id, json.dumps({"type": "status", "content": "COMPLETED"}))

    except Exception as e:
        error_msg = {"type": "error", "content": str(e)}
        redis_client.publish(session_id, json.dumps(error_msg))
    finally:
        if os.path.exists(config_filename):
            try:
                os.remove(config_filename)
            except:
                pass
