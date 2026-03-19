FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Arquivo gerado pelo script que cria o app FastAPI.
RUN python create_fast_api.py --mode template --output fast_api_novo.py --force

EXPOSE 8000

CMD ["uvicorn", "fast_api_novo:app", "--host", "0.0.0.0", "--port", "8000"]
