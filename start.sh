#!/bin/bash

# تعيين المسار الحالي
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# تعيين متغيرات البيئة
export PYTHONUNBUFFERED=1

# وظيفة لتشغيل البوت
run_bot() {
    echo "بدء تشغيل البوت في: $(date)"
    python3 main.py "$@"
}

# وظيفة للتحقق من حالة البوت
check_bot() {
    if pgrep -f "python3 main.py" > /dev/null; then
        return 0  # البوت يعمل
    else
        return 1  # البوت متوقف
    fi
}

# وظيفة لإعادة تشغيل البوت
restart_bot() {
    echo "إعادة تشغيل البوت في: $(date)"
    pkill -f "python3 main.py" || true
    sleep 2
    run_bot "$@"
}

# وظيفة keepalive
keepalive() {
    while true; do
        if ! check_bot; then
            echo "البوت متوقف. إعادة التشغيل في: $(date)"
            run_bot "$@"
        else
            echo "البوت يعمل بشكل طبيعي في: $(date)"
        fi
        sleep 60  # التحقق كل دقيقة
    done
}

# تشغيل البوت مع keepalive في الخلفية
run_with_keepalive() {
    # تشغيل البوت
    run_bot "$@" &
    
    # تشغيل keepalive في الخلفية
    keepalive "$@" &
    
    # كتابة معرفات العمليات إلى ملف
    echo $! > bot_keepalive.pid
    
    echo "تم تشغيل البوت مع keepalive في الخلفية"
    echo "استخدم './start.sh stop' لإيقاف البوت"
}

# إيقاف البوت
stop_bot() {
    echo "إيقاف البوت في: $(date)"
    if [ -f bot_keepalive.pid ]; then
        KEEPALIVE_PID=$(cat bot_keepalive.pid)
        kill $KEEPALIVE_PID 2>/dev/null || true
        rm bot_keepalive.pid
    fi
    pkill -f "python3 main.py" || true
    echo "تم إيقاف البوت بنجاح"
}

# عرض حالة البوت
status_bot() {
    if check_bot; then
        echo "البوت يعمل حالياً"
        ps aux | grep "python3 main.py" | grep -v grep
    else
        echo "البوت متوقف حالياً"
    fi
}

# معالجة الأوامر
case "$1" in
    start)
        shift
        run_with_keepalive "$@"
        ;;
    stop)
        stop_bot
        ;;
    restart)
        shift
        stop_bot
        sleep 2
        run_with_keepalive "$@"
        ;;
    status)
        status_bot
        ;;
    *)
        # إذا لم يتم تحديد أمر، قم بتشغيل البوت مع keepalive
        run_with_keepalive "$@"
        ;;
esac

exit 0
