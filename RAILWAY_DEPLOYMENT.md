# Railway Deployment Guide for DREAM-Chat

## Prerequisites
- Railway account
- OpenAI API key

## Required Environment Variables

Set these environment variables in your Railway project dashboard:

### 1. **OPENAI_API_KEY** (Required)
- Your OpenAI API key
- Get it from: https://platform.openai.com/api-keys
- Example: `sk-proj-...`
- **Without this, the chatbot will not work!**

### 2. **SECRET_KEY** (Recommended)
- Flask session secret key
- Generate a random string for security
- Example: `your-random-secret-key-here`
- If not set, will use default (not secure for production)

### 3. **PORT** (Optional)
- Railway automatically sets this
- Default: 8000

## Deployment Steps

### Step 1: Configure Environment Variables
1. Go to your Railway project dashboard
2. Click on your service
3. Go to "Variables" tab
4. Add the following variables:
   ```
   OPENAI_API_KEY=sk-proj-your-api-key-here
   SECRET_KEY=your-random-secret-key
   ```

### Step 2: Deploy from GitHub
1. Connect your GitHub repository to Railway
2. Railway will automatically detect the Python app and use:
   - Build command: `pip install --no-cache-dir -r requirements.txt`
   - Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1`

### Step 3: Monitor Deployment
1. Check the deployment logs for:
   - `✓ OpenAI API key is configured`
   - `✓ Chatbot initialized with model: gpt-4o`
   - `✓ Loaded EHR data with X records` (if EHR data file is present)
   
2. Look for warnings:
   - `⚠ WARNING: OPENAI_API_KEY environment variable is not set!`
   - `⚠ EHR data file not found` (this is OK if you don't have health data)

## Troubleshooting Common Issues

### Issue 1: "Sorry, there was an error processing your message" (Some questions work, others fail)

**Cause:** Timeout issues with complex health-related queries

**Why this happens:**
- Simple questions work fine (e.g., "What is diabetes?")
- Personal health questions fail (e.g., "What are my medications?", "How is my health?")
- Health queries load large EHR data (829K lines) and run multiple AI analyses
- This can exceed the request timeout (now increased to 300 seconds)

**Solutions Applied:**
1. ✅ Increased gunicorn timeout from 120s to 300s (5 minutes)
2. ✅ Added gevent async worker for better concurrency
3. ✅ Limited EHR data extraction to max 100 items total and 10 per category
4. ✅ Added 180s timeout protection for data summarization
5. ✅ Graceful fallback to category summaries if full analysis times out

**If still timing out:**
- Reduce EHR data file size
- Use a smaller sample dataset
- Consider breaking large queries into smaller, specific questions

### Issue 2: Missing or Invalid OpenAI API Key

**Cause:** `OPENAI_API_KEY` not set in Railway

**Solution:**
1. Verify `OPENAI_API_KEY` is set in Railway environment variables
2. Check that the API key is valid and has credits
3. Check Railway logs for the specific error message

**Verify in logs:**
```bash
⚠ WARNING: OPENAI_API_KEY environment variable is not set!
```

### Issue 2: Memory Issues / Deployment Crashes

**Cause:** Large EHR data file (829,608 lines) exceeds Railway's memory limits

**Solutions:**
- **Option A:** Reduce the size of `data/test_file/ehr_test_data.json`
- **Option B:** Exclude the file from deployment by modifying `.gitignore`:
  ```gitignore
  # Comment out or remove these lines:
  # !data/test_file/ehr_test_data.json
  data/test_file/ehr_test_data.json
  ```
- **Option C:** Upgrade to a Railway plan with more memory

### Issue 3: Health Data Features Not Working

**Cause:** EHR data file not deployed or too large

**Solution:**
The app will work without EHR data, but health analysis features will be limited. You'll see:
```
⚠ EHR data file not found - health data features will be limited
```

This is expected if you excluded the large data file.

### Issue 4: Rate Limiting Errors

**Cause:** Too many requests to OpenAI API

**Solution:**
- The app now returns: "The AI service is currently experiencing high demand. Please try again in a moment."
- Wait a few seconds and retry
- Consider upgrading your OpenAI API plan

## Health Check

Once deployed, test your application:

1. **Basic Health Check:**
   ```
   curl https://your-app.railway.app/health
   ```
   Should return:
   ```json
   {
     "status": "healthy",
     "ehr_data_available": true/false,
     "ehr_records": 0
   }
   ```

2. **Login Test:**
   - Navigate to your app URL
   - Try logging in with test credentials:
     - Username: `test`
     - Password: `111`

3. **Chat Test:**
   - After login, start a new chat
   - Send a simple message like "Hello"
   - If you see a response, the deployment is successful!

## Performance Optimization

### For Better Performance:
1. **Reduce EHR data size** - Only include necessary records
2. **Use Railway's Pro plan** - More memory and CPU
3. **Enable persistent storage** - For chat history across deployments

### Memory Usage:
- Minimal (no EHR data): ~150-200 MB
- With full EHR data: ~500-800 MB
- Medical imaging features: Additional ~200-400 MB

## Security Notes

1. **Change default passwords** in `app.py`:
   ```python
   USERS = {"Kevin": "123456", "Yuan": "3456", "test": "111"}
   ```
   
2. **Set a strong SECRET_KEY** in environment variables

3. **Don't commit** `.env` files or API keys to git (already in `.gitignore`)

## Support

If issues persist:
1. Check Railway deployment logs
2. Look for error messages starting with `⚠`
3. Verify all environment variables are set correctly
4. Test OpenAI API key locally first

## Monitoring

Railway provides:
- Real-time logs
- Resource usage metrics
- Automatic deployments on git push

Monitor your deployment at: https://railway.app/dashboard
