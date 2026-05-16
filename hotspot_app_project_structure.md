# hotspot_app 新项目结构说明

> 当前文档记录 `hotspot_app` 第一阶段后端迁移后的项目结构。目标是把旧项目中实际运行需要的模块整理到新项目中，减少无用文件，统一路径管理，方便后续前端联调和打包。

## 一、整体目录结构

```text
hotspot_app/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── paths.py
│   │   ├── UI/
│   │   │   ├── __init__.py
│   │   │   ├── main1.py
│   │   │   └── sqlite_utils.py
│   │   ├── common/
│   │   │   ├── __init__.py
│   │   │   ├── db_utils.py
│   │   │   ├── frame_processor.py
│   │   │   ├── freeze_processor.py
│   │   │   ├── get_config.py
│   │   │   ├── hightlight_processor.py
│   │   │   ├── line_contour_processing.py
│   │   │   ├── normal.py
│   │   │   ├── process_video.py
│   │   │   ├── read_srt.py
│   │   │   ├── rect_numbering.py
│   │   │   ├── rect_processor.py
│   │   │   ├── srt_lat_lng_range.py
│   │   │   └── video_zoom.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── common.py
│   │   │   ├── experimental.py
│   │   │   └── yolo.py
│   │   ├── utils/
│   │   │   ├── __init__.py
│   │   │   ├── augmentations.py
│   │   │   ├── autoanchor.py
│   │   │   ├── callbacks.py
│   │   │   ├── dataloaders.py
│   │   │   ├── downloads.py
│   │   │   ├── general.py
│   │   │   ├── loss.py
│   │   │   ├── metrics.py
│   │   │   ├── plots.py
│   │   │   ├── torch_utils.py
│   │   │   └── triton.py
│   │   ├── videoA/
│   │   │   ├── __init__.py
│   │   │   └── process_videoA.py
│   │   └── videoB/
│   │       ├── __init__.py
│   │       └── process_videoB.py
│   ├── config/
│   │   └── config.yaml
│   ├── data_db/
│   │   └── company_information.db
│   ├── fonts/
│   │   └── SIMHEI.TTF
│   ├── input_videos/
│   │   ├── A.mp4
│   │   ├── D.mp4
│   │   └── D.SRT
│   ├── runtime/
│   │   ├── files/
│   │   ├── output_videos/
│   │   │   └── detection_assets/
│   │   └── reports/
│   └── weights/
│       ├── best.pt
│       ├── best1.pt
│       └── best2.pt
└── frontend/                 # 后续前端迁移 / Tauri / Vue 接入时再整理
```

---

## 二、后端核心入口

```text
backend/app/main.py
```

职责：

```text
FastAPI 后端入口
注册接口路由
启动时初始化 runtime 目录
提供 /health、/detect/start、/detect/status/{task_id} 等接口
```

当前启动方式：

```bash
cd /Volumes/Mia/hotspot_app/backend
uvicorn app.main:app
```

开发调试接口时可以使用：

```bash
uvicorn app.main:app --reload
```

但跑完整检测流程时不要使用 `--reload`，否则保存代码会导致服务自动重启，中断检测任务。

---

## 三、路径统一管理

```text
backend/app/core/paths.py
```

职责：统一管理项目路径，避免代码里继续出现旧项目硬编码路径。

主要路径：

```python
APP_DIR = backend/app
BACKEND_DIR = backend
PROJECT_ROOT = hotspot_app
CONFIG_PATH = backend/config/config.yaml
DB_PATH = backend/data_db/company_information.db
REPORTS_DIR = backend/runtime/reports
OUTPUT_VIDEOS_DIR = backend/runtime/output_videos
DETECTION_ASSETS_DIR = backend/runtime/output_videos/detection_assets
FILES_DIR = backend/runtime/files
WEIGHT_BEST_PATH = backend/weights/best.pt
WEIGHT_BEST1_PATH = backend/weights/best1.pt
WEIGHT_BEST2_PATH = backend/weights/best2.pt
```

运行时目录统一通过：

```python
ensure_runtime_dirs()
```

创建。

---

## 四、配置文件

```text
backend/config/config.yaml
```

当前主要配置：

```yaml
input_path:
  videoA_path: input_videos/A.mp4
  videoB_path: input_videos/D.mp4

output_path:
  output_path: runtime/output_videos/output.mp4

srt_path:
  srt_path: input_videos/S2.SRT

detection_path:
  input_path: runtime/output_videos/report.mp4
  output_path: runtime/output_videos/detection_report.mp4
  photo_save_path: runtime/output_videos/detection_assets/D.jpg

database:
  dbname: hot_spot_detection
  user: xyy
  password: '123456'
  host: localhost
  port: '5432'
```

