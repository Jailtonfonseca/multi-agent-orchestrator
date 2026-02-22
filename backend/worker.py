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
    Redirects stdout to a Redis Pub/Sub channel.
    """
    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def write(self, s):
        if s.strip():
            msg = {
                "type": "log",
                "content": s
            }
            try:
                redis_client.publish(self.session_id, json.dumps(msg))
            except Exception as e:
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
        # Publish a specific status so the frontend knows input is needed
        # We also print the prompt so it shows up in the logs
        print(f"WAITING FOR USER INPUT: {prompt}")

        status_msg = {
            "type": "status",
            "content": "WAITING_FOR_INPUT"
        }
        redis_client.publish(self.session_id, json.dumps(status_msg))

        # Subscribe to the input channel
        pubsub = self.redis_sub.pubsub()
        pubsub.subscribe(self.input_channel)

        try:
            # Block and wait for a message
            for message in pubsub.listen():
                if message['type'] == 'message':
                    user_input = message['data'].decode('utf-8')
                    # Reset status to Executing
                    redis_client.publish(self.session_id, json.dumps({"type": "status", "content": "EXECUTING_TASK"}))
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

            # Setup GroupChat with Interactive Proxy
            # human_input_mode="ALWAYS" will trigger get_human_input every time it's the user's turn
            # or we can set it to trigger on specific conditions.
            # For true interactivity, "ALWAYS" or "TERMINATE" is best.
            # But "ALWAYS" asks after EVERY agent message, which is annoying.
            # Let's try "NEVER" first but allow interrupt? No, "NEVER" skips input.
            # "TERMINATE" asks for input only if termination condition met?
            # Ideally, we want the user to be part of the loop.
            # Let's use "ALWAYS" so the user acts as a moderator, OR use "TERMINATE" to only step in at the end.
            # Given the user wants "interaction", "ALWAYS" is safest but chatty.
            # A better UX is "TERMINATE" combined with a special check.
            # However, `AgentBuilder` agents might not loop back to user often.
            # Let's stick with "NEVER" for the *automated* flow, but that defeats the purpose.
            # The user explicitly said "I have no interaction".
            # So we MUST allow input. "TERMINATE" is a good middle ground:
            # It runs until an agent says "TERMINATE", then asks user "Do you want to continue?".
            # If user types something, it continues.

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
