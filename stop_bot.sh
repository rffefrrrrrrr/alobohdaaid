#!/bin/bash
# هذا الملف لإيقاف البوت وإدارة العمليات

if [ -f bot_pids.txt ]; then
  echo "Stopping bot processes..."
  cat bot_pids.txt | xargs kill -9
  rm bot_pids.txt
  echo "Bot processes stopped."
else
  echo "No running bot processes found."
fi
