# 核心业务 对视频B的每一帧进行一系列的处理

import time
from collections import deque
from pathlib import Path

from app.common.frame_processor import FrameProcessor
from app.common.read_srt import parse_srt_file
from app.common.process_video import get_video_metadata
from app.common.normal import *
from app.common.db_utils import *
from app.core.paths import BACKEND_DIR, CONFIG_PATH, DETECTION_ASSETS_DIR
from app.UI.sqlite_utils import *

# ==== 路径工具函数 ====
def get_project_root() -> Path:
    """返回 backend 目录，避免依赖当前终端所在目录。"""
    return BACKEND_DIR


def resolve_project_path(path_value) -> Path:
    """把 config.yaml 里的相对路径转换成 backend 绝对路径；如果本身是绝对路径则原样返回。"""
    path = Path(path_value)

    if path.is_absolute():
        return path

    return BACKEND_DIR / path

shared_process_videoB_srt_path = {
    "srt_path": ""
}

# 初始化共享数据
shared_data = {
    'column_data': None,
    'prev_max_col': 0,
    'row_data': None,
    'prev_max_row': 0,
    'number_frame_history': {},
    'screenshot_cache': {},
    'delay_counters': {},
    'label_history': {},
    'roof_name': "未知屋顶",
    'roof_id': "未知编号",
    'roof_info': {},
    'gap_types': None,
    'contact_avg': None,
    'aisle_avg': None,
    'large_avg': None,
    'gap_types_v': None,
    'contact_avg_v': None,
    'aisle_avg_v': None,
    'large_avg_v': None,
    # 确保缓冲区已初始化
    'coordinate_buffer': deque(maxlen=6),
    # 用于保存热斑缺陷的前面的坐标位置信息
    'suspected_hotspot_components': []
}
shared_data['roof_info'] = {"roof_name": shared_data['roof_name'], "roof_id": shared_data['roof_id']}

# 本次检测产生的图片资产统一保存到 output_videos/detection_assets/{本次检测输出视频名}/ 下
# report_pages：报告首页 / 缺陷详情页图片
# hotspot_frames：热斑现场截图 / 标注截图图片
def build_detection_asset_dirs(output_path):
    output_file = Path(output_path).resolve()
    asset_root = DETECTION_ASSETS_DIR / output_file.stem
    report_pages_dir = asset_root / "report_pages"
    hotspot_frames_dir = asset_root / "hotspot_frames"

    report_pages_dir.mkdir(parents=True, exist_ok=True)
    hotspot_frames_dir.mkdir(parents=True, exist_ok=True)

    return {
        "asset_root": asset_root,
        "report_pages_dir": report_pages_dir,
        "hotspot_frames_dir": hotspot_frames_dir,
    }


def save_image_sequence(images, target_dir, filename_prefix, extension="png", max_images=None):
    """把 PIL / OpenCV-Numpy / 已有图片路径列表保存到指定目录，并返回保存成功的绝对路径列表。"""
    saved_paths = []

    if not images:
        print(f"【DEBUG-图片资产】{filename_prefix} 图片列表为空，没有可保存的图片")
        return saved_paths

    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    image_list = images if max_images is None else images[:max_images]
    print(f"【DEBUG-图片资产】准备保存 {filename_prefix} 图片，目录:", target_dir)
    print(f"【DEBUG-图片资产】{filename_prefix} 图片总数:", len(images))

    for index, image in enumerate(image_list, start=1):
        debug_path = target_dir / f"{filename_prefix}_{index:03d}.{extension}"
        print(f"【DEBUG-图片资产】{filename_prefix} 第 {index} 张图片类型:", type(image))

        try:
            if hasattr(image, "save"):
                image.save(str(debug_path))
                saved_paths.append(str(debug_path))
                print(f"【DEBUG-图片资产】已保存 PIL 图片: {debug_path}")
            elif hasattr(image, "shape"):
                cv2.imwrite(str(debug_path), image)
                saved_paths.append(str(debug_path))
                print(f"【DEBUG-图片资产】已保存 OpenCV/Numpy 图片: {debug_path}")
            elif isinstance(image, (str, Path)) and Path(image).exists():
                source_path = Path(image).resolve()
                if source_path != debug_path:
                    debug_path.write_bytes(source_path.read_bytes())
                saved_paths.append(str(debug_path))
                print(f"【DEBUG-图片资产】已复制图片文件: {debug_path}")
            else:
                print(f"【DEBUG-图片资产】无法保存：未知图片对象类型 {type(image)}")
        except Exception as error:
            print(f"【DEBUG-图片资产】保存失败: {debug_path}", error)

    print(f"【DEBUG-图片资产】{filename_prefix} 保存路径列表:", saved_paths)
    return saved_paths


