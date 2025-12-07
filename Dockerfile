FROM python:3.11-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    default-jdk \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install apktool
RUN wget https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool -O /usr/local/bin/apktool && \
    wget https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_2.9.3.jar -O /usr/local/bin/apktool.jar && \
    chmod +x /usr/local/bin/apktool

# Install uber-apk-signer
RUN wget https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /usr/local/bin/uber-apk-signer.jar && \
    echo '#!/bin/bash\njava -jar /usr/local/bin/uber-apk-signer.jar "$@"' > /usr/local/bin/uber-apk-signer && \
    chmod +x /usr/local/bin/uber-apk-signer

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Run the bot
CMD ["python", "bot.py"]
