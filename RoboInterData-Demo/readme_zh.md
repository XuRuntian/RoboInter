# RoboInterData-Demo 使用说明

本文说明如何克隆主分支、安装依赖，并用本地数据启动可视化工具。

## 1. 克隆主分支

完整拉取 main 分支和所有文件：

```bash
git clone --branch main https://github.com/XuRuntian/RoboInter.git
cd RoboInter/RoboInterData-Demo
```

## 2. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

## 3. 准备数据

需要准备两个路径：

- `/path/to/human_anno_lang`：标注目录，里面应包含 `demo_data/`
- `/path/to/videos`：视频目录，里面应包含 `.mp4` 文件

## 4. 快速启动

```bash
ROBOINTER_DEMO_LMDB=/path/to/human_anno_lang/demo_data \
  ROBOINTER_DEMO_VIDEO_ROOT=/path/to/videos \
  python3 app.py
```

如果你的环境里 `python` 已指向 Python 3，也可以把最后一行改成：

```bash
python app.py
```

启动后在浏览器打开：

```text
http://localhost:7860
```

如果端口被占用，可以换一个端口：

```bash
GRADIO_SERVER_PORT=8860 python3 app.py
```
