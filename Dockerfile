# استخدم نسخة بايثون الرسمية (ليست slim أو alpine)
FROM python:3.11

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
