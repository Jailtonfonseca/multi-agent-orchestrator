# 🤖 AutoGen Enterprise (Microservices)

A scalable, production-ready platform for **building and managing autonomous AI agent teams**. Describe a task in natural language and watch a team of specialized AI agents collaborate, search the web, and execute code to complete it — in real time.

Built with a modern microservices architecture featuring real-time WebSocket streaming, persistent session history, human-in-the-loop interaction, and a clean React SPA.

---

## 🌟 Key Features

| Feature | Description |
|---|---|
| 🤖 **Agent Team Builder** | AutoGen `AgentBuilder` automatically assembles a team of specialized agents for each task |
| 💬 **Human-in-the-Loop** | Execution pauses when agents need input; reply directly from the UI |
| 🌐 **Web Search** | Agents use Tavily (preferred) or DuckDuckGo for real-time web research |
| ⚡ **Real-Time Streaming** | Logs stream instantly via WebSocket with auto-reconnect |
| 📦 **Session History** | All sessions and logs are persisted in PostgreSQL; browse history from the sidebar |
| 🔌 **Multi-Provider** | Works with OpenRouter, OpenAI, Groq, and DeepSeek |

---

## 🏗️ Architecture

```
Browser (React SPA)
    │  REST + WebSocket
    ▼
FastAPI Backend ──► Celery Worker ──► AutoGen AgentBuilder
    │                   │
    ▼                   ▼
PostgreSQL           Redis (Broker + Pub/Sub)
```

- **Frontend**: React 18 SPA with sidebar navigation, real-time log viewer, and WebSocket client
- **Backend**: FastAPI — REST endpoints, WebSocket relay, session management
- **Worker**: Celery + AutoGen — agent orchestration, tool execution, code running
- **Storage**: PostgreSQL (sessions & logs) + Redis (message broker & pub/sub)
- **Tools**: Adminer at `:8080` for DB inspection

---

## 🚀 Quick Start

### Prerequisites
- [Docker & Docker Compose](https://docs.docker.com/get-docker/)
- An API key from one of the supported providers:
  - [OpenRouter](https://openrouter.ai/keys) *(recommended — access to all models)*
  - [OpenAI](https://platform.openai.com/api-keys)
  - [Groq](https://console.groq.com/)
  - [DeepSeek](https://platform.deepseek.com/)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Jailtonfonseca/multi-agent-orchestrator.git
cd multi-agent-orchestrator

# 2. (Optional) Copy and edit environment config
cp .env.example .env

# 3. Launch the full stack
docker-compose up -d --build

# 4. Check that all services are healthy
docker-compose ps
```

### Open the App

Navigate to **http://localhost:3000**

---

## 📖 Usage Guide

1. **Click "⚙️ Settings"** in the sidebar
   - Enter your API key for your chosen provider
   - Optionally add a Tavily key for better web search
   - Optionally set a global system prompt

2. **Click "✦ New Task"** in the sidebar
   - Select your **Provider** and **Model ID** (e.g. `openai/gpt-4o`, `anthropic/claude-3-opus`)
   - Describe what you want the agent team to accomplish

3. **Start the task** — watch agents build a team and execute in real time
   - Status transitions: `🔨 Building Team` → `⚙️ Executing Task` → `✅ Completed`
   - If status shows `💬 Waiting for you`, type a reply to guide the agents

4. **Browse history** — click any session in the sidebar to reload its full log

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://autogen:autogen123@db:5432/autogen_db` | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `MAX_ROUNDS` | `12` | Max group chat rounds per task |
| `WORKSPACES_DIR` | `/tmp/workspaces` | Directory for agent code execution |
| `REACT_APP_API_URL` | `http://localhost:8000` | Backend URL seen by the browser |

---

## 🔧 Technical Details

### Session Persistence
- `session` table: metadata (task, model, status, created_at)
- `log` table: every log line with timestamp, type (`log`, `status`, `error`)

### Human-in-the-Loop
The backend uses a custom `InteractiveUserProxy` that overrides AutoGen's `get_human_input`. It pauses execution, publishes a `WAITING_FOR_INPUT` status to Redis, and blocks until a message arrives on the `input_{session_id}` channel — triggered by the frontend's `/api/reply` endpoint.

### WebSocket Auto-Reconnect
The React frontend automatically reconnects the WebSocket if the connection drops during an active task, preventing log gaps on network hiccups.

### Tools Available to Agents
| Tool | Description |
|---|---|
| `search_web` | Web search via Tavily or DuckDuckGo |
| `get_crypto_price` | Live cryptocurrency prices via CoinGecko |
| *Python executor* | Agents can write and run Python code in the worker container |

---

## 🛡️ Security Notes

> [!WARNING]
> **Code Execution Sandbox**: Agents currently execute code inside the Worker container. For public/multi-user production deployment, implement **Docker-in-Docker** or container sandboxing to isolate agent code execution.

> [!NOTE]
> API keys are passed per-request from the browser's `localStorage` and never stored on the server. For a multi-user deployment, implement OAuth2 authentication and server-side encrypted key storage.

---

## 📊 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/start-task` | Start a new agent task |
| `POST` | `/api/reply` | Send human input to a waiting task |
| `POST` | `/api/stop-task/{id}` | Stop a running task |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get single session metadata |
| `GET` | `/api/sessions/{id}/logs` | Get all logs for a session |
| `WS` | `/ws/{id}` | Real-time log stream |
| `GET` | `/health` | Deep health check (Redis + DB) |

---

## 🗺️ Roadmap

- [ ] **Auth**: JWT / OAuth2 for multi-user support
- [ ] **Docker-in-Docker**: Fully isolated code execution sandbox
- [ ] **More Tools**: File upload, image generation, database query tools
- [ ] **Metrics**: Prometheus + Grafana dashboard
- [ ] **CI/CD**: GitHub Actions for automated build and test
