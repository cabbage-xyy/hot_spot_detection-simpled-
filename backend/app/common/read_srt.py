# 读取srt文件信息
import re
from pathlib import Path
from typing import Any

from app.UI.sqlite_utils import *

def parse_srt_file(srt_file_path: Path) -> dict[str, Any]:
    """
    解析SRT文件，提取日期、经纬度，并调用get_roof_info获取屋顶信息
    """
    # 初始化返回结果
    result = {
        "date": None,
        "latitude": None,
        "longitude": None,
    }
    srt_file_path = str(srt_file_path)

    try:
        # 读取SRT文件内容
        with open(srt_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # 1. 提取第4行的日期信息（索引3）
        if len(lines) >= 4:
            time_line = lines[3].strip()
            time_match = re.search(r'(\d{4}-\d{2}-\d{2})', time_line)
            if time_match:
                result["date"] = time_match.group(1)
            else:
                print(f"警告：文件 {srt_file_path} 未找到有效的时间信息")
                return {'result': 'false', 'error': '未找到有效的时间信息'}
        else:
            print(f"警告：文件 {srt_file_path} 行数不足4行，无法提取时间")
            return {'result': 'false', 'error': '行数不足4行，无法提取时间'}
        # 2. 提取第5行的经纬度信息（索引4）
        if len(lines) >= 5:
            target_line = lines[4].strip()
            lat_lng_match = re.search(
                r'\[latitude:\s*([+-]?\d+\.\d+)].*?\[longitude:\s*([+-]?\d+\.\d+)]',
                target_line
            )
            if lat_lng_match:
                # 解析经纬度并赋值
                result["latitude"] = float(lat_lng_match.group(1))
                result["longitude"] = float(lat_lng_match.group(2))
                # 调用get_roof_info获取屋顶信息（需确保该函数已定义）
                # TODO 这里的srt文件应该是外界按钮导入的
                file_path = srt_file_path
                roof_info = get_roof_info_by_lon_lat(file_path)
                print(f"srt中获取到的经纬度,{result['latitude']},{result['longitude']}")
                result.update(roof_info)
            else:
                print(f"警告：文件 {srt_file_path} 未找到有效的经纬度信息")
                return {'result': 'false', 'error': '未找到有效的经纬度信息'}
        else:
            print(f"警告：文件 {srt_file_path} 行数不足5行，无法提取经纬度")
            return {'result': 'false', 'error': '行数不足5行，无法提取经纬度'}

    except Exception as e:
        # 捕获所有异常并记录到返回结果
        error_msg = f"解析SRT文件失败 - {str(e)}"
        print(f"错误：{error_msg}")
        result["error"] = error_msg

    print("读取后返回的结果有哪些", result)
    return result

