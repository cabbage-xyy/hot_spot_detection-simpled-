# 卡顿相关的所有操作
import cv2
import numpy as np


# 检测视频或图像序列中是否出现 “卡顿”（即物体位置几乎没有变化）
def check_freeze_with_5frame_gap(current_h, current_v, five_ago_h, five_ago_v, threshold):
    # # 它通过比较当前帧和 5 帧前的行列坐标数据，计算它们的平均位置变化量，然后与设定的阈值进行比较，判断是否发生了卡顿
    # 验证输入数据格式（current_h为column_data，current_v为row_data，均为字典）
    if not isinstance(current_h, dict) or not isinstance(current_v, dict) or \
            not isinstance(five_ago_h, dict) or not isinstance(five_ago_v, dict):
        return False

    # 1. 计算水平方向（列）的坐标变化量（column_data：key=col_num，value=col_x）
    common_cols = set(current_h.keys()) & set(five_ago_h.keys())  # 基于col_num匹配共同列

    col_diffs = []
    for col_num in common_cols:
        curr_x = current_h[col_num]  # 从column_data获取当前列x坐标
        prev_x = five_ago_h[col_num]  # 5帧前列x坐标
        # 验证坐标格式（确保是数值）
        if isinstance(curr_x, (int, float)) and isinstance(prev_x, (int, float)):
            diff = abs(curr_x - prev_x)
            col_diffs.append(diff)
        else:
            print(f"    列 {col_num} 坐标格式无效，跳过")

    # 2. 计算垂直方向（行）的坐标变化量（row_data：key=row_num，value=row_y）
    common_rows = set(current_v.keys()) & set(five_ago_v.keys())  # 基于row_num匹配共同行

    row_diffs = []
    for row_num in common_rows:
        curr_y = current_v[row_num]  # 从row_data获取当前行y坐标
        prev_y = five_ago_v[row_num]  # 5帧前行y坐标
        # 验证坐标格式（确保是数值）
        if isinstance(curr_y, (int, float)) and isinstance(prev_y, (int, float)):
            diff = abs(curr_y - prev_y)
            row_diffs.append(diff)
        else:
            print(f"    行 {row_num} 坐标格式无效，跳过")

    # 3. 处理无共同行列的特殊情况
    if not col_diffs and not row_diffs:
        return False

    # 4. 计算水平/垂直方向的平均变化量
    avg_col_diff = sum(col_diffs) / len(col_diffs) if col_diffs else 0
    avg_row_diff = sum(row_diffs) / len(row_diffs) if row_diffs else 0
    # print(f"\n[变化量计算] 水平平均变化量: {avg_col_diff:.2f}, 垂直平均变化量: {avg_row_diff:.2f}")

    # 5. 卡顿判断
    is_freeze = avg_col_diff < threshold and avg_row_diff < threshold

    return is_freeze


# 通过对比当前帧与上一帧的行列坐标数据，判断整体运动趋势是否趋于 “稳定” 或 “卡顿”
def check_coordinates_freeze(current_h, current_v, prev_h, prev_v):
    """分析坐标变化的 “主导方向” 和 “稳定性”，当行列变化都没有明显趋势或变化很小，就认为发生了卡顿"""
    if not isinstance(current_h, dict) or not isinstance(current_v, dict) or \
            not isinstance(prev_h, dict) or not isinstance(prev_v, dict):
        return False
    # 1. 计算所有列的x坐标变化量
    col_diffs = []
    for col_id in set(current_h.keys()) & set(prev_h.keys()):
        curr_col = current_h[col_id]
        prev_col = prev_h[col_id]

        # 验证坐标格式是否为可索引的结构（列表/元组）
        if not isinstance(curr_col, (list, tuple)) or len(curr_col) < 2:
            continue  # 跳过格式不正确的列
        if not isinstance(prev_col, (list, tuple)) or len(prev_col) < 2:
            continue  # 跳过格式不正确的列

        curr_x = curr_col[0]  # 安全访问 x 坐标
        prev_x = prev_col[0]
        col_diffs.append(curr_x - prev_x)

    # 2. 计算所有行的y坐标变化量
    row_diffs = []
    for row_id in set(current_v.keys()) & set(prev_v.keys()):
        curr_row = current_v[row_id]
        prev_row = prev_v[row_id]

        # 验证坐标格式是否为可索引的结构
        if not isinstance(curr_row, (list, tuple)) or len(curr_row) < 2:
            continue  # 跳过格式不正确的行
        if not isinstance(prev_row, (list, tuple)) or len(prev_row) < 2:
            continue  # 跳过格式不正确的行

        curr_y = curr_row[1]  # 安全访问 y 坐标
        prev_y = prev_row[1]
        row_diffs.append(curr_y - prev_y)

    # 3. 判断整体趋势：计算同向变化比例
    def get_dominant_direction(diffs):
        if not diffs:
            return 0, 0
        coordinate_threshold = 5
        positive = sum(1 for d in diffs if d > coordinate_threshold)
        negative = sum(1 for d in diffs if d < -coordinate_threshold)
        stable = sum(1 for d in diffs if abs(d) <= coordinate_threshold)

        total = len(diffs)
        if positive > negative and positive > stable:
            return positive / total, 1  # 正向为主
        elif negative > positive and negative > stable:
            return negative / total, -1  # 负向为主
        else:
            return stable / total, 0  # 稳定或分散为主

    col_dominance, col_dir = get_dominant_direction(col_diffs)
    row_dominance, row_dir = get_dominant_direction(row_diffs)

    # 4. 判断卡顿条件：
    # - 若行列主导方向一致性均低于阈值（如60%），视为卡顿
    # - 若行列主导方向均为稳定（变化小），视为卡顿
    is_freeze = (col_dominance < 0.6 and row_dominance < 0.6) or \
                (col_dir == 0 and row_dir == 0)

    return is_freeze


