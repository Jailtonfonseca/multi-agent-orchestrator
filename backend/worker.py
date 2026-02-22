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
app = Celery('autogen_tasks', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

# Redis Client
redis_client = redis.Redis(host='redis', port=6379, db=0)

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

            # Publish for real-time subscribers
            try:
                redis_client.publish(self.session_id, msg_json)
            except Exception:
                pass

            # Persist for history (RPUSH to list logs:{session_id})
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
        # Need a fresh connection for subscribing
        self.redis_sub = redis.Redis(host='redis', port=6379, db=0)
        self.input_channel = f"input_{session_id}"

    def get_human_input(self, prompt: str) -> str:
        """
        Overrides the default input method to wait for a message on the Redis channel.
        """
        print(f"WAITING FOR USER INPUT: {prompt}")

        status_msg = {
            "type": "status",
            "content": "WAITING_FOR_INPUT"
        }
        msg_json = json.dumps(status_msg)

        # Publish and Persist Status
        redis_client.publish(self.session_id, msg_json)
        redis_client.rpush(f"logs:{self.session_id}", msg_json)

        # Subscribe to the input channel
        pubsub = self.redis_sub.pubsub()
        pubsub.subscribe(self.input_channel)

        try:
            # Block and wait for a message
            for message in pubsub.listen():
                if message['type'] == 'message':
                    user_input = message['data'].decode('utf-8')

                    # Reset status to Executing
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
    # Create temp config file
    config_filename = f"OAI_{session_id}.json"

    # Store session metadata in Redis Hash
    session_data = {
        "id": session_id,
        "task": task[:50] + "..." if len(task) > 50 else task,
        "model": model,
        "created_at": time.time(),
        "status": "BUILDING_TEAM"
    }
    redis_client.hset(f"session:{session_id}", mapping=session_data)
    # Add to list of all sessions for easy retrieval
    redis_client.lpush("all_sessions", session_id)

    try:
        # Publish START status
        start_msg = json.dumps({"type": "status", "content": "BUILDING_TEAM"})
        redis_client.publish(session_id, start_msg)
        redis_client.rpush(f"logs:{session_id}", start_msg)

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

            # Update Status
            redis_client.hset(f"session:{session_id}", "status", "EXECUTING_TASK")
            exec_msg = json.dumps({"type": "status", "content": "EXECUTING_TASK"})
            redis_client.publish(session_id, exec_msg)
            redis_client.rpush(f"logs:{session_id}", exec_msg)

            print(f"Team built with {len(agent_list)} agents. Starting conversation...")

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

        # Complete
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
