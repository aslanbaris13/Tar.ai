#!/bin/bash
# Kullanım: ./run.sh agents/agent_3_news.py
source "$(dirname "$0")/.venv/bin/activate"
python3 "$@"
