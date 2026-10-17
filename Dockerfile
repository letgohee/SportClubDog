FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
ENV DB_PATH=/app/data/sessions.db
VOLUME /app/data
CMD ["python", "-m", "bot.main"]
