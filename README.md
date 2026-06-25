# Bt_record

Run gstreamer pipe that capture the camera and stream the video
Allow to attach record branch that save the stream from the camera to local path

The application and simple web site with single html file that allow to manage save videos

- start
- stop
- download
- status
- remove remote files

!!! Note

The idea of this project is the to allow record (raw/mp4) , the encoding control and streaming is out off scope


## Build
using uv to build the project as whl file
The `whl` locate in dist folder

```bash
uv build --wheel
```

## Install

```bash title="install gstreamer"
sudo apt install -y \
  python3-gi \
  python3-gst-1.0 \
  gir1.2-gstreamer-1.0 \
  gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly
```

```bash title="install apt dependencies"

sudo apt install -y \
  pkg-config \
  libcairo2-dev \
  libgirepository-2.0-dev \
  gobject-introspection \
  python3-dev \
  build-essential
```
```bash
# install uv from internet
curl -LsSf https://astral.sh/uv/install.sh | sh
# add automatic to /.bashrc
source $HOME/.local/bin/env
```


## Config
Set the UDP stream destination IP from the command line.

| config field  |  desc |
|---|---|
| --stream-ip  | client ip to stream to (port 5600)  |


## usage

```
uv run bt-gst-record
```

```bash
uv run bt-gst-record --stream-ip 10.0.0.17
```

### Web

![alt text](docs/images/web.png)


### Receiver pipe
```
gst-launch-1.0 -v \
  udpsrc port=5600 caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! \
  rtph264depay ! \
  h264parse ! \
  avdec_h264 ! \
  videoconvert ! \
  autovideosink sync=false
```
