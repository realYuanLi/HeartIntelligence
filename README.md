# AI Chat App

A Flask-based web application that provides a general-purpose AI chatbot powered by OpenAI models. The chatbot can help with a wide variety of tasks including answering questions, problem-solving, creative writing, and more.

## Features

- **AI Assistant**: General-purpose conversational chatbot powered by OpenAI models
- **Session Management**: Create, save, and manage multiple chat sessions
- **User Authentication**: Simple login system for users
- **Conversation History**: Persistent chat history with customizable session titles
- **Responsive Web Interface**: Clean, modern UI with breathing dots animation
- **Speech-to-Text**: Voice input with real-time transcription (optional)

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

## Speech-to-Text Feature (Optional)

The application includes an integrated speech-to-text transcription feature powered by pywhispercpp.

### Installation

To enable speech-to-text functionality:

```bash
pip install git+https://github.com/absadiki/pywhispercpp
```

**Note:** Additional system dependencies may be required depending on your platform. Refer to the [pywhispercpp repository](https://github.com/absadiki/pywhispercpp) for details.

### Usage

1. **Start Recording**: Click the microphone icon (🎤) in the input box
   - The button will turn red and pulse to indicate recording is active
   - The input box border will animate to show recording status
   - The placeholder text will change to "Listening..."

2. **Stop Recording**: Click the microphone button again
   - Recording stops and transcribed text appears in the input box
   - You can edit the transcribed text before sending
   - The text is added to any existing content in the input box

3. **Send Message**: Click the send button or press Enter to send the transcribed message

The speech-to-text feature works on both the welcome page and chat page, allowing you to use voice input anywhere in the application.

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