# 在输入图像中检测并提取关键点及其对应的描述符
def detect_features(frame):
    """
    OpenCV 中的 ORB（Oriented FAST and Rotated BRIEF）算法
    :param frame:  图像中的每一帧
    :return: 关键点，描述特征
    常用于：
      图像匹配（例如拼接、全景图）
      目标识别
      运动跟踪
      三维重建
    """
    orb = cv2.ORB_create(nfeatures=2000)  # type: ignore[attr-defined]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    kp, des = orb.detectAndCompute(gray, None)
    return kp, des


# 计算相邻两帧图像之间的特征点匹配，并根据匹配结果估计相机或物体的平移运动
def calculate_movement(prev_kp, prev_des, curr_kp, curr_des):
    """
      ORB 特征匹配和 仿射变换 来计算平移量，常用于：
      视频稳定
      运动跟踪
      视觉里程计
      相机姿态估计
    :param prev_kp: 上一帧图像中检测到的关键点列表
    :param prev_des: 上一帧图像中关键点对应的描述符矩阵
    :param curr_kp: 当前帧图像中检测到的关键点列表
    :param curr_des: 当前帧图像中关键点对应的描述符矩阵
    :return:
    """
    # 确保关键点是列表类型
    if isinstance(prev_kp, tuple):
        prev_kp = list(prev_kp)
    if isinstance(curr_kp, tuple):
        curr_kp = list(curr_kp)

    # 验证输入有效性
    if not isinstance(prev_kp, list) or not isinstance(curr_kp, list):
        return None
    if prev_des is None or curr_des is None:
        return None
    if len(prev_kp) == 0 or len(curr_kp) == 0:
        return None
    if prev_des.shape[0] == 0 or curr_des.shape[0] == 0:
        return None

    # 暴力匹配
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    good_matches = matcher.match(prev_des, curr_des)
    good_matches = sorted(good_matches, key=lambda x: x.distance)[:200]

    if len(good_matches) < 10:
        return None

    # 提取匹配点的坐标
    src_pts = np.float32([prev_kp[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([curr_kp[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    # 计算相似矩阵
    M, mask = cv2.estimateAffinePartial2D(src_pts, dst_pts, None, cv2.RANSAC, ransacReprojThreshold=3.0)

    # 检查相似矩阵是否成功计算
    if M is None:
        return None

    # 从相似矩阵中提取实际平移分量（不进行归一化）
    tx = M[0, 2]  # x方向的实际平移量
    ty = M[1, 2]  # y方向的实际平移量

    # 返回平移向量
    return np.array([tx, ty]), src_pts, dst_pts  # 返回(x, y)方向平均移动距离


# 根据一个平移运动向量，调整坐标字典中的行列坐标值
def apply_movement(coords, movement):
    """
      视频稳定：补偿相机的平移运动。
      坐标校正：将检测到的目标位置根据运动向量进行调整。
      图像配准：对齐不同帧的坐标系统。
    :param coords: 存放需要进行平移校正的坐标数据
    :param movement: 提供需要应用到坐标上的平移向量
    :return:
    """
    corrected = {'horizontal': {}, 'vertical': {}}
    # 修正列坐标（x方向）
    for col, x in coords['horizontal'].items():
        corrected['horizontal'][col] = x + movement[0]
    # 修正行坐标（y方向）
    for row, y in coords['vertical'].items():
        corrected['vertical'][row] = y + movement[1]
    return corrected