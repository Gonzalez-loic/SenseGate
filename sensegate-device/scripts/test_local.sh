#!/usr/bin/env bash
set -e
curl -s http://127.0.0.1:5000/api/health | python3 -m json.tool
curl -s http://127.0.0.1:5000/api/stats | python3 -m json.tool