def save_report_page_images(image_cache, output_path):
    asset_dirs = build_detection_asset_dirs(output_path)
    return save_image_sequence(
        image_cache,
        asset_dirs["report_pages_dir"],
        "report_page",
        extension="png",
        max_images=None,
    )


def save_hotspot_frame_images(hotspot_images, output_path):
    asset_dirs = build_detection_asset_dirs(output_path)
    return save_image_sequence(
        hotspot_images,
        asset_dirs["hotspot_frames_dir"],
        "hotspot_frame",
        extension="jpg",
        max_images=None,
    )

def operate_videoB(
    output_path,
    videoB_path: Path,
    out: cv2.VideoWriter,
    update_progress,
    srt_file_path,
    update_hotspot_count=None,
    should_stop=None,
    company_name="",
    station_name="",
    roof_name="",
    station_address="",
    selected_roof_info=None,
):

    global shared_process_videoB_srt_path

    metadata = get_video_metadata(videoB_path)
    totalB_frames = metadata['total_frames']

    config = get_config(str(CONFIG_PATH))

    videoA_path = resolve_project_path(config["input_path"]["videoA_path"])
    detection_input_path = resolve_project_path(config["detection_path"]["input_path"])
    detection_output_path = resolve_project_path(config["detection_path"]["output_path"])

    print("选择输入视频srt文件获取到的srt路径", srt_file_path)
    result = parse_srt_file(srt_file_path)
    print(f"根据srt读取到屋顶信息:{result}")
    # 读取srt文件
    time_str = result["date"]
    # 这一步读取的时候少了读取id的情况
    shared_data['roof_info'] = result
    selected_roof_info = dict(selected_roof_info or {})
    if selected_roof_info:
        shared_data['roof_info'].update(selected_roof_info)

    if company_name:
        shared_data['roof_info']['company_name'] = company_name
    if station_name:
        shared_data['roof_info']['station_name'] = station_name
    if roof_name:
        shared_data['roof_info']['roof_name'] = roof_name
    if station_address:
        shared_data['roof_info']['selected_station_address'] = station_address

    print("[视频B处理] 公司名称:", shared_data['roof_info'].get('company_name', '未传入'))
    print("[视频B处理] 电站名称:", shared_data['roof_info'].get('station_name', '未传入'))
    print("[视频B处理] 屋顶名称:", shared_data['roof_info'].get('roof_name', '未传入'))
    print("[视频B处理] 电站地址:", shared_data['roof_info'].get('selected_station_address', '未传入'))
    print("[视频B处理] 屋顶数据库整行信息:", selected_roof_info or {})

    # 每次新检测前重置热斑组件计数
    shared_data['zoom_stage_counter'] = 0
    shared_data['_last_reported_zoom_stage_counter'] = -1
    shared_data['counted_zoom_stage_keys'] = set()

    frameB_count = 0
    report_image_paths = []
    hotspot_image_paths = []
    shared_data["report_image_paths"] = report_image_paths
    shared_data["hotspot_image_paths"] = hotspot_image_paths
    cleanup_threshold = 600  # 原有数据清理阈值
    cleanup_interval = 500  # 原有清理间隔
    start_time = time.time()

    processor = FrameProcessor(shared_data=shared_data, update_hotspot_count=update_hotspot_count)  # 初始化一个帧类对象

    if should_stop is not None and should_stop():
        print("检测任务收到停止信号，视频B处理前提前结束")
        release_video_writer(out)
        return output_path

    capB = cv2.VideoCapture(str(videoB_path))
    if not capB.isOpened():
        raise FileNotFoundError(f"视频文件已损坏或文件路径错误{str(videoB_path)}")

    stop_requested = False

    while True:
        if should_stop is not None and should_stop():
            print("检测任务收到停止信号，视频B逐帧处理提前结束")
            stop_requested = True
            break

        retB, frameB = capB.read()
        if not retB:
            break

        frame_key = frameB_count % 5
        # 这里是对画面帧处理的关键方法process_frame
        processed_frame = processor.process_frame(frameB, frameB_count + 1, frame_key)

        out.write(processed_frame)
        frameB_count += 1

        update_progress(frameB_count, totalB_frames)

        # 只在热斑组件数量发生变化时才回传，避免频繁刷新UI
        if update_hotspot_count is not None:
            current_hotspot_count = int(shared_data.get('zoom_stage_counter', 0))
            last_hotspot_count = int(shared_data.get('_last_reported_zoom_stage_counter', -1))

            if current_hotspot_count != last_hotspot_count:
                shared_data['_last_reported_zoom_stage_counter'] = current_hotspot_count
                update_hotspot_count(current_hotspot_count)

        if frameB_count >= cleanup_threshold:
            cleanup_number_history(shared_data, cleanup_threshold, cleanup_interval)

        # 原有进度打印逻辑（保留）
        if frameB_count % 100 == 0:
            print(f"已处理 {frameB_count} 帧")
            print(f"当前处理时间：{time.time() - start_time:.2f} 秒")

    # 检测结束后补发一次最终热斑组件数
    if update_hotspot_count is not None:
        final_hotspot_count = int(shared_data.get('zoom_stage_counter', 0))
        update_hotspot_count(final_hotspot_count)

    capB.release()

    if stop_requested:
        print("检测任务已停止，跳过缺陷汇总、报告生成和后处理")
        release_video_writer(out)
        processor.release_resources()
        return output_path


    defect_labels = collect_detect_labels(processor)
    matched_defects = match_defect_with_position(processor, defect_labels)
    unique_defects_set = deduplicate_defect_labels(matched_defects)
    # 去重 只获取前面的坐标，而不需要后面的类型
    prefix_set = {item.split("-", 1)[0] for item in unique_defects_set}
    shared_data['suspected_hotspot_components'] = sorted(prefix_set)
    sorted_valid_nums = filter_and_sort_valid_numbers(shared_data)

    if not sorted_valid_nums:
        print("无符合条件的热斑编号")
        image_cache = []
    else:
        # 调用原有模块查询数据库（使用屋顶名 + roof_id 拼接动态组件表名）
        roof_info = shared_data.get("roof_info") or {}
        selected_roof_info = dict(selected_roof_info or {})

        roof_name = (
            roof_info.get("roof_name")
            or roof_info.get("roofName")
            or selected_roof_info.get("roof_name")
            or selected_roof_info.get("roofName")
            or roof_name
            or "未知屋顶"
        )
        roof_id = (
            roof_info.get("roof_id")
            or roof_info.get("roofId")
            or roof_info.get("id")
            or selected_roof_info.get("roof_id")
            or selected_roof_info.get("roofId")
            or selected_roof_info.get("id")
        )

        print("【DEBUG-屋顶组件表】roof_info:", roof_info)
        print("【DEBUG-屋顶组件表】selected_roof_info:", selected_roof_info)
        print("【DEBUG-屋顶组件表】roof_name:", roof_name)
        print("【DEBUG-屋顶组件表】roof_id:", roof_id)

        if not roof_id:
            expected_table_name_without_id = f"{roof_name}_<roof_id>"
            raise ValueError(
                "未获取到 roof_id，无法拼接屋顶组件动态表名。"
                f"当前 roof_name={roof_name!r}，"
                f"预期表名格式={expected_table_name_without_id!r}，"
                f"roof_info={roof_info!r}，"
                f"selected_roof_info={selected_roof_info!r}。"
                "请检查 SRT 经纬度匹配结果、前端传入的 selected_roof_info，"
                "或数据库 roof_info / station_management 表中是否存在该屋顶的 id。"
            )

        new_table_name = f"{roof_name}_{roof_id}"
        print("【DEBUG-屋顶组件表】准备查询动态表:", new_table_name)
        print("【DEBUG-屋顶组件表】热斑编号列表:", sorted_valid_nums)

        database_results = match_hot_spot_with_panel_position(new_table_name, sorted_valid_nums)

        if not database_results:
            print("数据库中未找到匹配的热斑记录")
            image_cache = []
        else:
            roof_info = shared_data["roof_info"]
            if selected_roof_info:
                roof_info.update(selected_roof_info)
            if company_name:
                roof_info["company_name"] = company_name
            if station_name:
                roof_info["station_name"] = station_name
            if roof_name:
                roof_info["roof_name"] = roof_name
            if station_address:
                roof_info["selected_station_address"] = station_address
            image_cache = generate_report_and_images(database_results, roof_info, time_str, unique_defects_set)
            report_image_paths = save_report_page_images(image_cache, output_path)
            shared_data["report_image_paths"] = report_image_paths
            print("【DEBUG-报告图片】report_image_paths:", report_image_paths)


    insert_images_to_video(out, image_cache)  # 检查是否有图片生成以及是否插入
    release_video_writer(out)  # 关闭视频播放器
    check_video_integrity(output_path)

    # 拼接后的最终视频路径（原output_video_path）
    input_final_video = output_path
    # 带标注的最终视频输出路径（新增前缀区分）
    pure_filename = os.path.basename(output_path)  # 提取纯文件名（去掉 ./ 等路径前缀）
    output_annotated_final = f"annotated_{pure_filename}"

    # 标注后视频完整路径
    annotated_output_path = os.path.join(
        os.path.abspath(os.path.dirname(output_path)),
        output_annotated_final
    )

    # 调用绘制函数，基于缓存的检测信息生成热斑标注图片
    # 不再使用 config['detection_path']['photo_save_path']，避免继续向 input_videos 目录生成 D.jpg 等旧图片。
    # 本次检测的热斑图片统一进入 output_videos/detection_assets/{本次检测输出视频名}/hotspot_frames/。
    asset_dirs = build_detection_asset_dirs(output_path)
    hotspot_annotation_save_path = asset_dirs["hotspot_frames_dir"] / "hotspot_annotation.jpg"
    print("【DEBUG-热斑图片】draw_one_annotation_image save_path:", hotspot_annotation_save_path)

    processor.draw_one_annotation_image(
        video_path=input_final_video,
        save_path=str(hotspot_annotation_save_path),
        total_frames_A=get_video_metadata(videoA_path)["total_frames"],
    )
    hotspot_image_paths = save_hotspot_frame_images(processor.draw_photo_cache, output_path)
    shared_data["hotspot_image_paths"] = hotspot_image_paths
    print("【DEBUG-热斑图片】hotspot_image_paths:", hotspot_image_paths)

    if hotspot_annotation_save_path.exists():
        try:
            hotspot_annotation_save_path.unlink()
            print("【DEBUG-热斑图片】已删除重复临时图片:", hotspot_annotation_save_path)
        except Exception as error:
            print("【DEBUG-热斑图片】删除重复临时图片失败:", hotspot_annotation_save_path, error)

    append_images_to_video(str(detection_input_path), str(detection_output_path), processor.draw_photo_cache)

    cv2.destroyAllWindows()

    print(f"原始结果视频: {output_path}")
    print(f"标注结果视频: {annotated_output_path}")
    print(f"总处理时间：{time.time() - start_time:.2f} 秒")

    # 程序结束时释放资源
    processor.release_resources()

    return annotated_output_path
