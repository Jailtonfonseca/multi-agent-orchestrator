import streamlit as st
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
import json
import os
import io
import sys
import tempfile
import contextlib
import requests

# ── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AutoGen Team Builder",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .block-container { max-width: 1200px; padding-top: 2rem; }
    div[data-testid="stSidebar"] { background-color: #161b22; }
    .stTextArea textarea { font-family: 'Inter', monospace; }
    .status-box { padding: 12px 16px; border-radius: 8px; margin: 8px 0; }
    .status-info { background: #1a3a5c; border-left: 4px solid #3b82f6; }
    .status-success { background: #1a3c2a; border-left: 4px solid #10b981; }
    .status-error { background: #3c1a1a; border-left: 4px solid #ef4444; }
</style>
""", unsafe_allow_html=True)


# ── Tools ──────────────────────────────────────────────────────────────────────
def search_web(query: str) -> str:
    """Search the web for information using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No results found."
            return "\n".join(
                f"**{r.get('title')}**\n{r.get('href')}\n{r.get('body')}\n---"
                for r in results
            )
    except Exception as e:
        return f"Search error: {str(e)}"


def get_crypto_price(symbol: str) -> str:
    """Get the current USD price of a cryptocurrency by its CoinGecko ID (e.g. bitcoin, ethereum)."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": symbol.lower(), "vs_currencies": "usd", "include_24hr_change": "true"}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if symbol.lower() in data:
            price = data[symbol.lower()]["usd"]
            change = data[symbol.lower()].get("usd_24h_change", 0)
            return f"{symbol}: ${price:,.2f} USD (24h: {change:+.2f}%)"
        return f"Could not find price for '{symbol}'."
    except Exception as e:
        return f"Error: {str(e)}"


# ── Stdout Capture for Streamlit ───────────────────────────────────────────────
class StreamlitCapture(io.StringIO):
    def __init__(self, placeholder):
        super().__init__()
        self.placeholder = placeholder
        self.output = ""

    def write(self, s):
        if s.strip():
            self.output += s
            self.placeholder.code(self.output[-8000:], language="text")  # Trim to last 8K chars
        return len(s)

    def flush(self):
        pass


# ── Provider Config ────────────────────────────────────────────────────────────
PROVIDERS = {
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash-001", "meta-llama/llama-3.3-70b-instruct"],
    },
    "OpenAI": {
        "base_url": None,
        "models": ["gpt-4-turbo", "gpt-4o", "gpt-3.5-turbo"],
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768"],
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-coder"],
    },
}


# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.title("🤖 AutoGen Team Builder")
st.sidebar.divider()

provider = st.sidebar.selectbox("LLM Provider", list(PROVIDERS.keys()))
provider_cfg = PROVIDERS[provider]

model_name = st.sidebar.selectbox("Model", provider_cfg["models"])
custom_model = st.sidebar.text_input("Or enter custom model ID", placeholder="e.g. anthropic/claude-3-opus")
if custom_model.strip():
    model_name = custom_model.strip()

api_key = st.sidebar.text_input(f"{provider} API Key", type="password")
max_rounds = st.sidebar.slider("Max Rounds", 5, 30, 12)

st.sidebar.divider()
st.sidebar.caption("API keys are never stored on the server.")


# ── Main Area ──────────────────────────────────────────────────────────────────
st.title("🤖 AutoGen Team Builder")
st.markdown("""
Describe a task below. **AutoGen AgentBuilder** will automatically create a specialized team of AI agents
and have them collaborate to complete it. Supports **OpenRouter**, **OpenAI**, **Groq**, and **DeepSeek**.
""")

col1, col2 = st.columns([3, 1])
with col1:
    task = st.text_area(
        "Task Description",
        height=150,
        placeholder="e.g. Research the latest trends in AI agent frameworks, then write a summary report with sources."
    )
with col2:
    st.markdown("#### 💡 Examples")
    examples = [
        "Find the latest AI news and write a summary",
        "Write a Python script that generates Fibonacci numbers",
        "Compare Bitcoin and Ethereum prices and trends",
        "Create a business plan outline for an AI startup",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex[:20]}", use_container_width=True):
            st.session_state["task_prefill"] = ex
            st.rerun()

# Prefill from example buttons
if "task_prefill" in st.session_state:
    task = st.session_state.pop("task_prefill")

# ── Execute Button ─────────────────────────────────────────────────────────────
if st.button("🚀 Build Team & Execute", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ Please enter your API key in the sidebar.")
        st.stop()
    if not task:
        st.error("⚠️ Please describe a task.")
        st.stop()

    # Build config_list
    config_entry = {"model": model_name, "api_key": api_key}
    if provider_cfg["base_url"]:
        config_entry["base_url"] = provider_cfg["base_url"]
    config_list = [config_entry]
    llm_config = {"config_list": config_list, "timeout": 120, "cache_seed": None}

    # Write config to temp file (not CWD — avoids permission issues)
    config_fd, config_filename = tempfile.mkstemp(suffix=".json", prefix="OAI_")
    with os.fdopen(config_fd, "w") as f:
        json.dump(config_list, f)

    # Create temp workspace
    work_dir = tempfile.mkdtemp(prefix="autogen_ws_")

    status_text = st.empty()
    progress = st.progress(0, text="Initializing...")

    try:
        # ── Step 1: Build Agent Team ──────────────────────────────────────
        status_text.info("🔨 Initializing AgentBuilder...")
        progress.progress(10, text="Building agent team...")

        builder = AgentBuilder(
            config_file_or_env=config_filename,
            builder_model=model_name,
            agent_model=model_name
        )

        build_expander = st.expander("📋 Agent Building Logs", expanded=True)
        with build_expander:
            build_console = st.empty()
            build_capture = StreamlitCapture(build_console)

            try:
                with contextlib.redirect_stdout(build_capture):
                    agent_list, agent_configs = builder.build(
                        building_task=task,
                        default_llm_config=llm_config,
                        coding=True
                    )
            except Exception as build_err:
                st.warning(f"⚠️ AgentBuilder failed: {build_err}")
                st.info("🔄 Falling back to simple assistant mode...")

                # Fallback: single AssistantAgent
                agent_list = [
                    autogen.AssistantAgent(
                        name="Assistant",
                        llm_config=llm_config,
                        system_message="You are a highly capable AI assistant. Complete the given task thoroughly."
                    )
                ]
                agent_configs = {"agents": [{"name": "Assistant", "type": "fallback"}]}

        progress.progress(40, text="Team ready!")
        status_text.success(f"✅ Agents built: {[a.name for a in agent_list]}")

        # Show agent configs
        with st.expander("🔧 Agent Configurations"):
            st.json(agent_configs)

        # ── Step 2: Setup GroupChat ───────────────────────────────────────
        progress.progress(50, text="Setting up group chat...")

        user_proxy = autogen.UserProxyAgent(
            name="User_Proxy",
            human_input_mode="NEVER",
            code_execution_config={"use_docker": False, "work_dir": work_dir},
            max_consecutive_auto_reply=max_rounds
        )

        # Register tools
        user_proxy.register_for_execution(name="search_web")(search_web)
        user_proxy.register_for_execution(name="get_crypto_price")(get_crypto_price)

        for agent in agent_list:
            if getattr(agent, 'llm_config', False):
                try:
                    autogen.agentchat.register_function(
                        search_web,
                        caller=agent,
                        executor=user_proxy,
                        name="search_web",
                        description="Search the web for real-time information using DuckDuckGo."
                    )
                    autogen.agentchat.register_function(
                        get_crypto_price,
                        caller=agent,
                        executor=user_proxy,
                        name="get_crypto_price",
                        description="Get current USD price of a cryptocurrency by its CoinGecko ID."
                    )
                except Exception:
                    pass

        # ── Step 3: Execute ──────────────────────────────────────────────
        progress.progress(60, text="Executing task...")
        status_text.info("⚙️ Executing task... (watch the logs below)")

        log_expander = st.expander("🖥️ Execution Logs", expanded=True)
        with log_expander:
            log_placeholder = st.empty()
            log_capture = StreamlitCapture(log_placeholder)

            with contextlib.redirect_stdout(log_capture):
                if len(agent_list) == 1:
                    # Simple two-agent chat
                    user_proxy.initiate_chat(agent_list[0], message=task)
                    messages = agent_list[0].chat_messages.get(user_proxy, [])
                else:
                    # Group chat
                    groupchat = autogen.GroupChat(
                        agents=[user_proxy] + agent_list,
                        messages=[],
                        max_round=max_rounds
                    )
                    manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=llm_config)
                    user_proxy.initiate_chat(manager, message=task)
                    messages = groupchat.messages

        progress.progress(100, text="Done!")
        status_text.success("🎉 Task completed successfully!")

        # ── Step 4: Display conversation history ─────────────────────────
        st.divider()
        st.subheader("💬 Conversation History")

        for msg in messages:
            name = msg.get('name', 'Unknown')
            content = msg.get('content', '')
            if not content:
                continue

            if name == "User_Proxy":
                role, avatar = "user", "👤"
            else:
                role, avatar = "assistant", "🤖"

            with st.chat_message(role, avatar=avatar):
                st.markdown(f"**{name}**")
                st.markdown(content)

    except Exception as e:
        progress.progress(100, text="Error")
        st.error(f"❌ An error occurred: {e}")
        st.exception(e)

    finally:
        # Clean up temp files
        if os.path.exists(config_filename):
            os.remove(config_filename)
        try:
            builder.clear_all_agents()
        except Exception:
            pass
