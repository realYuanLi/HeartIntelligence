# DREAM-Chat

A health-focused AI platform providing personalized medical insights and interactive data visualization.

## Core Functionality

- **Health-Centric AI Chat**: Personalized assistant that analyzes your medical history, clinical records, and mobile health data to provide tailored insights.
- **Interactive Health Dashboard**: A comprehensive view of clinical data and Apple Health metrics (Steps, Heart Rate, HRV, etc.) with real-time analysis.
- **"My Body" CT Visualization**: Interactive 3D visualization of CT scans and organ segmentations for better understanding of personal anatomy.
- **Voice Interaction**: Integrated speech-to-text for natural conversation about your health.

## Quick Start

1. **Install dependencies**: `pip install -r requirements.txt`
2. **Configure API**: Set your OpenAI API key in `functions/agent.py`
3. **Run application**: `./startup.sh` or `python3 app.py`
4. **Access**: Navigate to `http://localhost:8000` and login.

## Project Structure

- `app.py`: Main Flask application and API routing.
- `functions/`: AI agent logic, health data analyzers, and web search integration.
- `templates/`: Dynamic UI including Chat, Dashboard, and CT Viewer.
- `static/`: Modern styles and frontend logic.
- `data/`: Integrated storage for patient profiles, mobile health records, and imaging data.
