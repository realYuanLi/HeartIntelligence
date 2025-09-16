# AI Chat App

A Flask-based web application that provides a general-purpose AI chatbot powered by OpenAI models. The chatbot can help with a wide variety of tasks including answering questions, problem-solving, creative writing, and more.

## Features

- **AI Assistant**: General-purpose conversational chatbot powered by OpenAI models
- **Session Management**: Create, save, and manage multiple chat sessions
- **User Authentication**: Simple login system for users
- **Conversation History**: Persistent chat history with customizable session titles
- **Responsive Web Interface**: Clean, modern UI with breathing dots animation

## Quick Start

### Prerequisites

- Python 3.8+
- OpenAI API key

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd AI-Chat
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the application**
   - Set your OpenAI API key in `functions/agent.py` (replace `"your-openai-api-key-here"`)
   - Available models are configured in `config/configs.json`
   - Default users are configured in `app.py` (Kevin/123456, Fang/123456)

4. **Run the application**
   ```bash
   python3 app.py
   ```
   
   Or use the startup script:
   ```bash
   chmod +x startup.sh
   ./startup.sh
   ```

5. **Access the application**
   - Open your browser to `http://localhost:8000`
   - Login with default credentials (Kevin/123456 or Fang/123456)
   - Start a new chat session and begin interacting with the AI assistant

## Configuration

- **API Key**: Set your OpenAI API key in `functions/agent.py`
- **Models**: Available models (gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo) are listed in `config/configs.json`
- **System Prompt**: The AI assistant behavior is defined in the config file
- **Users**: Add/modify users in the `USERS` dictionary in `app.py`

## Project Structure

```
AI-Chat/
├── app.py                 # Main Flask application
├── functions/agent.py     # AI agent implementation
├── config/configs.json    # Model and prompt configuration
├── templates/             # HTML templates
├── static/               # CSS and JavaScript files
├── requirements.txt      # Python dependencies
└── startup.sh           # Production startup script
```

## Development

The application runs in development mode by default. For production deployment, use the provided `startup.sh` script with Gunicorn.