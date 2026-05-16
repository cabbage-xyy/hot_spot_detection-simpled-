# 前后端联调入口：先只做“导入视频路径 -> 后端收到路径”的最小链路
from datetime import datetime
import shutil
import re
import socket
import argparse
import atexit
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.UI.main1 import run_detection
from app.common.normal import global_normal_infos
from app.UI.sqlite_utils import (
    add_detection_task_record,
    add_hotspot_detection_record,
    add_station_management_info,
    delete_detection_task_record_by_id,
    delete_hotspot_detection_record_by_id,
    delete_station_management_info_by_id,
    get_all_company_names,
    get_id_by_company_name,
    get_roof_info_by_roof_name,
    get_roof_name_by_station_name,
    get_station_name_by_company_id,
    select_all_infos,
    select_detection_task_records,
    select_hotspot_detection_records,
    update_detection_task_record,
    update_hotspot_detection_record,
    update_station_management_info_by_id,
)
from app.core.paths import (
    BACKEND_PORT_PATH,
    DETECTION_ASSETS_DIR,
    OUTPUT_VIDEOS_DIR,
    REPORTS_DIR,
    ensure_runtime_dirs,
)

app = FastAPI()

# ====== 动态端口：启动时自动扫描可用端口 ======
# 全局变量保存实际启动端口，供 Tauri/Rust 层通过 backend_port.txt 读取
ACTUAL_PORT: int = 8000


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """检查指定端口是否可用（未被占用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_available_port(start_port: int = 8000, end_port: int = 9000, host: str = "127.0.0.1") -> int:
    """从 start_port 开始扫描，返回第一个可用端口。"""
    for port in range(start_port, end_port + 1):
        if is_port_available(port, host):
            return port
    raise RuntimeError(f"在 {start_port}-{end_port} 范围内未找到可用端口")


def _get_port_file_path() -> Path:
    """获取 backend_port.txt 的路径，统一写入 backend/runtime 目录。"""
    ensure_runtime_dirs()
    return BACKEND_PORT_PATH


def write_port_file(port: int) -> Path:
    """将实际启动端口写入当前工作目录下的 backend_port.txt，供 Tauri/Rust 层读取。"""
    port_file = _get_port_file_path()
    port_file.write_text(str(port), encoding="utf-8")
    print(f"[动态端口] 已将实际端口 {port} 写入 {port_file}")
    return port_file


def remove_port_file() -> None:
    """进程退出时删除端口文件。"""
    port_file = _get_port_file_path()
    try:
        if port_file.exists():
            port_file.unlink()
            print(f"[动态端口] 已删除端口文件 {port_file}")
    except Exception as exc:
        print(f"[动态端口] 删除端口文件失败: {exc}")


# 允许 Vue / Tauri 开发环境访问 Python 后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class DetectStartRequest(BaseModel):
    input_path: str
    output_path: str | None = None
    srt_file_path: str = ""
    company_name: str = ""
    station_name: str = ""
    roof_name: str = ""



class ReportExportRequest(BaseModel):
    save_path: str


# 新增: 用于视频与屋顶信息验证的请求模型
class ValidateVideoRoofRequest(BaseModel):
    input_path: str
    company_name: str
    station_name: str
    roof_name: str


class StationManagementSaveRequest(BaseModel):
    company_name: str
    station_name: str
    station_address: str = ""
    roof_number: str | int = ""
    roof_name: str
    size: str = ""
    type: str = ""
    person: str = ""
    weather: str = ""
    longitude: str | float | None = None
    latitude: str | float | None = None
    min_longitude: str | float | None = None
    max_longitude: str | float | None = None
    min_latitude: str | float | None = None
    max_latitude: str | float | None = None
    status: str = "运行中"
    original_roof_name: str | None = None



class StationManagementDeleteRequest(BaseModel):
    company_name: str = ""
    station_name: str = ""
    roof_name: str = ""
    company_id: int | None = None


class HotspotRecordUpdateRequest(BaseModel):
    process_status: str | None = None
    report_status: str | None = None
    report_path: str | None = None
    defect_summary: str | None = None
    hotspot_component_count: int | None = None


# 简单内存任务表：开发联调用，记录每次检测任务的状态

DETECTION_TASKS: dict[str, dict[str, Any]] = {}


# Helper to find the latest report file (.docx or .doc) in relevant directories
def find_latest_report_file() -> Path | None:
    latest_generated_report = str(global_normal_infos.get("report_path") or "").strip()

    if latest_generated_report:
        report_path = Path(latest_generated_report).expanduser().resolve()

        if report_path.exists() and report_path.is_file():
            return report_path

    reports_dir = REPORTS_DIR

    search_dirs = [
        reports_dir,
        OUTPUT_VIDEOS_DIR,
    ]

    report_files: list[Path] = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        if search_dir == reports_dir:
            report_files.extend(search_dir.rglob("*.docx"))
            report_files.extend(search_dir.rglob("*.doc"))
        else:
            report_files.extend(search_dir.glob("*.docx"))
            report_files.extend(search_dir.glob("*.doc"))

    if not report_files:
        return None

    return max(report_files, key=lambda file_path: file_path.stat().st_mtime)


# Helper: safe report lookup name
def _safe_report_lookup_name(value: str, fallback: str = "未填写") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text or fallback


def find_task_report_file(company_name: str, station_name: str, roof_name: str, finished_at: str) -> Path | None:
    reports_dir = REPORTS_DIR

    finished_time = _parse_task_time(finished_at) or datetime.now()
    date_folder = finished_time.strftime("%Y-%m-%d")

    target_dir = (
        reports_dir
        / date_folder
        / _safe_report_lookup_name(company_name, "未知公司")
        / _safe_report_lookup_name(station_name, "未知电站")
    )
    roof_prefix = _safe_report_lookup_name(roof_name, "未知屋顶")

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"未找到当前任务报告目录: {target_dir}")
        return None

    matched_reports = [
        *target_dir.glob(f"{roof_prefix}_*.docx"),
        *target_dir.glob(f"{roof_prefix}_*.doc"),
    ]

    if not matched_reports:
        print(f"未找到当前任务报告文件: {target_dir}/{roof_prefix}_*.docx")
        return None

    return max(matched_reports, key=lambda file_path: file_path.stat().st_mtime)


# === Hotspot detection record helpers ===
def _parse_task_time(time_text: str) -> datetime | None:
    if not time_text:
        return None

    try:
        return datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _calculate_duration_minutes(started_at: str, finished_at: str) -> float:
    started_time = _parse_task_time(started_at)
    finished_time = _parse_task_time(finished_at)

    if not started_time or not finished_time:
        return 0

    duration_seconds = max(0, (finished_time - started_time).total_seconds())
    return round(duration_seconds / 60, 2)


def _build_hotspot_detect_code(company_id: int | None, roof_id: int | None, finished_at: str) -> str:
    finished_time = _parse_task_time(finished_at) or datetime.now()
    time_code = finished_time.strftime("%Y%m%d%H%M%S")
    company_part = company_id if company_id is not None else "NA"
    roof_part = roof_id if roof_id is not None else "NA"
    return f"HS-{company_part}-{roof_part}-{time_code}"


def _try_write_completed_hotspot_record(task_id: str) -> None:
    task = DETECTION_TASKS.get(task_id)

    if not task:
        return

    if task.get("status") != "completed":
        return

    company_name = str(task.get("company_name") or "").strip()
    station_name = str(task.get("station_name") or "").strip()
    roof_name = str(task.get("roof_name") or "").strip()

    if not company_name or not station_name or not roof_name:
        task["hotspot_record_message"] = "缺少公司/电站/屋顶信息，未写入热斑管理正式记录"
        print(task["hotspot_record_message"])
        return

    finished_at = str(task.get("finished_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    report_path = find_task_report_file(company_name, station_name, roof_name, finished_at)
    print(f"本次检测用于写入热斑管理的报告路径: {report_path}")

    if report_path is None or not report_path.exists() or not report_path.is_file():
        task["hotspot_record_message"] = "当前公司/电站/屋顶对应的报告未生成，未写入热斑管理正式记录"
        print(task["hotspot_record_message"])
        return

    company_id = get_id_by_company_name(company_name)

    if company_id is None:
        task["hotspot_record_message"] = "未找到公司ID，未写入热斑管理正式记录"
        print(task["hotspot_record_message"])
        return

    try:
        roof_info = _get_selected_roof_info(company_id, station_name, roof_name)
    except HTTPException as exc:
        task["hotspot_record_message"] = f"未找到屋顶信息，未写入热斑管理正式记录: {exc.detail}"
        print(task["hotspot_record_message"])
        return

    roof_id = roof_info.get("id") or roof_info.get("roof_id")
    detect_code = _build_hotspot_detect_code(company_id, roof_id, finished_at)
    detect_duration = _calculate_duration_minutes(str(task.get("started_at") or ""), finished_at)
    hotspot_count = int(task.get("hotspot_count") or 0)

    record_id = add_hotspot_detection_record(
        {
            "detect_code": detect_code,
            "company_id": company_id,
            "company_name": company_name,
            "station_name": station_name,
            "roof_id": roof_id,
            "roof_name": roof_name,
            "video_path": task.get("input_path") or "",
            "report_path": str(report_path),
            "detect_time": finished_at,
            "detect_duration": detect_duration,
            "hotspot_component_count": hotspot_count,
            "defect_summary": "热斑" if hotspot_count > 0 else "未发现热斑",
            "process_status": "未处理",
            "report_status": "已生成",
        }
    )

    task["hotspot_record_id"] = record_id
    task["hotspot_record_message"] = "已写入热斑管理正式记录"
    task["report_path"] = str(report_path)
    print(f"热斑管理正式记录写入成功 record_id={record_id}")


def _try_create_detection_task_record(task_id: str) -> None:
    task = DETECTION_TASKS.get(task_id)

    if not task:
        return

    company_name = str(task.get("company_name") or "").strip()
    station_name = str(task.get("station_name") or "").strip()
    roof_name = str(task.get("roof_name") or "").strip()

    if not company_name or not station_name or not roof_name:
        task["detection_task_record_message"] = "缺少公司/电站/屋顶信息，未写入检测任务记录"
        print(task["detection_task_record_message"])
        return

    company_id = get_id_by_company_name(company_name)

    if company_id is None:
        task["detection_task_record_message"] = "未找到公司ID，未写入检测任务记录"
        print(task["detection_task_record_message"])
        return

    try:
        roof_info = _get_selected_roof_info(company_id, station_name, roof_name)
    except HTTPException as exc:
        task["detection_task_record_message"] = f"未找到屋顶信息，未写入检测任务记录: {exc.detail}"
        print(task["detection_task_record_message"])
        return

    roof_id = roof_info.get("id") or roof_info.get("roof_id")
    # 新增: 保存电站地址到检测任务
    task["station_address"] = roof_info.get("station_address") or ""
    record_id = add_detection_task_record(
        {
            "company_id": company_id,
            "company_name": company_name,
            "station_name": station_name,
            "roof_id": roof_id,
            "roof_name": roof_name,
            "started_at": task.get("started_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "hotspot_component_count": 0,
            "is_saved_to_hotspot_management": 0,
            "hotspot_record_id": None,
            "task_status": "检测中",
        }
    )

    task["detection_task_record_id"] = record_id
    task["detection_task_record_message"] = "已写入检测任务记录"
    task["company_id"] = company_id
    task["roof_id"] = roof_id
    print(f"检测任务记录写入成功 record_id={record_id}")



def _map_detection_task_status(task_status: str) -> str:
    if task_status == "completed":
        return "检测完毕"

    if task_status in {"stopped", "stopping"}:
        return "检测中断"

    if task_status == "failed":
        return "检测失败"

    return "检测中"


def _try_update_detection_task_record(task_id: str) -> None:
    task = DETECTION_TASKS.get(task_id)

    if not task:
        return

    record_id = task.get("detection_task_record_id")

    if not record_id:
        return

    update_detection_task_record(
        record_id,
        {
            "finished_at": task.get("finished_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hotspot_component_count": int(task.get("hotspot_count") or 0),
            "is_saved_to_hotspot_management": 1 if task.get("hotspot_record_id") else 0,
            "hotspot_record_id": task.get("hotspot_record_id"),
            "task_status": _map_detection_task_status(str(task.get("status") or "")),
        },
    )



@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "Python后端已经启动成功",
        "port": ACTUAL_PORT,
        "api_base_url": f"http://127.0.0.1:{ACTUAL_PORT}",
    }


# ====== Station Selector Endpoints ======

def _first_value(row: Any, preferred_keys: tuple[str, ...] = ()):
    if isinstance(row, dict):
        for key in preferred_keys:
            if key in row:
                return row[key]
        return next(iter(row.values()), None)

    if isinstance(row, (list, tuple)):
        return row[0] if row else None

    return row


def _unique_text_options(rows, preferred_keys: tuple[str, ...] = ()) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in rows or []:
        value = _first_value(row, preferred_keys)
        if value is None:
            continue

        text = str(value).strip()
        if not text or text in seen:
            continue

        seen.add(text)
        options.append({"name": text})

    return options


# 新增: 视频与屋顶相关的辅助函数
def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row

    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}

    return {}





def collect_detection_asset_image_paths_by_asset_root(asset_root: Path) -> dict[str, list[str]]:
    report_pages_dir = asset_root / "report_pages"
    hotspot_frames_dir = asset_root / "hotspot_frames"

    def collect_images(folder: Path) -> list[str]:
        if not folder.exists() or not folder.is_dir():
            return []

        image_files: list[Path] = []
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            image_files.extend(folder.glob(pattern))

        return [str(file_path.resolve()) for file_path in sorted(image_files)]

    return {
        "report_image_paths": collect_images(report_pages_dir),
        "hotspot_image_paths": collect_images(hotspot_frames_dir),
    }


def find_detection_asset_image_paths_for_hotspot_record(row_dict: dict[str, Any]) -> dict[str, list[str]]:
    """根据热斑管理记录的检测时间，匹配 output_videos/detection_assets 下本次检测生成的图片。"""
    detection_assets_dir = DETECTION_ASSETS_DIR

    empty_result = {
        "report_image_paths": [],
        "hotspot_image_paths": [],
    }

    if not detection_assets_dir.exists() or not detection_assets_dir.is_dir():
        return empty_result

    asset_roots = [path for path in detection_assets_dir.iterdir() if path.is_dir()]

    if not asset_roots:
        return empty_result

    def latest_asset_mtime(asset_root: Path) -> datetime:
        image_files: list[Path] = []

        for child_dir_name in ("hotspot_frames", "report_pages"):
            child_dir = asset_root / child_dir_name

            if child_dir.exists() and child_dir.is_dir():
                for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    image_files.extend(child_dir.glob(pattern))

        if image_files:
            return datetime.fromtimestamp(max(file_path.stat().st_mtime for file_path in image_files))

        return datetime.fromtimestamp(asset_root.stat().st_mtime)

    detect_time = _parse_task_time(str(row_dict.get("detect_time") or ""))

    if detect_time is None:
        latest_asset_root = max(asset_roots, key=lambda path: latest_asset_mtime(path))
        return collect_detection_asset_image_paths_by_asset_root(latest_asset_root)

    candidate_asset_roots: list[tuple[float, Path]] = []

    for asset_root in asset_roots:
        asset_time = latest_asset_mtime(asset_root)
        delta_seconds = abs((asset_time - detect_time).total_seconds())

        # 一次检测通常几分钟内完成。给 15 分钟容差，避免 detect_time、报告生成时间、图片写入时间不完全一致导致匹配不到。
        if delta_seconds <= 15 * 60:
            candidate_asset_roots.append((delta_seconds, asset_root))

    if not candidate_asset_roots:
        return empty_result

    candidate_asset_roots.sort(key=lambda item: item[0])
    matched_asset_root = candidate_asset_roots[0][1]
    matched_paths = collect_detection_asset_image_paths_by_asset_root(matched_asset_root)

    print("【DEBUG-热斑管理图片】detect_code:", row_dict.get("detect_code"))
    print("【DEBUG-热斑管理图片】detect_time:", row_dict.get("detect_time"))
    print("【DEBUG-热斑管理图片】matched_asset_root:", matched_asset_root)
    print("【DEBUG-热斑管理图片】hotspot_image_paths:", matched_paths["hotspot_image_paths"])
    print("【DEBUG-热斑管理图片】report_image_paths:", matched_paths["report_image_paths"])

    return matched_paths


def _format_station_management_record(row: Any) -> dict[str, Any]:
    row_dict = _row_to_dict(row)

    record_id = row_dict.get("id") or row_dict.get("roof_id") or row_dict.get("roof_info_id")
    station_name = row_dict.get("station_name") or ""
    roof_name = row_dict.get("roof_name") or ""
    company_name = row_dict.get("name") or row_dict.get("company_name") or ""

    return {
        "id": record_id,
        "code": f"STATION-{record_id}" if record_id is not None else "STATION-UNKNOWN",
        "name": station_name,
        "stationName": station_name,
        "companyName": company_name,
        "roofName": roof_name,
        "region": row_dict.get("station_address") or "未填写",
        "capacity": row_dict.get("size") or "未填写",
        "status": row_dict.get("status") or "运行中",
        "owner": row_dict.get("person") or "未填写",
        "type": row_dict.get("type") or "未填写",
        "weather": row_dict.get("weather") or "未填写",
        "longitude": row_dict.get("longitude"),
        "latitude": row_dict.get("latitude"),
        "minLongitude": row_dict.get("min_longitude"),
        "maxLongitude": row_dict.get("max_longitude"),
        "minLatitude": row_dict.get("min_latitude"),
        "maxLatitude": row_dict.get("max_latitude"),
        "raw": row_dict,
    }


def _format_hotspot_detection_record(row: Any) -> dict[str, Any]:
    row_dict = _row_to_dict(row)
    asset_image_paths = find_detection_asset_image_paths_for_hotspot_record(row_dict)

    return {
        "id": row_dict.get("id"),
        "detectCode": row_dict.get("detect_code") or "",
        "companyId": row_dict.get("company_id"),
        "companyName": row_dict.get("company_name") or "未填写",
        "stationName": row_dict.get("station_name") or "未填写",
        "roofId": row_dict.get("roof_id"),
        "roofName": row_dict.get("roof_name") or "未填写",
        "videoPath": row_dict.get("video_path") or "",
        "reportPath": row_dict.get("report_path") or "",
        "detectTime": row_dict.get("detect_time") or "未填写",
        "detectDuration": row_dict.get("detect_duration") or 0,
        "hotspotComponentCount": row_dict.get("hotspot_component_count") or 0,
        "defectSummary": row_dict.get("defect_summary") or "热斑",
        "hotspot_image_paths": asset_image_paths["hotspot_image_paths"],
        "report_image_paths": asset_image_paths["report_image_paths"],
        "defectImagePaths": [
            *asset_image_paths["hotspot_image_paths"],
            *asset_image_paths["report_image_paths"],
        ],
        "processStatus": row_dict.get("process_status") or "未处理",
        "reportStatus": row_dict.get("report_status") or "未生成",
        "createdAt": row_dict.get("created_at") or "",
        "updatedAt": row_dict.get("updated_at") or "",
        "raw": row_dict,
    }


# 新增: 检测任务记录格式化
def _format_detection_task_record(row: Any) -> dict[str, Any]:
    row_dict = _row_to_dict(row)

    return {
        "id": row_dict.get("id"),
        "companyId": row_dict.get("company_id"),
        "companyName": row_dict.get("company_name") or "未填写",
        "stationName": row_dict.get("station_name") or "未填写",
        "roofId": row_dict.get("roof_id"),
        "roofName": row_dict.get("roof_name") or "未填写",
        "startedAt": row_dict.get("started_at") or "未记录",
        "finishedAt": row_dict.get("finished_at") or "未记录",
        "hotspotComponentCount": row_dict.get("hotspot_component_count") or 0,
        "isSavedToHotspotManagement": bool(row_dict.get("is_saved_to_hotspot_management")),
        "hotspotRecordId": row_dict.get("hotspot_record_id"),
        "taskStatus": row_dict.get("task_status") or "检测中",
        "createdAt": row_dict.get("created_at") or "",
        "updatedAt": row_dict.get("updated_at") or "",
        "raw": row_dict,
    }


# --- Station Management Backend Helpers ---
def _safe_number_or_text(value: Any):
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text or text == "未填写":
            return None
        try:
            return float(text)
        except ValueError:
            return text

    return value


def _build_roof_info_message(req: StationManagementSaveRequest) -> dict[str, Any]:
    return {
        "station_name": req.station_name,
        "station_address": req.station_address,
        "roof_number": req.roof_number,
        "roof_name": req.roof_name,
        "size": req.size,
        "type": req.type,
        "person": req.person,
        "weather": req.weather,
        "longitude": _safe_number_or_text(req.longitude),
        "latitude": _safe_number_or_text(req.latitude),
        "min_longitude": _safe_number_or_text(req.min_longitude),
        "max_longitude": _safe_number_or_text(req.max_longitude),
        "min_latitude": _safe_number_or_text(req.min_latitude),
        "max_latitude": _safe_number_or_text(req.max_latitude),
        "status": req.status or "运行中",
    }


def _find_same_name_srt(video_path: Path) -> Path | None:
    candidates = [
        video_path.with_suffix(".srt"),
        video_path.with_suffix(".SRT"),
    ]

    for srt_path in candidates:
        if srt_path.exists() and srt_path.is_file():
            return srt_path

    # 兜底：兼容大小写混合的后缀，例如 .Srt / .sRt
    video_stem = video_path.stem.lower()
    parent_dir = video_path.parent

    if parent_dir.exists() and parent_dir.is_dir():
        for file_path in parent_dir.iterdir():
            if file_path.is_file() and file_path.stem.lower() == video_stem and file_path.suffix.lower() == ".srt":
                return file_path

    return None


def _extract_average_lon_lat_from_srt(srt_path: Path) -> tuple[float, float]:
    text = srt_path.read_text(encoding="utf-8", errors="ignore")

    longitude_values: list[float] = []
    latitude_values: list[float] = []

    longitude_patterns = [
        r"longitude\s*[:：=]\s*(-?\d+(?:\.\d+)?)",
        r"lon\s*[:：=]\s*(-?\d+(?:\.\d+)?)",
        r"经度\s*[:：=]\s*(-?\d+(?:\.\d+)?)",
    ]
    latitude_patterns = [
        r"latitude\s*[:：=]\s*(-?\d+(?:\.\d+)?)",
        r"lat\s*[:：=]\s*(-?\d+(?:\.\d+)?)",
        r"纬度\s*[:：=]\s*(-?\d+(?:\.\d+)?)",
    ]

    for pattern in longitude_patterns:
        longitude_values.extend(float(value) for value in re.findall(pattern, text, flags=re.IGNORECASE))

    for pattern in latitude_patterns:
        latitude_values.extend(float(value) for value in re.findall(pattern, text, flags=re.IGNORECASE))

    if not longitude_values or not latitude_values:
        raise HTTPException(status_code=400, detail="SRT文件中没有解析到经纬度信息")

    average_longitude = sum(longitude_values) / len(longitude_values)
    average_latitude = sum(latitude_values) / len(latitude_values)

    return average_longitude, average_latitude


def _get_selected_roof_info(company_id: int, station_name: str, roof_name: str) -> dict[str, Any]:
    rows = get_roof_info_by_roof_name(roof_name)

    for row in rows or []:
        row_dict = _row_to_dict(row)

        if (
            int(row_dict.get("company_id", -1)) == int(company_id)
            and str(row_dict.get("station_name", "")) == station_name
            and str(row_dict.get("roof_name", "")) == roof_name
        ):
            return row_dict

    raise HTTPException(status_code=404, detail="未找到对应屋顶信息")


@app.get("/station/companies")
def station_companies():
    rows = get_all_company_names()
    return {
        "success": True,
        "data": _unique_text_options(rows, ("name", "company_name")),
    }


@app.get("/station/stations")
def station_names(company_name: str):
    company_id = get_id_by_company_name(company_name)

    if company_id is None:
        raise HTTPException(status_code=404, detail="未找到对应公司")

    rows = get_station_name_by_company_id(company_id)

    return {
        "success": True,
        "company_id": company_id,
        "data": _unique_text_options(rows, ("station_name",)),
    }


@app.get("/station/roofs")
def station_roofs(company_name: str, station_name: str):
    company_id = get_id_by_company_name(company_name)

    if company_id is None:
        raise HTTPException(status_code=404, detail="未找到对应公司")

    rows = get_roof_name_by_station_name(station_name)
    matched_rows = []

    for row in rows or []:
        row_dict = _row_to_dict(row)

        if (
            int(row_dict.get("company_id", -1)) == int(company_id)
            and str(row_dict.get("station_name", "")).strip() == station_name.strip()
        ):
            matched_rows.append(row_dict)

    return {
        "success": True,
        "company_id": company_id,
        "station_name": station_name,
        "data": _unique_text_options(matched_rows, ("roof_name",)),
    }


@app.get("/station/roof-info")
def station_roof_info(company_name: str, station_name: str, roof_name: str):
    company_id = get_id_by_company_name(company_name)

    if company_id is None:
        raise HTTPException(status_code=404, detail="未找到对应公司")

    roof_info = _get_selected_roof_info(company_id, station_name, roof_name)

    return {
        "success": True,
        "company_id": company_id,
        "station_name": station_name,
        "roof_name": roof_name,
        "data": [roof_info],
    }


# 新增: 站点管理-站点列表接口
@app.get("/station-management/stations")
def station_management_stations():
    rows = select_all_infos()
    records = [_format_station_management_record(row) for row in rows or []]

    return {
        "success": True,
        "total": len(records),
        "data": records,
    }


# 新增: 站点管理-创建站点
@app.post("/station-management/stations")
def station_management_create_station(req: StationManagementSaveRequest):
    message = _build_roof_info_message(req)
    add_station_management_info(req.company_name, message)

    rows = select_all_infos()
    records = [_format_station_management_record(row) for row in rows or []]

    return {
        "success": True,
        "message": "电站信息创建成功",
        "total": len(records),
        "data": records,
    }


# 新增: 站点管理-更新站点
@app.put("/station-management/stations/{station_id}")
def station_management_update_station(station_id: int, req: StationManagementSaveRequest):
    message = _build_roof_info_message(req)
    effect_rows = update_station_management_info_by_id(station_id, req.company_name, message)

    if effect_rows <= 0:
        raise HTTPException(status_code=404, detail="未找到要更新的电站记录")

    rows = select_all_infos()
    records = [_format_station_management_record(row) for row in rows or []]

    return {
        "success": True,
        "message": "电站信息更新成功",
        "station_id": station_id,
        "total": len(records),
        "data": records,
    }



# 新增: 站点管理-删除站点
@app.delete("/station-management/stations/{station_id}")
def station_management_delete_station(station_id: int):
    effect_rows = delete_station_management_info_by_id(station_id)

    if effect_rows <= 0:
        raise HTTPException(status_code=404, detail="未找到要删除的电站记录")

    rows = select_all_infos()
    records = [_format_station_management_record(row) for row in rows or []]

    return {
        "success": True,
        "message": "电站信息删除成功",
        "station_id": station_id,
        "total": len(records),
        "data": records,
    }


# 新增: 热斑管理-正式检测记录列表
@app.get("/hotspot-management/records")
def hotspot_management_records():
    rows = select_hotspot_detection_records()
    records = [_format_hotspot_detection_record(row) for row in rows or []]

    return {
        "success": True,
        "total": len(records),
        "data": records,
    }


# 新增: 热斑管理-更新正式检测记录
@app.put("/hotspot-management/records/{record_id}")
def hotspot_management_update_record(record_id: int, req: HotspotRecordUpdateRequest):
    update_message = req.model_dump(exclude_unset=True)
    effect_rows = update_hotspot_detection_record(record_id, update_message)

    if effect_rows <= 0:
        raise HTTPException(status_code=404, detail="未找到要更新的热斑检测记录")

    rows = select_hotspot_detection_records()
    records = [_format_hotspot_detection_record(row) for row in rows or []]

    return {
        "success": True,
        "message": "热斑检测记录更新成功",
        "record_id": record_id,
        "total": len(records),
        "data": records,
    }


# 新增: 热斑管理-软删除正式检测记录
@app.delete("/hotspot-management/records/{record_id}")
def hotspot_management_delete_record(record_id: int):
    effect_rows = delete_hotspot_detection_record_by_id(record_id)

    if effect_rows <= 0:
        raise HTTPException(status_code=404, detail="未找到要删除的热斑检测记录")

    rows = select_hotspot_detection_records()
    records = [_format_hotspot_detection_record(row) for row in rows or []]

    return {
        "success": True,
        "message": "热斑检测记录删除成功",
        "record_id": record_id,
        "total": len(records),
        "data": records,
    }


# 新增: 热斑检测页面右下角-检测任务记录列表
@app.get("/detection-task-records")
def detection_task_records(limit: int = 20):
    rows = select_detection_task_records(limit)
    records = [_format_detection_task_record(row) for row in rows or []]

    return {
        "success": True,
        "total": len(records),
        "data": records,
    }


# 新增: 热斑检测页面右下角-软删除检测任务记录
@app.delete("/detection-task-records/{record_id}")
def detection_task_delete_record(record_id: int):
    effect_rows = delete_detection_task_record_by_id(record_id)

    if effect_rows <= 0:
        raise HTTPException(status_code=404, detail="未找到要删除的检测任务记录")

    rows = select_detection_task_records(20)
    records = [_format_detection_task_record(row) for row in rows or []]

    return {
        "success": True,
        "message": "检测任务记录删除成功",
        "record_id": record_id,
        "total": len(records),
        "data": records,
    }


# 新增: 视频与屋顶信息验证接口
@app.post("/station/validate-video-roof")
def validate_video_roof(req: ValidateVideoRoofRequest):
    video_path = Path(req.input_path).expanduser().resolve()

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    company_id = get_id_by_company_name(req.company_name)

    if company_id is None:
        raise HTTPException(status_code=404, detail="未找到对应公司")

    srt_path = _find_same_name_srt(video_path)

    if srt_path is None:
        raise HTTPException(status_code=404, detail="未找到与视频同名的SRT文件")

    average_longitude, average_latitude = _extract_average_lon_lat_from_srt(srt_path)
    roof_info = _get_selected_roof_info(company_id, req.station_name, req.roof_name)

    min_longitude = float(roof_info["min_longitude"])
    max_longitude = float(roof_info["max_longitude"])
    min_latitude = float(roof_info["min_latitude"])
    max_latitude = float(roof_info["max_latitude"])

    longitude_matched = min_longitude <= average_longitude <= max_longitude
    latitude_matched = min_latitude <= average_latitude <= max_latitude
    matched = longitude_matched and latitude_matched

    return {
        "success": True,
        "matched": matched,
        "message": "视频位置与所选屋顶匹配" if matched else "视频位置不属于当前选择的屋顶",
        "input_path": str(video_path),
        "srt_path": str(srt_path),
        "company_id": company_id,
        "company_name": req.company_name,
        "station_name": req.station_name,
        "roof_name": req.roof_name,
        "average_longitude": average_longitude,
        "average_latitude": average_latitude,
        "roof_range": {
            "min_longitude": min_longitude,
            "max_longitude": max_longitude,
            "min_latitude": min_latitude,
            "max_latitude": max_latitude,
        },
    }


# 视频文件播放接口
@app.get("/media/video")
def media_video(path: str):
    video_path = Path(path).expanduser().resolve()

    print("前端请求播放视频 path：", path)
    print("解析后的视频路径：", video_path)
    print("视频是否存在：", video_path.exists())
    print("是否是文件：", video_path.is_file())

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail=f"视频文件不存在: {video_path}")

    suffix = video_path.suffix.lower()
    media_type = "video/mp4"

    if suffix == ".mov":
        media_type = "video/quicktime"
    elif suffix == ".avi":
        media_type = "video/x-msvideo"
    elif suffix == ".mkv":
        media_type = "video/x-matroska"

    return FileResponse(
        str(video_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{video_path.name}"',
            "Accept-Ranges": "bytes",
        },
    )


# 图片文件播放接口
@app.get("/media/image")
def media_image(path: str):
    image_path = Path(path).expanduser().resolve()

    print("前端请求播放图片 path：", path)
    print("解析后的图片路径：", image_path)
    print("图片是否存在：", image_path.exists())
    print("是否是文件：", image_path.is_file())

    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"图片文件不存在: {image_path}")

    suffix = image_path.suffix.lower()
    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(suffix)

    if media_type is None:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式: {suffix}")

    return FileResponse(
        str(image_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{image_path.name}"',
        },
    )


@app.post("/detect/start")
def detect_start(req: DetectStartRequest):
    print("前端传来的输入视频路径：", req.input_path)
    print("[后端入口] 公司名称:", req.company_name or "未传入")
    print("[后端入口] 电站名称:", req.station_name or "未传入")
    print("[后端入口] 屋顶名称:", req.roof_name or "未传入")

    if req.output_path:
        output_path = req.output_path
    else:
        ensure_runtime_dirs()
        output_filename = f"detect_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        output_path = str(OUTPUT_VIDEOS_DIR / output_filename)

    task_id = str(uuid4())
    DETECTION_TASKS[task_id] = {
        "task_id": task_id,
        "status": "running",
        "message": "检测任务已启动",
        "input_path": req.input_path,
        "output_path": output_path,
        "company_name": req.company_name,
        "station_name": req.station_name,
        "roof_name": req.roof_name,
        "station_address": "",
        "progress": 0,
        "current_frame": 0,
        "total_frames": 0,
        "hotspot_count": 0,
        "result_video_path": "",
        "report_path": "",
        "hotspot_image_paths": [],
        "report_image_paths": [],
        "defectImagePaths": [],
        "hotspot_record_id": None,
        "hotspot_record_message": "",
        "detection_task_record_id": None,
        "detection_task_record_message": "",
        "error": "",
        "stop_requested": False,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": "",
    }

    _try_create_detection_task_record(task_id)

    def run_task():
        def update_progress(*args):
            current_frame = 0
            total_frames = 0

            # 推荐传法：update_progress(当前检测帧数, 总帧数)
            if len(args) >= 2:
                current_frame, total_frames = args[0], args[1]
                progress = int(current_frame / total_frames * 100) if total_frames else 0
            # 兼容旧传法：update_progress(百分比)
            elif len(args) == 1:
                progress = int(args[0])
            else:
                progress = 0

            progress = max(0, min(100, progress))

            DETECTION_TASKS[task_id]["progress"] = progress
            DETECTION_TASKS[task_id]["current_frame"] = current_frame
            DETECTION_TASKS[task_id]["total_frames"] = total_frames

            if total_frames:
                print(f"检测进度：{current_frame}/{total_frames} = {progress}%")
            else:
                print("检测进度：", progress)

        def update_hotspot_count(count=0, *args):
            DETECTION_TASKS[task_id]["hotspot_count"] = count
            print("热斑数量：", count)

        def should_stop():
            return DETECTION_TASKS.get(task_id, {}).get("stop_requested", False)

        try:
            print("[后端线程] 即将调用 run_detection，公司名称:", req.company_name or "未传入")
            print("[后端线程] 即将调用 run_detection，电站名称:", req.station_name or "未传入")
            print("[后端线程] 即将调用 run_detection，屋顶名称:", req.roof_name or "未传入")
            print("[后端线程] 即将调用 run_detection，电站地址:", DETECTION_TASKS[task_id].get("station_address") or "未传入")
            success, result = run_detection(
                input_path=req.input_path,
                output_path=output_path,
                update_progress=update_progress,
                srt_file_path=req.srt_file_path,
                update_hotspot_count=update_hotspot_count,
                should_stop=should_stop,
                company_name=req.company_name,
                station_name=req.station_name,
                roof_name=req.roof_name,
                station_address=DETECTION_TASKS[task_id].get("station_address") or "",
            )

            # --- Begin Patch: Result video path and image paths handling ---
            if isinstance(result, dict):
                result_video_path = str(
                    result.get("video_path")
                    or result.get("result_video_path")
                    or result.get("annotated_output_path")
                    or output_path
                )
                hotspot_image_paths = result.get("hotspot_image_paths") or result.get("hotspotImagePaths") or []
                report_image_paths = result.get("report_image_paths") or result.get("reportImagePaths") or []
            else:
                result_video_path = str(result)
                asset_root = Path(output_path).resolve().parent / "detection_assets" / Path(output_path).resolve().stem
                asset_image_paths = collect_detection_asset_image_paths_by_asset_root(asset_root)
                hotspot_image_paths = asset_image_paths["hotspot_image_paths"]
                report_image_paths = asset_image_paths["report_image_paths"]

            DETECTION_TASKS[task_id]["result_video_path"] = result_video_path
            DETECTION_TASKS[task_id]["hotspot_image_paths"] = hotspot_image_paths
            DETECTION_TASKS[task_id]["report_image_paths"] = report_image_paths
            DETECTION_TASKS[task_id]["defectImagePaths"] = [
                *hotspot_image_paths,
                *report_image_paths,
            ]
            print("【DEBUG-检测任务图片】hotspot_image_paths:", hotspot_image_paths)
            print("【DEBUG-检测任务图片】report_image_paths:", report_image_paths)
            DETECTION_TASKS[task_id]["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # --- End Patch: Result video path and image paths handling ---

            if DETECTION_TASKS[task_id].get("stop_requested"):
                DETECTION_TASKS[task_id]["status"] = "stopped"
                DETECTION_TASKS[task_id]["message"] = "检测已停止"
                _try_update_detection_task_record(task_id)
            elif success:
                DETECTION_TASKS[task_id]["status"] = "completed"
                DETECTION_TASKS[task_id]["message"] = "检测完成"
                DETECTION_TASKS[task_id]["progress"] = 100
                _try_write_completed_hotspot_record(task_id)
                _try_update_detection_task_record(task_id)
            else:
                DETECTION_TASKS[task_id]["status"] = "failed"
                DETECTION_TASKS[task_id]["message"] = "检测失败"
                DETECTION_TASKS[task_id]["error"] = str(result)
                _try_update_detection_task_record(task_id)
        except Exception as exc:
            DETECTION_TASKS[task_id]["status"] = "failed"
            DETECTION_TASKS[task_id]["message"] = "检测失败"
            DETECTION_TASKS[task_id]["error"] = str(exc)
            DETECTION_TASKS[task_id]["result_video_path"] = f"视频检测失败,{exc}"
            DETECTION_TASKS[task_id]["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _try_update_detection_task_record(task_id)

    Thread(target=run_task, daemon=True).start()

    return DETECTION_TASKS[task_id]


@app.post("/detect/stop/{task_id}")
def detect_stop(task_id: str):
    task = DETECTION_TASKS.get(task_id)

    if not task:
        return {
            "success": False,
            "status": "not_found",
            "message": "未找到检测任务",
            "task_id": task_id,
        }

    if task.get("status") in {"completed", "failed", "stopped"}:
        return {
            "success": True,
            "status": task.get("status"),
            "message": "检测任务已经结束，无需停止",
            "task_id": task_id,
        }

    task["stop_requested"] = True
    task["status"] = "stopping"
    task["message"] = "正在停止检测任务"
    task["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _try_update_detection_task_record(task_id)

    return {
        "success": True,
        "status": "stopping",
        "message": "已发送停止检测请求",
        "task_id": task_id,
    }


# 检测任务状态查询接口
@app.get("/detect/status/{task_id}")
def detect_status(task_id: str):
    task = DETECTION_TASKS.get(task_id)

    if not task:
        return {
            "success": False,
            "status": "not_found",
            "message": "未找到检测任务",
            "task_id": task_id,
        }

    return {
        "success": task["status"] == "completed",
        **task,
    }


# 最新报告下载接口
@app.get("/report/latest")
def download_latest_report():
    report_path = find_latest_report_file()
    print(f"下载最新报告路径: {report_path}")

    if report_path is None or not report_path.exists() or not report_path.is_file():
        raise HTTPException(status_code=404, detail="未找到可导出的报告文件")

    suffix = report_path.suffix.lower()
    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    if suffix == ".doc":
        media_type = "application/msword"

    return FileResponse(
        path=str(report_path),
        filename=report_path.name,
        media_type=media_type,
    )


# 报告导出接口
@app.post("/report/export")
def export_report(req: ReportExportRequest):
    report_path = find_latest_report_file()
    print(f"导出报告源路径: {report_path}")

    if report_path is None or not report_path.exists() or not report_path.is_file():
        raise HTTPException(status_code=404, detail="未找到可导出的报告文件")

    save_path = Path(req.save_path).expanduser().resolve()
    save_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(report_path, save_path)

    return {
        "success": True,
        "message": "报告导出成功",
        "source_path": str(report_path),
        "save_path": str(save_path),
    }

# ====== 启动入口：自动扫描可用端口并启动 uvicorn ======
if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="热斑检测 Python 后端服务")
    parser.add_argument("--port", type=int, default=0, help="指定启动端口，0 表示自动扫描可用端口（默认）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    args = parser.parse_args()

    if args.port > 0:
        # 命令行显式指定了端口，直接使用
        ACTUAL_PORT = args.port
    else:
        # 自动从 8000 开始扫描可用端口
        ACTUAL_PORT = find_available_port(8000, 9000, args.host)

    # 将实际端口写入文件，供 Tauri/Rust 层读取
    write_port_file(ACTUAL_PORT)

    # 注册退出时清理端口文件
    atexit.register(remove_port_file)

    print(f"[动态端口] Python 后端即将启动在 http://{args.host}:{ACTUAL_PORT}")
    uvicorn.run(app, host=args.host, port=ACTUAL_PORT)
