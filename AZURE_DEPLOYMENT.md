# Azure App Service Deployment Guide

## Current Issues and Solutions

### 1. Environment Variables Setup
Your app requires these environment variables to be set in Azure:

**In Azure Portal → Your App Service → Configuration → Application settings:**

```
OPENAI_API_KEY=your-openai-api-key-here
SECRET_KEY=your-generated-secret-key-here
```

**To generate a SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Startup Configuration
- **Startup Command**: Set this in Azure Portal → Configuration → General settings:
  ```
  bash startup.sh
  ```

### 3. Python Version
- **Python Version**: 3.12 (as configured in your runtime.txt)
- Make sure this matches your Azure App Service Python version

### 4. Deployment Steps

1. **Commit your changes:**
   ```bash
   git add .
   git commit -m "Fix Azure deployment issues"
   git push origin main
   ```

2. **In Azure Portal:**
   - Go to your App Service
   - Go to **Deployment Center**
   - Click **Sync** to redeploy with your latest changes

3. **Set Environment Variables:**
   - Go to **Configuration** → **Application settings**
   - Add the required environment variables listed above

4. **Configure Startup Command:**
   - Go to **Configuration** → **General settings**
   - Set **Startup Command** to: `bash startup.sh`

### 5. Troubleshooting

**Check Logs:**
- Go to **Monitoring** → **Log stream** in Azure Portal
- Or check **Development Tools** → **Console** for runtime errors

**Common Issues:**
1. **"Module not found" errors**: Make sure all dependencies are in requirements.txt
2. **"Port binding" errors**: Azure sets PORT automatically, our startup script handles this
3. **"OpenAI API" errors**: Verify OPENAI_API_KEY is set correctly

**Test the Deployment:**
1. Visit your Azure URL: `personalhealthchat-b2h9b9fuhefeb9d9.canadacentral-01.azurewebsites.net`
2. Try logging in with: Username: `test`, Password: `111`
3. Start a new chat and test the AI functionality

### 6. Performance Optimization

For Azure Basic B1 plan:
- Using 1 worker process (configured in startup.sh)
- 600-second timeout for AI requests
- Minimal dependencies to reduce startup time

### 7. Security Notes

- Change default passwords in production
- Use strong SECRET_KEY
- Keep OPENAI_API_KEY secure
- Consider implementing proper authentication for production use
