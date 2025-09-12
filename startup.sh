#!/usr/bin/env bash
exec gunicorn --bind=0.0.0.0${PORT} --timeout 600 app:app
