# 这是代码执行入口
from pathlib import Path

from app.common.get_config import get_config
from app.common.process_video import get_video_metadata, create_video_writer
from app.core.paths import CONFIG_PATH
from app.videoA.process_videoA import videoA_dump
from app.videoB.process_videoB import operate_videoB


def run_detection(
    input_path,
    output_path,
    update_progress,
    srt_file_path="",
    update_hotspot_count=None,
    should_stop=None,
    company_name="",
    station_name="",
    roof_name="",
    station_address="",
    selected_roof_info=None,
):
    try:
        print("[检测入口] 输入视频:", input_path)
        print("[检测入口] 输出视频:", output_path)
        print("[检测入口] 公司名称:", company_name or "未传入")
        print("[检测入口] 电站名称:", station_name or "未传入")
        print("[检测入口] 屋顶名称:", roof_name or "未传入")
        print("[检测入口] 电站地址:", station_address or "未传入")
        print("[检测入口] 屋顶数据库整行信息:", selected_roof_info or {})
        if should_stop is not None and should_stop():
            print("[检测入口] 检测任务已在启动前收到停止信号")
            return False, "检测已停止"

        config = get_config(str(CONFIG_PATH))

        videoA_path = Path(config["input_path"]["videoA_path"])

        if not videoA_path.is_absolute():
            videoA_path = CONFIG_PATH.parent.parent / videoA_path

        videoA_path = videoA_path.resolve()

        # 根据视频A的元数据 生成两个视频共同输出的地方
        metadata = get_video_metadata(videoA_path)
        out = create_video_writer(Path(output_path), metadata["width"], metadata["height"], metadata["fps"])

        if should_stop is not None and should_stop():
            print("[检测入口] 检测任务已在处理视频A前停止")
            release_message = "检测已停止"
            try:
                out.release()
            except Exception:
                pass
            return False, release_message

        # 对视频A的操作
        videoA_dump(videoA_path,out)

        if should_stop is not None and should_stop():
            print("[检测入口] 检测任务已在处理视频A后停止")
            try:
                out.release()
            except Exception:
                pass
            return False, "检测已停止"

        # 如果前端没有传 srt_file_path，就自动查找输入视频同目录下的同名 SRT 文件
        if not srt_file_path:
            input_video_path = Path(input_path)
            srt_lower = input_video_path.with_suffix(".srt")
            srt_upper = input_video_path.with_suffix(".SRT")

            if srt_lower.exists():
                srt_file_path = str(srt_lower)
            elif srt_upper.exists():
                srt_file_path = str(srt_upper)

        print("[检测入口] SRT路径:", srt_file_path if srt_file_path else "未找到同名SRT")

        # 核心业务 对视频B的操作
        final_video_path = operate_videoB(
            output_path,
            Path(input_path),
            out,
            update_progress,
            srt_file_path,
            update_hotspot_count,
            should_stop,
            company_name=company_name,
            station_name=station_name,
            roof_name=roof_name,
            station_address=station_address,
            selected_roof_info=selected_roof_info or {},
        )
        return True, final_video_path
    except Exception as e:
        import traceback
        print("run_detection发生异常，完整错误如下:")
        traceback.print_exc()
        return False, f"视频检测失败,{str(e)}"
