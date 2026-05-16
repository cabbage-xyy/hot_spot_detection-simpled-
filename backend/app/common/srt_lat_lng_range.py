# 从srt文件中获取最小和最大的纬度和经度 确认屋顶的经纬度范围
import re


# 从指定路径的 SRT 文件中，批量提取所有符合特定格式的经纬度坐标，并转换为浮点数后返回（按 “经度、纬度” 的顺序存储）
def extract_coordinates_from_srt(file_path):
    """从SRT文件中提取经纬度坐标"""
    # 定义匹配经纬度的正则表达式模式
    # 匹配 [latitude: 30.483284] [longitude: 120.671616] 格式
    pattern = r"\[latitude:\s*([-+]?\d+\.\d+)\]\s*\[longitude:\s*([-+]?\d+\.\d+)\]"

    coordinates = []

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            # 查找所有匹配的经纬度对
            matches = re.findall(pattern, content)

            for match in matches:
                try:
                    # 转换为浮点数并添加到坐标列表（注意顺序：纬度在前，经度在后）
                    lat = float(match[0])
                    lon = float(match[1])
                    coordinates.append((lon, lat))  # 按 (经度, 纬度) 顺序存储
                except ValueError:
                    # 忽略无法转换的匹配
                    continue

    except FileNotFoundError:
        print(f"错误：找不到文件 '{file_path}'")
        return None
    except Exception as e:
        print(f"错误：读取文件时发生异常: {e}")
        return None

    return coordinates


# 计算出
def calculate_min_max_avg_coordinates(coordinates):
    """计算经纬度的最大、最小和平均值"""
    if not coordinates:
        print("错误：没有找到有效的经纬度坐标")
        # 返回：最小经度、最大经度、最小纬度、最大纬度、平均经度、平均纬度
        return None, None, None, None, None, None

    # 初始化极值为第一个坐标
    min_lon = max_lon = coordinates[0][0]
    min_lat = max_lat = coordinates[0][1]
    # 初始化经纬度总和（用于计算平均值）
    sum_lon = 0.0
    sum_lat = 0.0

    # 遍历所有坐标，更新极值 + 累加总和
    for lon, lat in coordinates:
        # 更新极值
        if lon < min_lon:
            min_lon = lon
        if lon > max_lon:
            max_lon = lon
        if lat < min_lat:
            min_lat = lat
        if lat > max_lat:
            max_lat = lat
        # 累加经纬度值
        sum_lon += lon
        sum_lat += lat

    # 计算平均值（除以有效坐标数量）
    avg_lon = round(sum_lon / len(coordinates), 8)
    avg_lat = round(sum_lat / len(coordinates), 8)

    lon_lat_messages = {
        "min_longitude": min_lon,
        "max_longitude": max_lon,
        "min_latitude": min_lat,
        "max_latitude": max_lat,
        "longitude": avg_lon,
        "latitude": avg_lat,
    }

    # 返回：极值 + 平均值
    return lon_lat_messages
