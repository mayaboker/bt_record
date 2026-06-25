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

## Config
for the version we need to set manual the stream ip address

| config field  |  desc |
|---|---|
| DEST_STREAM_IP  | client ip to stream to (port 5600)  |


## usage

```
uv run bt-gst-record
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