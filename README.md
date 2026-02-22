# 🤖 AutoGen Enterprise (Microservices)

A scalable, production-ready platform for building and managing autonomous AI agent teams. Built with a modern microservices architecture, it features real-time interaction, session persistence, and a robust task execution engine.

![Architecture Diagram](https://mermaid.ink/img/pako:eNp1kcFqwzAMhl8l6NRChx022GHQYYesu4ySg1FjaWJbOQ5lTPDdd5K2W06FIPz6T9LPSF6sQoG04W3lG_RaYTfKBytPVqE4-sEOGhVvLDr08m1l0KGP44QzLniG3mFw8BNa_x96_Qk9TviEPY7Y44S3eMZbPOHtiLd4xod4xod4wYd4wYf4yYf4yU_4yU_4J37CP_E_uF85W4W2QoH0t2qF0qJShbLRqEJZ71ShrDeqUNY7VSjrnSqU9U4VynqnCmW9U4Wy3qlCWe9Uoax3qlDWO1Uo650qlPVO1f8A5qVzNw)

## 🌟 Key Features

*   **Interactive Chat Sessions**: Not just "fire and forget". The system pauses when agents need input, allowing you to guide the team mid-task.
*   **Web Search Capability**: Agents are equipped with `duckduckgo-search` to access real-time information and prevent hallucinations.
*   **Session History**: All tasks and logs are persisted in Redis. Switch between past sessions via the Sidebar, just like ChatGPT.
*   **Model Agnostic**: Use **any** OpenRouter model (GPT-4o, Claude 3.5, Llama 3 70B, etc.) by simply typing its ID.
*   **Real-Time Streaming**: Watch agents think and converse instantly via WebSockets.
*   **Scalable Architecture**: Decoupled Frontend, Backend, and Worker services.

## 🏗️ Architecture

*   **Frontend**: React (SPA) with Sidebar navigation and WebSocket integration.
*   **Backend**: FastAPI for REST endpoints and WebSocket management.
*   **Worker**: Celery + Redis for asynchronous agent orchestration.
*   **Storage**: Redis (Hash/List) for session metadata and persistent log history.

## 🚀 Quick Start

### Prerequisites
*   Docker & Docker Compose
*   [OpenRouter API Key](https://openrouter.ai/keys)

### Installation

1.  **Clone the repo**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Launch the stack**
    ```bash
    docker-compose up -d --build
    ```

3.  **Open the App**
    Navigate to `http://localhost:3000`

### Usage Guide

1.  **Create a New Task**: Click "+" in the sidebar.
2.  **Configure**:
    *   **API Key**: Enter your OpenRouter key.
    *   **Model**: Type the model ID (e.g., `openai/gpt-4o`, `anthropic/claude-3-opus`, `meta-llama/llama-3-70b-instruct`).
    *   **Task**: Describe what you want the team to do.
3.  **Interact**:
    *   Watch the logs stream.
    *   If the status changes to `WAITING FOR INPUT`, type your reply in the input box to guide the agents.
4.  **Review**: Click on any past session in the sidebar to load its full conversation history.

## 🔧 Technical Details

### Session Persistence
Sessions are stored in Redis:
*   `session:{id}` (Hash): Metadata (Task, Model, Status, CreatedAt).
*   `logs:{id}` (List): JSON objects of every log line and user interaction.
*   `all_sessions` (List): Ordered list of session IDs for the sidebar.

### Human-in-the-Loop
The backend uses a custom `InteractiveUserProxy` that overrides AutoGen's `get_human_input`. It pauses execution, publishes a status update to Redis, and waits for a message on a dedicated `input_{session_id}` channel, which is triggered by the Frontend's `/api/reply` endpoint.

### Tools & Capabilities
Agents are automatically provisioned with the `search_web` tool, powered by `duckduckgo-search`. This allows them to perform unlimited, key-free web searches to gather data, verify facts, or find documentation, significantly reducing "hallucinations" (invented facts).

## 🛡️ Security Notes
*   **Execution Sandbox**: Currently, agents run code inside the Worker container. For public production use, you **must** implement Docker-in-Docker sandboxing to isolate agent code execution.
*   **API Keys**: Keys are passed per request. In a multi-user environment, implement OAuth2 and encrypted key storage.
