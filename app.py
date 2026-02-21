import streamlit as st
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
import json
import os
import io
import sys
import contextlib

# Set page configuration
st.set_page_config(page_title="AutoGen Team Builder", layout="wide")

# Sidebar for Configuration
st.sidebar.title("Configuration")
api_key = st.sidebar.text_input("OpenRouter API Key", type="password")
model_name = st.sidebar.selectbox("Model", ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"])

# Main Area
st.title("AutoGen Team Builder")
st.markdown("""
This application uses **Microsoft AutoGen** to automatically build a team of agents tailored to your task.
It uses **OpenRouter** as the LLM provider.
""")

task = st.text_area("Task Description", height=150, placeholder="e.g. Find the latest news about AI agent frameworks and summarize the key trends.")

# Helper class to capture stdout and display it in Streamlit
class StreamlitCapture(io.StringIO):
    def __init__(self, placeholder):
        super().__init__()
        self.placeholder = placeholder
        self.output = ""

    def write(self, s):
        # Filter out some specific irrelevant internal logs if needed, but keeping all for now
        self.output += s
        # Update the placeholder with the current accumulated output
        # usage of code block to simulate terminal
        self.placeholder.code(self.output, language="text")

    def flush(self):
        pass

if st.button("Build Team & Execute"):
    if not api_key:
        st.error("Please provide an OpenRouter API Key in the sidebar.")
    elif not task:
        st.error("Please provide a task description.")
    else:
        # Configuration for OpenRouter
        config_list = [
            {
                "model": model_name,
                "api_key": api_key,
                "base_url": "https://openrouter.ai/api/v1"
            }
        ]

        llm_config = {"config_list": config_list}

        # Create a temporary OAI_CONFIG_LIST file for AgentBuilder
        config_filename = "OAI_CONFIG_LIST_temp.json"
        with open(config_filename, "w") as f:
            json.dump(config_list, f)

        status_text = st.empty()
        status_text.info("Initializing AgentBuilder...")

        try:
            # Initialize AgentBuilder
            builder = AgentBuilder(
                config_file_or_env=config_filename,
                builder_model=model_name,
                agent_model=model_name
            )

            status_text.info(f"Building agents for task: {task[:50]}...")

            # Build agents
            # We redirect stdout here too because AgentBuilder might print logs
            build_output_placeholder = st.expander("Agent Building Logs", expanded=True)
            with build_output_placeholder:
                build_console = st.empty()
                build_capture = StreamlitCapture(build_console)

                with contextlib.redirect_stdout(build_capture):
                    agent_list, agent_configs = builder.build(
                        building_task=task,
                        default_llm_config=llm_config
                    )

            status_text.success(f"Agents built successfully: {[agent.name for agent in agent_list]}")

            # Display agent configurations
            with st.expander("View Agent Configurations"):
                st.json(agent_configs)

            # Setup GroupChat
            # Create a UserProxyAgent to initiate the chat
            user_proxy = autogen.UserProxyAgent(
                name="User_Proxy",
                human_input_mode="NEVER",
                code_execution_config={"use_docker": False, "work_dir": "web"},
            )

            # Combine user proxy with built agents
            group_agents = [user_proxy] + agent_list

            # Create GroupChat and Manager
            groupchat = autogen.GroupChat(agents=group_agents, messages=[], max_round=20)
            manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=llm_config)

            status_text.info("Executing task... (Check 'Execution Logs' below)")

            # Create a placeholder for real-time execution logs
            log_expander = st.expander("Execution Logs", expanded=True)
            with log_expander:
                log_placeholder = st.empty()
                capture = StreamlitCapture(log_placeholder)

                # Execute the chat and capture stdout
                with contextlib.redirect_stdout(capture):
                    user_proxy.initiate_chat(
                        manager,
                        message=task
                    )

            status_text.success("Execution complete!")

            # Display the conversation history in a nice chat format
            st.divider()
            st.subheader("Conversation History")

            for msg in groupchat.messages:
                # msg contains 'role', 'content', 'name'
                name = msg.get('name', 'Unknown')
                content = msg.get('content', '')

                # Determine role for Streamlit
                if name == "User_Proxy":
                    role = "user"
                    avatar = "👤"
                else:
                    role = "assistant"
                    avatar = "🤖"

                with st.chat_message(role, avatar=avatar):
                    st.markdown(f"**{name}**: {content}")

        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.exception(e)

        finally:
            # Clean up
            if os.path.exists(config_filename):
                os.remove(config_filename)
            # Try to clear agents if possible to free resources
            try:
                builder.clear_all_agents()
            except:
                pass
