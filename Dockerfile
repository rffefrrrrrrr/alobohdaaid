# استخدم Python 3.10
FROM python:3.10

# مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ كل الملفات للمجلد /app داخل الحاوية
COPY . .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# أمر التشغيل الرئيسي
CMD ["python", "main.py"]
