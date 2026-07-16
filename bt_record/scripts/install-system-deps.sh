#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y \
  v4l-utils \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  python3-gi \
  python3-gst-1.0
