#!/bin/bash

# تسجيل بداية التشغيل
echo "Starting keep-alive script at $(date)"

# تشغيل خادم keep_alive_http.py في الخلفية
echo "Starting keep_alive_http.py in background at $(date)"
python3 keep_alive_http.py &
KEEP_ALIVE_PID=$!
echo "Started keep_alive_http.py with PID: $KEEP_ALIVE_PID"

# انتظار بضع ثوانٍ للتأكد من أن خادم الويب قد بدأ
sleep 5

# تشغيل البوت الرئيسي (bot.py)
echo "Starting main bot (bot.py) at $(date)"
python3 bot.py

# إذا توقف البوت الرئيسي، قم بإيقاف خادم keep_alive أيضاً
echo "Main bot (bot.py) stopped at $(date). Stopping keep_alive_http.py"
kill $KEEP_ALIVE_PID

