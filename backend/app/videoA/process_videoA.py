from pathlib import Path

import cv2


def videoA_dump(videoA_path: Path, writer: cv2.VideoWriter):
    """将视频A写入到新的文件中。"""
    capA = cv2.VideoCapture(str(videoA_path))

    if not capA.isOpened():
        raise ValueError(f"视频A无法正常打开，A地址: {videoA_path}")

    try:
        while True:
            ret, frame = capA.read()

            if not ret:
                break

            writer.write(frame)
    finally:
        capA.release()
