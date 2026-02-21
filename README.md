# 🤖 AutoGen Production App (React + FastAPI)

A robust, production-ready implementation of an Autonomous Agent Team Builder. This application moves beyond simple prototypes, offering a scalable microservices architecture that decouples the frontend, backend, and heavy AI processing tasks.

## 🏗️ Architecture

![Architecture Diagram](https://mermaid.ink/img/pako:eNp1kcFqwzAMhl8l6NRChx022GHQYYesu4ySg1FjaWJbOQ5lTPDdd5K2W06FIPz6T9LPSF6sQoG04W3lG_RaYTfKBytPVqE4-sEOGhVvLDr08m1l0KGP44QzLniG3mFw8BNa_x96_Qk9TviEPY7Y44S3eMZbPOHtiLd4xod4xod4wYd4wYf4yYf4yU_4yU_4J37CP_E_uF85W4W2QoH0t2qF0qJShbLRqEJZ71ShrDeqUNY7VSjrnSqU9U4VynqnCmW9U4Wy3qlCWe9Uoax3qlDWO1Uo650qlPVO1f8A5qVzNw)

*   **Frontend**: React (Create React App) - Provides a responsive, modern UI for task input and real-time log visualization.
*   **Backend**: FastAPI - A high-performance async API that handles requests and manages WebSocket connections for log streaming.
*   **Worker**: Celery + Redis - Executes the heavy `AutoGen` processes in the background, preventing API blocking and allowing for horizontal scaling.
*   **Broker/Cache**: Redis - Acts as the message broker for Celery and the Pub/Sub channel for real-time logs.

## 🚀 Features

*   **Asynchronous Execution**: Long-running agent tasks are offloaded to background workers.
*   **Real-time Log Streaming**: WebSocket integration delivers agent conversation logs to the UI instantly via Redis Pub/Sub.
*   **Scalable**: The worker service can be scaled independently of the web server.
*   **Robust Error Handling**: Dedicated status tracking and error reporting.
*   **Dockerized**: Fully containerized environment ensuring consistency and easy deployment.

## 🛠️ Tech Stack

*   **Frontend**: React, Axios, WebSocket
*   **Backend**: Python, FastAPI, Uvicorn
*   **Task Queue**: Celery
*   **Broker**: Redis
*   **AI Framework**: Microsoft AutoGen

## 📋 Prerequisites

*   **Docker** and **Docker Compose** installed on your machine.
*   An **OpenRouter API Key** with credits.

## 🏃‍♂️ Installation & Usage

1.  **Clone the Repository**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Start the Application**
    Run the container using Docker Compose:
    ```bash
    docker-compose up -d --build
    ```
    *Note: The first build may take a few minutes as it installs dependencies for both Python and Node.js.*

3.  **Access the Interface**
    Open your browser and navigate to:
    ```
    http://localhost:3000
    ```

4.  **Usage**
    *   Enter your **OpenRouter API Key**.
    *   Select your preferred **LLM Model**.
    *   Describe your task.
    *   Click **Build Team & Execute** and watch the logs stream in real-time!

## 🔧 Development

*   **Backend Logs**: `docker-compose logs -f backend`
*   **Worker Logs**: `docker-compose logs -f worker`
*   **Frontend Logs**: `docker-compose logs -f frontend`

The source code is mounted as volumes, so changes to `backend/` or `frontend/src/` will often trigger auto-reloads (depending on the specific file changed and configuration).
