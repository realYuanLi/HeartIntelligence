FROM python:3.12-slim

# Install Node.js 20
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir Flask gunicorn gevent python-dotenv openai requests Flask-Login Flask-SQLAlchemy tiktoken nibabel numpy Pillow pypdf reportlab icalendar pycryptodome

# Install Node.js dependencies and build WhatsApp service
COPY whatsapp/package*.json whatsapp/
RUN cd whatsapp && npm install

COPY whatsapp/ whatsapp/
RUN cd whatsapp && npm run build

# Copy the rest of the app
COPY . .

# Railway sets PORT env var
ENV PORT=8000
EXPOSE 8000

# Start both services
CMD ["bash", "scripts/start.sh"]
