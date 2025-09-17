# DREAM-Chat Deployment Guide

This guide will help you deploy your DREAM-Chat application to Railway for free with a publicly accessible URL.

## Prerequisites

1. A GitHub account
2. A Railway account (free tier available)
3. An OpenAI API key (for AI functionality)

## Step 1: Prepare Your Repository

1. **Commit your changes** to Git:
   ```bash
   git add .
   git commit -m "Prepare for deployment"
   git push origin main
   ```

2. **Generate a secret key** for Flask sessions:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Save this key - you'll need it for deployment.

## Step 2: Deploy to Railway

### Option A: Deploy via Railway Dashboard (Recommended)

1. **Go to [Railway.app](https://railway.app)** and sign up/login
2. **Click "New Project"** → **"Deploy from GitHub repo"**
3. **Select your DREAM-Chat repository**
4. **Railway will automatically detect** it's a Python app and use the `Procfile`

### Option B: Deploy via Railway CLI

1. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   ```

2. **Login to Railway**:
   ```bash
   railway login
   ```

3. **Deploy your app**:
   ```bash
   railway deploy
   ```

## Step 3: Configure Environment Variables

In your Railway dashboard:

1. **Go to your project** → **Variables tab**
2. **Add these environment variables**:

   ```
   SECRET_KEY=your-generated-secret-key-here
   OPENAI_API_KEY=your-openai-api-key-here
   ```

   - `SECRET_KEY`: Use the key you generated in Step 1
   - `OPENAI_API_KEY`: Your OpenAI API key for AI functionality

## Step 4: Access Your App

1. **Railway will provide a URL** like: `https://your-app-name.railway.app`
2. **Your app will be publicly accessible** at this URL
3. **Default login credentials**:
   - Username: `Kevin` or `Fang`
   - Password: `123456`

## Step 5: Custom Domain (Optional)

1. **In Railway dashboard** → **Settings** → **Domains**
2. **Add your custom domain** (if you have one)
3. **Configure DNS** as instructed by Railway

## Free Tier Limits

Railway's free tier includes:
- ✅ **$5 credit monthly** (usually enough for small apps)
- ✅ **512MB RAM**
- ✅ **1GB storage**
- ✅ **Custom domains**
- ✅ **Automatic HTTPS**
- ✅ **Zero-downtime deployments**

## Troubleshooting

### Build Timeout Issues
If you're experiencing build timeouts, try these solutions:

1. **Use the minimal requirements** (already configured):
   - The current `requirements.txt` has been optimized to only include essential dependencies
   - Heavy packages like `torch`, `transformers`, and `langchain` have been removed for deployment

2. **Alternative deployment platforms** if Railway still times out:
   - **Render.com**: Similar to Railway, good for Python apps
   - **Heroku**: Classic platform, has free tier limitations
   - **Fly.io**: Fast deployment, good for Python apps

3. **If you need the full dependencies**:
   - Use `requirements-full.txt` for local development
   - Consider using a paid Railway plan for faster builds
   - Or deploy to a platform with longer build timeouts

### App Won't Start
- Check the **Deployments** tab in Railway for error logs
- Ensure all environment variables are set correctly
- Verify your `requirements.txt` includes all dependencies
- Check that the port is set correctly (Railway sets `$PORT` automatically)

### AI Features Not Working
- Verify your `OPENAI_API_KEY` is set correctly
- Check that you have sufficient OpenAI API credits
- The app will fall back to dummy responses if OpenAI is not configured

### Performance Issues
- Monitor your usage in Railway dashboard
- Consider upgrading to a paid plan if you exceed free tier limits
- The app is configured to use minimal resources (1 worker, optimized timeouts)

## Security Notes

- **Change default passwords** in production
- **Use strong SECRET_KEY** for Flask sessions
- **Keep your OpenAI API key secure**
- **Consider implementing proper user authentication** for production use

## Support

- **Railway Documentation**: https://docs.railway.app
- **Railway Discord**: https://discord.gg/railway
- **Railway Status**: https://status.railway.app

---

Your DREAM-Chat app should now be live and accessible to anyone with the URL! 🚀
