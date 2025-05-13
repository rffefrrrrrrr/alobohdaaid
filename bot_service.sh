#!/bin/bash

# تعريف المتغيرات
BOT_DIR="/home/ubuntu/telegram_bot/final_bot"
BOT_SCRIPT="bot.py"
LOG_FILE="$BOT_DIR/bot_service.log"
PID_FILE="$BOT_DIR/bot.pid"
TOKEN="7792142434:AAFPwfOx-6eULS6J1IAQ0wO0GO1cUtbIW3U"
CHECK_INTERVAL=60  # التحقق كل دقيقة

# التأكد من وجود المجلدات اللازمة
mkdir -p "$BOT_DIR/data"

# دالة لبدء تشغيل البوت
start_bot() {
    echo "$(date): Starting bot..." >> "$LOG_FILE"
    
    # التحقق مما إذا كان البوت يعمل بالفعل
    if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null; then
        echo "$(date): Bot is already running with PID $(cat $PID_FILE)" >> "$LOG_FILE"
        return 0
    fi
    
    # بدء تشغيل البوت
    cd "$BOT_DIR"
    nohup python3 "$BOT_SCRIPT" "$TOKEN" > bot_output.log 2>&1 &
    
    # حفظ معرف العملية
    echo $! > "$PID_FILE"
    echo "$(date): Bot started with PID $!" >> "$LOG_FILE"
}

# دالة لإيقاف البوت
stop_bot() {
    echo "$(date): Stopping bot..." >> "$LOG_FILE"
    
    # التحقق مما إذا كان ملف PID موجودًا
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        
        # التحقق مما إذا كانت العملية لا تزال قيد التشغيل
        if ps -p $PID > /dev/null; then
            echo "$(date): Killing process $PID" >> "$LOG_FILE"
            kill $PID
            sleep 2
            
            # التحقق مما إذا كانت العملية لا تزال قيد التشغيل وإجبارها على الإنهاء إذا لزم الأمر
            if ps -p $PID > /dev/null; then
                echo "$(date): Force killing process $PID" >> "$LOG_FILE"
                kill -9 $PID
            fi
        else
            echo "$(date): Process $PID is not running" >> "$LOG_FILE"
        fi
        
        # إزالة ملف PID
        rm "$PID_FILE"
    else
        echo "$(date): PID file not found" >> "$LOG_FILE"
        
        # محاولة العثور على عمليات البوت وإنهائها
        BOT_PIDS=$(ps aux | grep "python3 $BOT_SCRIPT" | grep -v grep | awk '{print $2}')
        if [ ! -z "$BOT_PIDS" ]; then
            echo "$(date): Found bot processes: $BOT_PIDS" >> "$LOG_FILE"
            for pid in $BOT_PIDS; do
                echo "$(date): Killing process $pid" >> "$LOG_FILE"
                kill $pid
                sleep 1
                if ps -p $pid > /dev/null; then
                    echo "$(date): Force killing process $pid" >> "$LOG_FILE"
                    kill -9 $pid
                fi
            done
        fi
    fi
    
    echo "$(date): Bot stopped" >> "$LOG_FILE"
}

# دالة للتحقق من حالة البوت وإعادة تشغيله إذا لزم الأمر
check_bot() {
    echo "$(date): Checking bot status..." >> "$LOG_FILE"
    
    # التحقق مما إذا كان ملف PID موجودًا
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        
        # التحقق مما إذا كانت العملية لا تزال قيد التشغيل
        if ps -p $PID > /dev/null; then
            echo "$(date): Bot is running with PID $PID" >> "$LOG_FILE"
        else
            echo "$(date): Bot process $PID is not running, restarting..." >> "$LOG_FILE"
            rm "$PID_FILE"
            start_bot
        fi
    else
        echo "$(date): PID file not found, starting bot..." >> "$LOG_FILE"
        start_bot
    fi
}

# دالة لتشغيل البوت في وضع المراقبة المستمرة
run_watchdog() {
    echo "$(date): Starting watchdog mode..." >> "$LOG_FILE"
    
    # بدء تشغيل البوت أولاً
    start_bot
    
    # حلقة لا نهائية للتحقق من حالة البوت
    while true; do
        check_bot
        sleep $CHECK_INTERVAL
    done
}

# معالجة الأوامر
case "$1" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        sleep 2
        start_bot
        ;;
    status)
        if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null; then
            echo "Bot is running with PID $(cat $PID_FILE)"
        else
            echo "Bot is not running"
        fi
        ;;
    watchdog)
        # تشغيل في وضع المراقبة المستمرة
        run_watchdog
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|watchdog}"
        exit 1
        ;;
esac

exit 0
