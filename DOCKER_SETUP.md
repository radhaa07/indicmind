# 🐳 Docker Setup Guide for ContractLens

This guide will help you run ContractLens using Docker and Docker Compose.

## Prerequisites

1. **Install Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
   - Download from: https://www.docker.com/products/docker-desktop
   - Make sure Docker is running

2. **Verify Docker installation**:
   ```bash
   docker --version
   docker-compose --version
   ```

## Quick Start

### 1. Configure Environment Variables

First, make sure your `.env` file is properly configured:

```bash
# Copy the example file if you haven't already
copy .env.example .env
```

Edit `.env` with your actual API keys and configuration:
```env
GEMINI_API_KEY=your-actual-gemini-api-key
FLASK_SECRET_KEY=your-random-secret-key
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

### 2. Build and Run with Docker Compose

**Option A: Run with Ollama (Recommended for offline AI)**
```bash
docker-compose up -d
```

This will start:
- ContractLens app on http://localhost:5000
- Ollama local AI service on http://localhost:11434

**Option B: Run without Ollama (Use only Gemini API)**
```bash
docker-compose up -d contractlens
```

### 3. Access the Application

Open your browser and go to:
```
http://localhost:5000
```

### 4. Pull Ollama Model (If using Ollama)

If you're running with Ollama, pull the required model:

```bash
# Enter the Ollama container
docker exec -it contractlens-ollama ollama pull llama3.2

# Or use a different model
docker exec -it contractlens-ollama ollama pull mistral
```

## Docker Commands Cheat Sheet

### Basic Operations

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f contractlens

# Restart services
docker-compose restart

# Rebuild after code changes
docker-compose up -d --build
```

### Troubleshooting

```bash
# Check running containers
docker ps

# Enter the app container
docker exec -it contractlens-app bash

# View app logs
docker-compose logs contractlens

# Check Ollama status
docker exec -it contractlens-ollama ollama list

# Remove all containers and volumes (FRESH START)
docker-compose down -v
```

### Database Access

```bash
# Access SQLite database inside container
docker exec -it contractlens-app sqlite3 contractlens.db

# Or copy database to your local machine
docker cp contractlens-app:/app/contractlens.db ./contractlens_backup.db
```

## Configuration Details

### Volumes (Persistent Data)

The following directories are mounted as volumes to persist data:

- `./uploads` - Uploaded contract files
- `./contractlens.db` - SQLite database
- `./tts_cache` - Text-to-speech cache
- `./models` - Translation models (NLLB)

### Networking

- **ContractLens App**: Port 5000
- **Ollama**: Port 11434
- Both services are on the same Docker network for communication

### Environment Variables

Key environment variables in `docker-compose.yml`:

```yaml
OLLAMA_HOST=http://ollama:11434  # Use service name in Docker network
FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
GEMINI_API_KEY=${GEMINI_API_KEY}
```

## Production Deployment

For production deployment, consider:

1. **Use a production WSGI server** (Gunicorn):
   
   Update `Dockerfile` CMD to:
   ```dockerfile
   CMD python -c "from app import init_db; init_db()" && \
       gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```
   
   Add to `requirements.txt`:
   ```
   gunicorn>=21.0,<22.0
   ```

2. **Use PostgreSQL instead of SQLite**:
   
   Add to `docker-compose.yml`:
   ```yaml
   postgres:
     image: postgres:15
     environment:
       POSTGRES_DB: contractlens
       POSTGRES_USER: contractlens
       POSTGRES_PASSWORD: your-secure-password
     volumes:
       - postgres-data:/var/lib/postgresql/data
   ```

3. **Add reverse proxy (Nginx)**:
   
   ```yaml
   nginx:
     image: nginx:alpine
     ports:
       - "80:80"
       - "443:443"
     volumes:
       - ./nginx.conf:/etc/nginx/nginx.conf
   ```

4. **Enable HTTPS** with Let's Encrypt

5. **Set secure secrets** - Never commit real secrets to Git

## Common Issues

### Issue: Port already in use
```bash
# Change the port in docker-compose.yml
ports:
  - "5001:5000"  # Use port 5001 instead
```

### Issue: Ollama connection fails
```bash
# Make sure Ollama is running
docker ps | grep ollama

# Check if model is downloaded
docker exec -it contractlens-ollama ollama list

# Update OLLAMA_HOST in .env to:
OLLAMA_HOST=http://ollama:11434
```

### Issue: Database locked
```bash
# Restart the container
docker-compose restart contractlens
```

### Issue: Tesseract language missing
```bash
# Enter container and install language
docker exec -it contractlens-app bash
apt-get update && apt-get install -y tesseract-ocr-spa  # Example for Spanish
```

## Updating the Application

When you make code changes:

```bash
# Rebuild and restart
docker-compose up -d --build

# Or full rebuild without cache
docker-compose build --no-cache
docker-compose up -d
```

## Backup and Restore

### Backup
```bash
# Backup database
docker cp contractlens-app:/app/contractlens.db ./backup/contractlens_$(date +%Y%m%d).db

# Backup uploads
docker cp contractlens-app:/app/uploads ./backup/uploads_$(date +%Y%m%d)
```

### Restore
```bash
# Restore database
docker cp ./backup/contractlens_20260827.db contractlens-app:/app/contractlens.db

# Restart app
docker-compose restart contractlens
```

## Resource Limits

To set resource limits, add to `docker-compose.yml`:

```yaml
services:
  contractlens:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

## Monitoring

### View resource usage
```bash
docker stats
```

### Health check
Add to `docker-compose.yml`:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5000/"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## Need Help?

- Check logs: `docker-compose logs -f`
- Verify environment: `docker exec contractlens-app env`
- Test connection: `docker exec contractlens-app ping ollama`

---

**Happy Dockerizing! 🐳**