说明：

```text
相对路径均按 backend/ 目录解析。
videoA_path 用于拼接左侧视频 A。
/detect/start 的 input_path 一般传视频 B 的真实路径。
srt_file_path 一般传视频 B 对应的 SRT 文件路径。
```

---

## 五、数据库相关模块

### 1. SQLite 数据库

```text
backend/data_db/company_information.db
```

主要表包括：

```text
company_name
roof_info
detection_task_record
hotspot_detection_record
屋顶s1_1
芯能屋顶A_1
```

其中：

```text
company_name：公司 / 电站基础信息
roof_info：屋顶索引或屋顶基础信息
detection_task_record：检测任务记录
hotspot_detection_record：热斑管理记录
动态屋顶表：如 屋顶s1_1、芯能屋顶A_1，用于组件位置 / 热斑匹配
```

### 2. SQLite 工具模块

```text
backend/app/UI/sqlite_utils.py
```

职责：

```text
读取公司列表
读取电站列表
读取屋顶信息
写入检测任务记录
更新检测任务状态
写入 / 查询热斑管理记录
根据 SRT 经纬度匹配屋顶信息
```

当前已验证正常的接口链路：

```text
GET /station/companies
GET /station/stations
GET /station-management/stations
GET /detection-task-records
GET /hotspot-management/records
```

暂留问题：

```text
GET /station/roofs 当前可能返回空。
后续前端联调时，如果前端屋顶下拉依赖该接口，需要重新适配 roof_info 表和动态屋顶表结构。
```

### 3. PostgreSQL 工具模块

```text
backend/app/common/db_utils.py
```

职责：

```text
通过 config.yaml 读取 PostgreSQL 配置
连接 PostgreSQL
查询屋顶 / 组件相关信息
```

当前已改为使用：

```python
from app.common.get_config import get_config
from app.core.paths import CONFIG_PATH
```

---

## 六、检测主流程模块

### 1. 检测入口调度

```text
backend/app/UI/main1.py
```

职责：

```text
run_detection 主检测函数
创建输出路径
创建任务记录
调用视频 A / 视频 B 处理逻辑
更新检测任务状态
保存最终视频、报告、热斑图片路径
```

### 2. 视频 A 处理

```text
backend/app/videoA/process_videoA.py
```

职责：

```text
读取视频 A
将视频 A 写入输出视频 writer
```

### 3. 视频 B 处理

```text
backend/app/videoB/process_videoB.py
```

职责：

```text
读取视频 B
读取 SRT 文件
解析屋顶信息
逐帧调用 FrameProcessor
统计热斑组件
匹配数据库组件表
生成报告图片
插入报告图片到视频
生成热斑标注图片
生成最终标注视频
```

当前已增加调试输出：

```text
【DEBUG-屋顶组件表】roof_info
【DEBUG-屋顶组件表】selected_roof_info
【DEBUG-屋顶组件表】roof_name
【DEBUG-屋顶组件表】roof_id
【DEBUG-屋顶组件表】准备查询动态表
```

用于排查动态表名是否存在，例如：

```text
芯能屋顶A_1
屋顶s1_1
```

---

## 七、帧处理核心模块

```text
backend/app/common/frame_processor.py
```

职责：

```text
逐帧处理视频 B
识别矩形组件
识别高亮热斑区域
进行行列编号
判断卡顿 / 放大 / 稳定 / 缩小阶段
缓存最大倍率阶段画面
调用 YOLO 模型进行缺陷检测
绘制热斑标签和缺陷标注
```

当前注意点：

```text
这个文件 PyCharm 静态红线较多，多数来自 import *，不一定代表运行失败。
真实问题以终端 traceback 为准。
```

已增加防护：

```text
当 max_mag_start / max_mag_end 为空时，不再直接 None - 4 崩溃，而是打印 DEBUG 并跳过缺陷模型检测。
```

---

## 八、common 通用模块说明

```text
backend/app/common/get_config.py
```

读取 `config.yaml`。

```text
backend/app/common/process_video.py
```

读取视频元数据、创建视频写入器、释放 writer。

```text
backend/app/common/read_srt.py
```

解析 SRT 文件，提取日期、经纬度，并通过 SQLite 工具匹配屋顶信息。

```text
backend/app/common/srt_lat_lng_range.py
```

从 SRT 中提取经纬度范围和平均值。

```text
backend/app/common/normal.py
```

大型通用工具模块，包括：

