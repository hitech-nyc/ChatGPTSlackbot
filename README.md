# ChatGPT-Slack Integration Server

This repository contains a server that integrates ChatGPT with Slack, allowing users to interact with various bots through Slack. The server is built using FastAPI and hosts multiple environments for different conversational contexts.

## Features

- Hosts ChatGPT on Slack for interactive bot responses.
- Supports multiple environments with different mindsets.
- Logs messages and interactions for review.
- Manages user permissions and access control.

## Files

- `slack_chatbot.py`: Main server script handling requests and responses.
- `chatbot2_settings.json`: Configuration file for different environments and user settings.

## Setup

### Prerequisites

- Python 3.8 or higher.
- Slack API token.
- OpenAI API token.

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/your-repo/chatgpt-slack-integration.git
   cd chatgpt-slack-integration
   pip install -r requirements.txt
   export SLACKAPI_KEY=your-slack-api-token
   export OPENAI_KEY=your-openai-api-token
   ```

### Configuration
Update the chatbot2_settings.json file with your environment settings and user configurations.

## Adding Users
Users and their permissions are managed in the chatbot2_settings.json file. Update the users section with the relevant user information and their access status.


### Running the Server
Start the server using Uvicorn:

```
nohup uvicorn slack_chatbot:app --host 0.0.0.0 --port 8000
```


### Usage
## Endpoints
- "POST /:" Default endpoint for handling Slack events in production environment.
- "POST /mamaru:" Endpoint for handling Slack events in the MamaRu environment.
- "POST /testbench:" Endpoint for handling Slack events in the testbench environment.


### Logging
Logs are stored in the file specified in the logging_path for each environment. These logs include message interactions and error messages for debugging.



