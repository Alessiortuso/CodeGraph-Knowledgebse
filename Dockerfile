# Usiamo una versione leggera di Python
FROM python:3.10-slim

# Installiamo Git e gli strumenti di compilazione per gqlalchemy
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Creiamo la cartella di lavoro
WORKDIR /app

# Copiamo i requisiti e li installiamo
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiamo tutto il resto del codice
COPY . .

# Comando per avviare il tuo main con output non bufferizzato
CMD ["python", "-u", "main.py"]