```text
报告图片生成
Word 报告路径生成
YOLO 检测封装
图片插入视频
中文字体绘制
视频完整性检查
热斑数据库匹配辅助逻辑
```

```text
backend/app/common/video_zoom.py
```

放大倍率识别、ORB 特征提取、特征匹配。

```text
backend/app/common/rect_processor.py
```

矩形筛选、去重、重叠处理。

```text
backend/app/common/rect_numbering.py
```

组件矩形行列编号。

```text
backend/app/common/freeze_processor.py
```

卡顿状态检测、特征点检测、运动估计。

```text
backend/app/common/hightlight_processor.py
```

高亮热斑区域检测和筛选。

```text
backend/app/common/line_contour_processing.py
```

边缘线、轮廓、大黑区域处理。

---

## 九、YOLO 模型模块

```text
backend/app/models/
├── common.py
├── experimental.py
└── yolo.py
```

职责：YOLOv5 模型结构、模型加载、推理相关模块。

已完成迁移：

```text
models.* -> app.models.*
utils.*  -> app.utils.*
```

并移除了对 `app.export` 的依赖，避免新项目缺少 `export.py` 报错。

---

## 十、YOLO 工具模块

```text
backend/app/utils/
├── __init__.py
├── augmentations.py
├── autoanchor.py
├── callbacks.py
├── dataloaders.py
├── downloads.py
├── general.py
├── loss.py
├── metrics.py
├── plots.py
├── torch_utils.py
└── triton.py
```

职责：YOLOv5 推理和工具依赖。

已完成迁移：

```text
utils.*  -> app.utils.*
models.* -> app.models.*
```

未迁移旧项目中的以下目录：

```text
autobatch.py
aws/
docker/
flask_rest_api/
google_app_engine/
loggers/
segment/
```

原因：当前第一阶段只需要推理检测，不需要训练、云部署、日志平台、分割模型等功能。

---

## 十一、资源目录

### 1. 权重目录

```text
backend/weights/
├── best.pt
├── best1.pt
└── best2.pt
```

说明：

```text
best.pt：默认 YOLO 权重
best1.pt / best2.pt：旧项目中保留的其他检测权重
```

### 2. 字体目录

```text
backend/fonts/SIMHEI.TTF
```

说明：

```text
中文绘制统一从 backend/fonts/SIMHEI.TTF 读取。
已经清理 ../../fonts、./fonts 等不稳定路径。
```

### 3. 输入视频目录

```text
backend/input_videos/
├── A.mp4
├── D.mp4
└── D.SRT
```

说明：

```text
A.mp4：视频 A
D.mp4：视频 B
D.SRT：视频 B 对应字幕文件
```

---

## 十二、运行产物目录

```text
backend/runtime/
├── files/
├── output_videos/
│   └── detection_assets/
└── reports/
```

说明：

```text
runtime/output_videos：检测输出视频
runtime/output_videos/detection_assets：报告图片、热斑现场图、标注图
runtime/reports：Word 报告
runtime/files：运行中间文件或接口下载文件
```

后续打包时，`runtime/` 应作为可写目录处理，不建议放进只读资源区。

---

## 十三、当前已验证接口

已验证通过：

```text
GET  /health
GET  /station/companies
GET  /station/stations
GET  /station-management/stations
GET  /detection-task-records
GET  /hotspot-management/records
POST /detect/start
GET  /detect/status/{task_id}
```

暂留待修：

```text
GET /station/roofs
```

原因：当前数据库中屋顶信息和动态屋顶组件表之间的关系还需要结合前端选择逻辑进一步确认。

---

## 十四、当前启动方式

开发启动：

```bash
cd /Volumes/Mia/hotspot_app/backend
uvicorn app.main:app --reload
```

完整检测测试启动：

```bash
cd /Volumes/Mia/hotspot_app/backend
uvicorn app.main:app
```

说明：

```text
跑完整检测时不要使用 --reload。
--reload 会在保存 Python 文件时自动重启服务，导致后台检测任务中断。
```

---

## 十五、后续 TODO

```text
1. 全局搜索旧路径残留：scripts.*、utils.*、models.*、../../fonts、/Users/xyy、旧项目路径。
2. 修复 /station/roofs 查询逻辑。
3. 清理 runtime 外散落的调试输出目录，例如 max_magnification_mid_half_*。
4. 前端接入新后端接口。
5. 打包前处理 weights、fonts、config、data_db、runtime 可写目录。
6. 减少 frame_processor.py 中 import *，后续重构为显式导入。
7. 将大型 normal.py 拆分为 report、font、video、detect、database_match 等子模块。
```
