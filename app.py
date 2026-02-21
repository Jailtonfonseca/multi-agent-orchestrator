import streamlit as st
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
import os
import json
import sys
import io
import re
import contextlib
import time
import logging
import uuid

# --- Configure Streamlit ---
st.set_page_config(page_title="AutoGen Team Builder", layout="wide", page_icon="🤖")

# --- Helper Class for Stdout Capture ---
class StreamlitRedirector(io.StringIO):
    """
    A custom output redirector that captures stdout and updates a Streamlit container.
    It parses AutoGen's standard output format to render nicely formatted chat messages.
    """
    def __init__(self, container_func, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container_func = container_func  # Function to get the current container
        self.buffer = ""
        self.current_speaker = None
        self.current_message = ""
        self.logs = [] # Store raw logs for debugging/fallback
        self.messages = [] # Store parsed messages for the session

    def write(self, s):
        # Write to the internal buffer for standard behavior
        ret = super().write(s)
        self.buffer += s
        self.logs.append(s)

        # Process the buffer line by line to handle real-time updates
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self._parse_and_render(line)

        return ret

    def _parse_and_render(self, line):
        # Regex to detect "Sender (to Receiver):"
        match = re.search(r'^(.*?) \(to (.*?)\):\s*$', line)

        if match:
            # If we were accumulating a message, save it
            if self.current_speaker:
                self._save_message()

            # Start a new message
            self.current_speaker = match.group(1)
            self.current_receiver = match.group(2)
            self.current_message = "" # Reset message content
        else:
            # It's content or system log
            # Filter out the divider lines
            if line.strip().startswith('----------------'):
                return

            # If we have an active speaker, append to the message
            if self.current_speaker:
                self.current_message += line + "\n"
                # Update the UI in real-time (streaming effect)
                # Note: This might be flickery, so we usually update largely on completion or chunks
                # For this implementation, we will update the container directly
                # But to avoid massive flicker, we just wait for the block to finish or stream strictly
                # For simplicity, we just save to buffer and render on completion of block in _save_message
                pass
            else:
                # System log (e.g. "TERMINATE" or builder logs)
                pass

    def _save_message(self):
        """Saves the completed message to the session history."""
        if self.current_speaker and self.current_message.strip():
            msg_data = {
                "role": self.current_speaker,
                "content": self.current_message.strip(),
                "avatar": "🤖" if "User" not in self.current_speaker else "👤"
            }
            # Add to session state for persistence
            if "messages" not in st.session_state:
                st.session_state.messages = []
            st.session_state.messages.append(msg_data)

            # Render immediately to the container
            with self.container_func():
                with st.chat_message(msg_data["role"], avatar=msg_data["avatar"]):
                    st.markdown(msg_data["content"])

    def flush(self):
        # Handle remaining buffer
        if self.buffer:
            self._parse_and_render(self.buffer)
            self.buffer = ""
        # Save any pending message
        if self.current_speaker:
            self._save_message()
            self.current_speaker = None
        super().flush()


# --- Main Application Logic ---

def get_config_list(api_key, model):
    return [
        {
            "model": model,
            "api_key": api_key,
            "base_url": "https://openrouter.ai/api/v1",
        }
    ]

def main():
    # --- Sidebar ---
    with st.sidebar:
        st.header("Configuration")
        api_key = st.text_input("OpenRouter API Key", type="password", help="Enter your OpenRouter API Key.")
        model_options = ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-pro-1.5", "Other..."]
        selected_model = st.selectbox("Select Model", model_options, index=0)

        if selected_model == "Other...":
            model = st.text_input("Enter Custom Model Name (OpenRouter ID)", placeholder="e.g., meta-llama/llama-3-70b-instruct")
        else:
            model = selected_model

        st.info("Ensure the model supports function calling for best results with AutoGen.")

        reset_btn = st.button("Reset Session")
        if reset_btn:
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

    # --- Main Area ---
    st.title("🤖 Autonomous Team Builder")
    st.markdown("""
    Describe a complex task, and I will build a team of agents to solve it.
    """)

    task = st.text_area("Enter your task:", height=150, placeholder="e.g., Create a Python script to scrape stock prices for 'AAPL' and plot them using matplotlib.")

    start_btn = st.button("Build Team & Execute", type="primary")

    # --- State Management ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "logs" not in st.session_state:
        st.session_state.logs = []

    # --- Execution Logic ---
    if start_btn and task and api_key:
        st.session_state.messages = [] # Clear previous messages
        st.session_state.logs = []     # Clear previous logs

        config_list = get_config_list(api_key, model)

        # Create a unique config file for this session/run
        config_filename = f"OAI_CONFIG_LIST_{uuid.uuid4()}.json"
        with open(config_filename, "w") as f:
            json.dump(config_list, f)

        llm_config = {"config_list": config_list}

        # Ensure work directory exists
        os.makedirs("coding", exist_ok=True)

        # 1. Build the Team
        builder_container = st.expander("Building Team...", expanded=True)
        main_container = st.container()

        try:
            with builder_container:
                st.write("Initializing AgentBuilder...")
                builder = AgentBuilder(
                    config_file_or_env=config_filename,
                    builder_model=model,
                    agent_model=model
                )

                with st.spinner("Building agents based on your task... (This may take a minute)"):
                    # Capture stdout during build
                    captured_build_logs = io.StringIO()
                    with contextlib.redirect_stdout(captured_build_logs):
                         agent_list, agent_configs = builder.build(
                            building_task=task,
                            default_llm_config=llm_config,
                            coding=False
                        )
                    st.text(captured_build_logs.getvalue())
                    st.success(f"Built {len(agent_list)} agents!")

                    # Display Agent Details
                    for agent in agent_list:
                        st.info(f"**{agent.name}**: {agent.system_message[:100]}...")

            # 2. Execute the Task
            st.divider()
            st.subheader("Agent Conversation")

            # Create a container for the chat
            chat_container = st.container()

            def get_container():
                return chat_container

            # Initialize our custom redirector
            output_redirector = StreamlitRedirector(get_container)

            with st.spinner("Agents are working..."):
                try:
                    # Manually setup GroupChat since AgentBuilder (0.2.x) build() just returns agents

                    # Create a UserProxyAgent to act as the trigger
                    user_proxy = autogen.UserProxyAgent(
                        name="User_Proxy",
                        human_input_mode="NEVER",
                        code_execution_config={"use_docker": False, "work_dir": "coding"},
                        is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
                    )

                    # Create GroupChat
                    # Include the user_proxy and the built agents
                    group_chat = autogen.GroupChat(
                        agents=[user_proxy] + agent_list,
                        messages=[],
                        max_round=12
                    )

                    manager = autogen.GroupChatManager(
                        groupchat=group_chat,
                        llm_config=llm_config
                    )

                    # Redirect stdout to our custom class
                    with contextlib.redirect_stdout(output_redirector):
                        # Initiate chat
                        user_proxy.initiate_chat(
                            manager,
                            message=task
                        )

                    # Ensure buffer is flushed
                    output_redirector.flush()

                except Exception as e:
                    st.error(f"Error during execution: {e}")
                    st.exception(e)

        except Exception as e:
            st.error(f"Error initializing builder: {e}")
            st.exception(e)
        finally:
            if os.path.exists(config_filename):
                os.remove(config_filename)

    elif start_btn and not api_key:
        st.warning("Please provide an OpenRouter API Key.")

    # --- Render History (if not running) ---
    # If we are just refreshing the page, show the history
    if not start_btn and st.session_state.messages:
        st.subheader("Agent Conversation History")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"], avatar=msg["avatar"]):
                st.markdown(msg["content"])

if __name__ == "__main__":
    main()
