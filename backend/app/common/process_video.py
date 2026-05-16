# 对与视频相关操作的公用方法
from pathlib import Path

import cv2

def get_video_metadata(video_path: Path, key: str | None = None):
    """返回视频的元数据(宽,高,帧率,编码),可以输出其中一个属性也可以输出整个元数据"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频{video_path}")

    fourcc_code = int(cap.get(cv2.CAP_PROP_FOURCC))  # 获取四字符编码的数值(整数形式)
    codec = (  # 将数值转换成可读的四字符编码形式(如avc1,mp4v)
        chr(fourcc_code & 0xFF)
        + chr((fourcc_code >> 8) & 0xFF)
        + chr((fourcc_code >> 16) & 0xFF)
        + chr((fourcc_code >> 24) & 0xFF)
    )

    metadata = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": int(cap.get(cv2.CAP_PROP_FPS)),
        "total_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "codec": codec,
    }
    cap.release()

    if key:
        if key not in metadata:
            raise KeyError(f"无效key! 可选:{list(metadata.keys())}")
        return metadata[key]
    return metadata


def create_video_writer(
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    codec: str = "mp4v",
) -> cv2.VideoWriter:
    """创建一个视频输出器"""
    output_path.parent.mkdir(parents=True, exist_ok=True)  # 确保输出路径的父目录一定存在,没有则直接创建

    fourcc = cv2.VideoWriter_fourcc(*codec)

    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    if not writer.isOpened():
        raise ValueError(
            f"无法创建输出对象!请检查\n"
            f"1.编码格式{codec}是否合法\n"
            f"2.输出路径{output_path}是否可写\n"
            f"3.宽高{width}x{height}是否合法"
        )
    return writer