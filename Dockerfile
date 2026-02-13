FROM python:3.11

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Patch transparent_background to remove GUI dependency (double protection)
RUN sed -i '/from transparent_background.gui import gui/d' \
    /usr/local/lib/python3.11/site-packages/transparent_background/__init__.py && \
    sed -i '/gui()/d' \
    /usr/local/lib/python3.11/site-packages/transparent_background/__init__.py

COPY . .

CMD ["python", "my_bot.py"]
