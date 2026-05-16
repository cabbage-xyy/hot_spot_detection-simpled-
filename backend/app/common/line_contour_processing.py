# 直线 + 轮廓 + 处理

import math
import cv2
import numpy as np
from sklearn.cluster import DBSCAN

# 强化边缘检测中的直线
def perform_edge_detection_and_line_fitting(gray):
    # 自适应中值滤波
    gray = cv2.medianBlur(gray, 9)
    # 高斯模糊
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    # 方向边缘检测（获取水平/竖直边缘掩码）
    sobelx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)  # 竖直边缘梯度（Gx）
    vertical_edges = cv2.Canny(np.uint8(np.absolute(sobelx)), 70, 150)

    sobely = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)  # 水平边缘梯度（Gy）
    horizontal_edges = cv2.Canny(np.uint8(np.absolute(sobely)), 50, 100)

    # 定义水平方向的线结构元素
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))  # 可调整宽度
    # 水平方向膨胀
    horizontal_dilated = cv2.dilate(horizontal_edges, horizontal_kernel, iterations=1)

    # 定义垂直方向的线结构元素
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 15))  # 可调整高度
    # 垂直方向膨胀
    vertical_dilated = cv2.dilate(vertical_edges, vertical_kernel, iterations=1)

    # 合并线定向膨胀后的结果
    edges = cv2.bitwise_or(horizontal_dilated, vertical_dilated)

    # 进行霍夫变换和直线拟合
    lines = cv2.HoughLinesP(edges, 1, np.pi * 5 / 180, threshold=50, minLineLength=50, maxLineGap=10)
    line_image = np.zeros_like(edges)
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            cv2.line(line_image, (x1, y1), (x2, y2), (255,), 2)

    return line_image

#直接延长直线
def zhijieyanchang(gray):
    # 1. 图像预处理（滤波降噪）
    gray = cv2.medianBlur(gray, 9)  # 自适应中值滤波
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)  # 高斯模糊

    # 2. 方向边缘检测（分离水平/竖直边缘）
    # 竖直边缘（Gx，用于后续竖直直线检测与延长）
    sobelx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)
    vertical_edges = cv2.Canny(np.uint8(np.absolute(sobelx)), 70, 150)
    # 水平边缘（Gy，用于后续水平直线检测，作为竖直直线延长的终止条件）
    sobely = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
    horizontal_edges = cv2.Canny(np.uint8(np.absolute(sobely)), 50, 100)

    # 3. 边缘膨胀增强（突出直线连续性，便于霍夫检测）
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
    horizontal_dilated = cv2.dilate(horizontal_edges, horizontal_kernel, iterations=1)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 15))
    vertical_dilated = cv2.dilate(vertical_edges, vertical_kernel, iterations=1)
    edges = cv2.bitwise_or(horizontal_dilated, vertical_dilated)

    # 4. 霍夫直线检测（获取所有水平/竖直直线）
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,  # 全角度检测，确保同时获取水平/竖直直线
        threshold=50,
        minLineLength=50,
        maxLineGap=10
    )
    line_image = np.zeros_like(edges)
    if lines is None:
        return line_image  # 无直线时直接返回空图

    # 4.1 分离水平直线与竖直直线（为后续延长逻辑做准备）
    horizontal_lines = []  # 存储水平直线：(x1, y1, x2, y2, y_coord)，y_coord为水平直线的y值（近似不变）
    vertical_lines = []    # 存储竖直直线：(x1, y1, x2, y2, x_avg)，x_avg为竖直直线的基准x值（固定）

    # 工具函数：判断直线是否为水平/竖直
    def is_horizontal(x1, y1, x2, y2, angle_thresh=5):
        """判断是否为水平直线（与水平方向夹角≤angle_thresh）"""
        if x1 == x2:
            return False
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        angle = math.degrees(math.atan(dy / dx))
        return angle <= angle_thresh

    def is_vertical(x1, y1, x2, y2, angle_thresh=5):
        """判断是否为竖直直线（与竖直方向夹角≤angle_thresh）"""
        if y1 == y2:
            return False
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        angle = math.degrees(math.atan(dx / dy))
        return angle <= angle_thresh

    # 遍历直线，分类并绘制原始直线（水平/竖直均保留，不修改）
    for line in lines:
        x1, y1, x2, y2 = line[0]
        # 绘制原始直线（确保水平直线不变，竖直直线原始部分保留）
        cv2.line(line_image, (x1, y1), (x2, y2), (255,), 2)

        # 分类水平/竖直直线
        if is_horizontal(x1, y1, x2, y2):
            # 水平直线：y值近似不变，记录其y坐标（取平均值减少误差）
            y_coord = int((y1 + y2) / 2)
            horizontal_lines.append((x1, y1, x2, y2, y_coord))
        elif is_vertical(x1, y1, x2, y2):
            # 竖直直线：记录其基准x值（固定，用于延长时保持x不变）和原始y范围
            x_avg = int((x1 + x2) / 2)
            orig_y_min = min(y1, y2)  # 原始上端点y值
            orig_y_max = max(y1, y2)  # 原始下端点y值
            vertical_lines.append((x1, y1, x2, y2, x_avg, orig_y_min, orig_y_max))

    # 5. 核心逻辑：延长竖直直线至水平直线（延长距离≤100像素）
    max_extend_dist = 100  # 最大延长距离（像素）
    height, width = line_image.shape[:2]

    # 遍历每条竖直直线，执行延长
    for (v_x1, v_y1, v_x2, v_y2, v_x_avg, orig_y_min, orig_y_max) in vertical_lines:
        # 5.1 确定竖直直线的延长方向（向上、向下，或双向）
        # 向上延长：从原始上端点（orig_y_min）向上找水平直线
        # 向下延长：从原始下端点（orig_y_max）向下找水平直线
        extend_up = True
        extend_down = True

        # 5.2 向上延长：寻找上方最近的水平直线（且延长距离≤100）
        if extend_up:
            # 上方水平直线筛选条件：y坐标 < orig_y_min（在原始上端点上方），且与竖直直线x范围重叠
            candidate_h_lines_up = []
            for (h_x1, h_y1, h_x2, h_y2, h_y) in horizontal_lines:
                # 条件1：水平直线在原始上端点上方
                if not (h_y < orig_y_min):
                    continue
                # 条件2：水平直线的x范围与竖直直线的x_avg重叠（确保相交）
                if not (min(h_x1, h_x2) - 2 <= v_x_avg <= max(h_x1, h_x2) + 2):
                    continue
                # 条件3：延长距离（orig_y_min - h_y）≤100像素
                extend_dist_up = orig_y_min - h_y
                if extend_dist_up > max_extend_dist:
                    continue
                # 符合条件的水平直线：记录其y坐标和延长距离
                candidate_h_lines_up.append((h_y, extend_dist_up))

            # 取上方最近的水平直线（延长距离最小的）
            if candidate_h_lines_up:
                candidate_h_lines_up.sort(key=lambda x: x[1])  # 按延长距离升序
                target_h_y_up = candidate_h_lines_up[0][0]  # 目标水平直线的y坐标
                # 绘制向上延长的线段（x固定为v_x_avg，y从target_h_y_up到orig_y_min）
                cv2.line(line_image, (v_x_avg, target_h_y_up), (v_x_avg, orig_y_min), (255,), 2)

        # 5.3 向下延长：寻找下方最近的水平直线（且延长距离≤100）
        if extend_down:
            # 下方水平直线筛选条件：y坐标 > orig_y_max（在原始下端点下方），且与竖直直线x范围重叠
            candidate_h_lines_down = []
            for (h_x1, h_y1, h_x2, h_y2, h_y) in horizontal_lines:
                # 条件1：水平直线在原始下端点下方
                if not (h_y > orig_y_max):
                    continue
                # 条件2：水平直线的x范围与竖直直线的x_avg重叠（确保相交）
                if not (min(h_x1, h_x2) - 2 <= v_x_avg <= max(h_x1, h_x2) + 2):
                    continue
                # 条件3：延长距离（h_y - orig_y_max）≤100像素
                extend_dist_down = h_y - orig_y_max
                if extend_dist_down > max_extend_dist:
                    continue
                # 符合条件的水平直线：记录其y坐标和延长距离
                candidate_h_lines_down.append((h_y, extend_dist_down))

            # 取下方最近的水平直线（延长距离最小的）
            if candidate_h_lines_down:
                candidate_h_lines_down.sort(key=lambda x: x[1])  # 按延长距离升序
                target_h_y_down = candidate_h_lines_down[0][0]  # 目标水平直线的y坐标
                # 绘制向下延长的线段（x固定为v_x_avg，y从orig_y_max到target_h_y_down）
                cv2.line(line_image, (v_x_avg, orig_y_max), (v_x_avg, target_h_y_down), (255,), 2)

    return line_image

# 输入 图像的左半边，输出 拟合后的边缘直线，黑色大区域外轮廓，黑色大区域范围内的白色区域轮廓
def draw_contours(left_half_image, min_distance=10, angle_threshold=5, distance_threshold=20):
    # 提取G通道并二值化
    g_channel = left_half_image[:, :, 1]
    _, binary_g = cv2.threshold(g_channel, 80, 255, cv2.THRESH_BINARY)

    # 填充内部白色小点（先腐蚀后膨胀的闭运算）
    kernel = np.ones((3, 3), np.uint8)
    # 闭运算填充小孔
    closed = cv2.morphologyEx(binary_g, cv2.MORPH_CLOSE, kernel, iterations=1)
    # 腐蚀操作去除边缘小突起
    eroded = cv2.erode(closed, kernel, iterations=1)
    binary_g = eroded  # 使用处理后的图像继续后续操作

    # 去除窄黑色区域
    inverted = cv2.bitwise_not(binary_g)
    distance = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)
    narrow_mask = (distance < min_distance).astype(np.uint8) * 255

    # 计算外围黑色区域掩码
    contours, _ = cv2.findContours(binary_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer_black_mask = np.zeros_like(binary_g)
    if contours:
        hull = cv2.convexHull(np.vstack(contours))
        cv2.drawContours(outer_black_mask, [hull], -1, (255,), -1)
        outer_black_mask = cv2.bitwise_not(outer_black_mask)

    # 生成最终二值图
    remove_mask = cv2.bitwise_and(narrow_mask, cv2.bitwise_not(outer_black_mask))
    result_binary = binary_g.copy()
    result_binary[remove_mask == 255] = 255

    # 提取最大黑色区域
    black_regions = cv2.bitwise_not(result_binary)  # 黑色区域转为白色便于检测
    contours, _ = cv2.findContours(black_regions, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [], None, []

    # 新增：过滤面积小于10000的轮廓，仅保留面积达标者
    valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) >= 10000]
    # 若过滤后无有效轮廓，返回空结果
    if not valid_contours:
        return [], None, []

    max_contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(max_contour)

    # 提取黑色区域内的白色区域轮廓
    roi = result_binary[y:y + h, x:x + w]
    inner_white = cv2.bitwise_and(roi, roi)  # 白色区域保留
    inner_contours, _ = cv2.findContours(inner_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 转换内轮廓坐标到原图
    adjusted_inner = []
    for cnt in inner_contours:
        cnt_adjusted = cnt + np.array([x, y], dtype=np.int32)
        adjusted_inner.append(cnt_adjusted)

    # 提取边缘直线并聚类
    roi_inverted = cv2.bitwise_not(roi)
    edges = cv2.Canny(roi_inverted, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 30, minLineLength=20, maxLineGap=10)

    detected_lines = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            detected_lines.append(((x1 + x, y1 + y), (x2 + x, y2 + y)))

    # 直线聚类与拟合
    if not detected_lines:
        return [], max_contour, adjusted_inner

    # 提取直线特征
    line_features = []
    for (pt1, pt2) in detected_lines:
        x1, y1 = pt1
        x2, y2 = pt2
        angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi
        angle = (angle + 90) % 180 - 90
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        line_features.append((angle, mid_x, mid_y, pt1, pt2))

    # 角度聚类
    angles = np.array([f[0] for f in line_features]).reshape(-1, 1)
    angle_clusters = DBSCAN(eps=angle_threshold, min_samples=1).fit_predict(angles)
    num_clusters = len(np.unique(angle_clusters))

    # 位置聚类
    clustered_lines = []
    for cluster_id in range(num_clusters):
        cluster_mask = (angle_clusters == cluster_id)
        cluster = [line_features[i] for i in np.where(cluster_mask)[0]]
        mid_points = np.array([(f[1], f[2]) for f in cluster])
        pos_clusters = DBSCAN(eps=distance_threshold, min_samples=1).fit_predict(mid_points)
        pos_cluster_ids = np.unique(pos_clusters)

        for pos_id in pos_cluster_ids:
            pos_mask = (pos_clusters == pos_id)
            pos_cluster = [cluster[i] for i in np.where(pos_mask)[0]]
            clustered_lines.append(pos_cluster)

    # 拟合长直线
    fitted_lines = []
    for cluster in clustered_lines:
        points = []
        for f in cluster:
            points.append(f[3])
            points.append(f[4])
        points = np.array(points, dtype=np.float32)

        if len(points) < 2:
            continue

        x_coords = points[:, 0]
        y_coords = points[:, 1]
        A = np.vstack([x_coords, np.ones(len(x_coords))]).T
        k, b = np.linalg.lstsq(A, y_coords, rcond=None)[0]

        x_min, x_max = np.min(x_coords), np.max(x_coords)
        y_min = k * x_min + b
        y_max = k * x_max + b

        fitted_lines.append(((int(x_min), int(y_min)), (int(x_max), int(y_max))))

    return fitted_lines, max_contour, adjusted_inner

# 输入原始图像，输出延长后的直线图，黑色大区域外轮廓，黑色区域内白色区域轮廓
def process_line_image(image):
    # 转换为灰度图
    gray = 0.6 * image[:, :, 2] + 0.3 * image[:, :, 1] + 0.1 * image[:, :, 0]  # R*0.6 + G*0.3 + B*0.1
    gray = np.uint8(gray)

    # 自适应中值滤波
    gray = cv2.medianBlur(gray, 9)
    # 高斯模糊
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    # 方向边缘检测（只关注竖直边缘）
    sobelx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)  # 竖直边缘梯度（Gx）
    vertical_edges = cv2.Canny(np.uint8(np.absolute(sobelx)), 70, 150)
    sobely = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)#水平
    horizontal_edges = cv2.Canny(np.uint8(np.absolute(sobely)), 50, 100)

    # 定义垂直方向的线结构元素并膨胀
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 15))
    vertical_dilated = cv2.dilate(vertical_edges, vertical_kernel, iterations=1)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))  # 水平核：长横短竖
    horizontal_dilated = cv2.dilate(horizontal_edges, horizontal_kernel, iterations=1)

    edges = cv2.bitwise_or(horizontal_dilated, vertical_dilated)

    # 霍夫变换提取直线（更倾向于检测竖直方向直线）
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,  # 全角度检测（0~180°）
        threshold=50,
        minLineLength=50,
        maxLineGap=10
    )
    line_image = np.zeros_like(edges)
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            cv2.line(line_image, (x1, y1), (x2, y2), (255,), 2)

    # 第二部分: 轮廓提取与处理
    # 提取G通道并二值化
    g_channel = image[:, :, 1]
    _, binary_g = cv2.threshold(g_channel, 80, 255, cv2.THRESH_BINARY)

    # 形态学操作优化二值图
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(binary_g, cv2.MORPH_CLOSE, kernel, iterations=1)  # 填充小孔
    eroded = cv2.erode(closed, kernel, iterations=1)  # 去除边缘小突起
    binary_g = eroded

    # 去除窄黑色区域
    inverted = cv2.bitwise_not(binary_g)
    distance = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)
    narrow_mask = (distance < 10).astype(np.uint8) * 255  # min_distance=10

    # 计算所有轮廓（用于后续判断）
    contours, _ = cv2.findContours(binary_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    all_contours = []
    if contours:
        for cnt in contours:
            all_contours.append(cnt)

    # 计算外围黑色区域掩码
    outer_black_mask = np.zeros_like(binary_g)
    if contours:
        hull = cv2.convexHull(np.vstack(contours))
        # 确保hull格式正确
        hull = hull.reshape(-1, 1, 2).astype(np.int32)
        cv2.drawContours(outer_black_mask, [hull], -1, (255,), -1)
        outer_black_mask = cv2.bitwise_not(outer_black_mask)

    # 生成最终二值图
    remove_mask = cv2.bitwise_and(narrow_mask, cv2.bitwise_not(outer_black_mask))
    result_binary = binary_g.copy()
    result_binary[remove_mask == 255] = 255

    # 提取最大黑色区域（外轮廓）
    black_regions = cv2.bitwise_not(result_binary)
    contours, _ = cv2.findContours(black_regions, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.zeros_like(line_image), None, []

    max_contour = max(contours, key=cv2.contourArea)

    x, y, w, h = cv2.boundingRect(max_contour)
    # 提取黑色区域内的白色区域轮廓
    roi = result_binary[y:y + h, x:x + w]
    inner_white = cv2.bitwise_and(roi, roi)
    inner_contours, _ = cv2.findContours(inner_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 转换内轮廓坐标到原图
    adjusted_inner = []
    for cnt in inner_contours:
        cnt_adjusted = cnt + np.array([x, y], dtype=np.int32)
        adjusted_inner.append(cnt_adjusted)

    # 合并所有轮廓用于检测
    all_contours = [max_contour] + adjusted_inner

    # 检测上下方黑色填充区的边界（关键修改）
    # 1. 检测图像最上方的黑色填充边界（上边界）
    top_boundary = 0
    # 从顶部向下扫描，找到非黑色区域的第一个行索引
    for y in range(image.shape[0]):
        row_avg = np.mean(gray[y, :])  # 使用之前计算的gray图
        if row_avg > 50:  # 非黑色区域（阈值可调整）
            top_boundary = y
            break

    # 2. 检测图像最下方的黑色填充边界（下边界）
    bottom_boundary = image.shape[0] - 1
    # 从底部向上扫描，找到非黑色区域的最后一个行索引
    for y in range(image.shape[0] - 1, -1, -1):
        row_avg = np.mean(gray[y, :])
        if row_avg > 50:  # 非黑色区域（阈值与上方一致）
            bottom_boundary = y
            break
    # 核心部分: 基于端点位置的直线延长（只进行竖直方向延伸）
    height, width = line_image.shape[:2]
    extended_line_image = line_image.copy()
    # 图像垂直中心（用于方向限制）
    img_center_y = height // 2
    half_height = height // 4  # 中间1/2区域的半高
    center_region_min_y = img_center_y - half_height  # 中间区域上边界
    center_region_max_y = img_center_y + half_height  # 中间区域下边界
    # 最大延长距离（100像素）
    max_extend_dist = 100

    # 函数：判断直线是否接近竖直（角度阈值可调整）
    def is_vertical_line(x1, y1, x2, y2, angle_threshold=5):
        if x1 == x2:  # 完全竖直
            return True
        # 计算直线与竖直方向的夹角（度）
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        angle_to_vertical = 90 - math.degrees(math.atan(dx / dy))
        return abs(angle_to_vertical) <= angle_threshold  # 接近竖直

    def is_horizontal_line(x1, y1, x2, y2, angle_threshold=5):
        if y1 == y2:  # 竖直直线（x不变），直接排除
            return False
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        # 计算直线与水平方向的夹角（水平方向为0°，夹角越小越接近水平）
        angle_to_horizontal = math.degrees(math.atan(dy / dx))
        return abs(angle_to_horizontal) <= angle_threshold  # 接近水平

    # 函数：寻找竖直线与轮廓的交点（仅保留有效区域内）
    def find_vertical_intersection(contour, x_coord):
        intersections = []
        epsilon = 0.01 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)

        for i in range(len(approx)):
            p1 = approx[i][0]
            p2 = approx[(i + 1) % len(approx)][0]
            x3, y3 = p1
            x4, y4 = p2

            if (x3 <= x_coord <= x4) or (x4 <= x_coord <= x3):
                if x4 != x3:
                    t = (x_coord - x3) / (x4 - x3)
                    y = y3 + t * (y4 - y3)
                    y = int(round(y))
                    if top_boundary <= y <= bottom_boundary:
                        intersections.append((int(x_coord), y))
        return intersections

    # 仅对竖直直线进行延长处理（不影响非竖直直线）
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]

            # 跳过水平直线（不延长，保留原始绘制）
            if is_horizontal_line(x1, y1, x2, y2):
                continue
            # 只处理接近竖直的直线
            if not is_vertical_line(x1, y1, x2, y2):
                continue

            # 计算竖直直线的基准x坐标（平均x值）
            x_avg = int((x1 + x2) / 2)
            # 明确端点角色：A（下端，y值大）、B（上端，y值小）
            if y1 > y2:
                A, B = (int(x1), int(y1)), (int(x2), int(y2))
            else:
                A, B = (int(x2), int(y2)), (int(x1), int(y1))
            A_x, A_y = A
            B_x, B_y = B

            # 匹配端点所在轮廓（判断端点是否在轮廓内）
            contour_A = None  # A端点（下端）的轮廓
            contour_B = None  # B端点（上端）的轮廓
            for cnt in all_contours:
                if cv2.pointPolygonTest(cnt, A, False) >= 0:
                    contour_A = cnt
                if cv2.pointPolygonTest(cnt, B, False) >= 0:
                    contour_B = cnt

            # 原始直线的y范围（上端点B的y→下端点A的y）
            orig_y_min = B_y
            orig_y_max = A_y
            extend_up = False  # 是否向上延长（针对B端点）
            extend_down = False  # 是否向下延长（针对A端点）

            # 8.5 核心规则：根据端点区域和轮廓判断延长方向
            # 检查端点是否在中间1/2区域
            A_in_middle = center_region_min_y <= A_y <= center_region_max_y
            B_in_middle = center_region_min_y <= B_y <= center_region_max_y

            # 规则1：AB都在中间1/2 → 不延长
            if A_in_middle and B_in_middle:
                continue
#contour_B is None and
            # 规则2：A在中间、B在上方1/4 → 仅判断B的上延条件
            if A_in_middle and not B_in_middle:
                # B不在轮廓内 + B在中心上方 → 允许向上延长
                if B_y < img_center_y:
                    extend_up = True
#contour_A is None and
            # 规则3：B在中间、A在下方1/4 → 仅判断A的下延条件
            elif B_in_middle and not A_in_middle:
                # A不在轮廓内 + A在中心下方 → 允许向下延长
                if    A_y >= img_center_y:
                    extend_down = True

            # 规则4：A在下方1/4、B在上方1/4 → 分别判断上下延条件
            else:
                # 上延：B不在轮廓内 + B在中心上方
                #contour_B is None and
                if B_y < img_center_y:
                    extend_up = True
                # 下延：A不在轮廓内 + A在中心下方
                #contour_A is None and
                if A_y >= img_center_y:
                    extend_down = True

            # 8.6 计算延长终点（带最大距离100像素限制）
            new_y_min = orig_y_min
            new_y_max = orig_y_max

            # 向上延长（针对B端点）
            if extend_up:
                intersections_up = []
                # 遍历所有轮廓，寻找竖直线与轮廓的上方交点
                for cnt in all_contours:
                    intersections_up.extend(find_vertical_intersection(cnt, x_avg))
                if intersections_up:
                    # 筛选出在原始直线上方的有效交点
                    valid_up = [p for p in intersections_up if p[1] < orig_y_min]
                    if valid_up:
                        candidate_y_min = min(valid_up, key=lambda p: p[1])[1]
                        # 限制最大上延距离（不超过100像素）
                        max_allow_y_min = orig_y_min - max_extend_dist
                        new_y_min = max(candidate_y_min, max_allow_y_min)
                # 确保不超过上方有效边界
                new_y_min = max(new_y_min, top_boundary)

            # 向下延长（针对A端点）
            if extend_down:
                intersections_down = []
                # 遍历所有轮廓，寻找竖直线与轮廓的下方交点
                for cnt in all_contours:
                    intersections_down.extend(find_vertical_intersection(cnt, x_avg))
                if intersections_down:
                    # 筛选出在原始直线下方的有效交点
                    valid_down = [p for p in intersections_down if p[1] > orig_y_max]
                    if valid_down:
                        candidate_y_max = max(valid_down, key=lambda p: p[1])[1]
                        # 限制最大下延距离（不超过100像素）
                        max_allow_y_max = orig_y_max + max_extend_dist
                        new_y_max = min(candidate_y_max, max_allow_y_max)
                # 确保不超过下方有效边界
                new_y_max = min(new_y_max, bottom_boundary)

            # 8.7 绘制延长线段（仅绘制延长部分，不覆盖原始直线）
            if new_y_min < orig_y_min:
                cv2.line(extended_line_image, (x_avg, new_y_min), (x_avg, orig_y_min), (255,), 2)
            if new_y_max > orig_y_max:
                cv2.line(extended_line_image, (x_avg, orig_y_max), (x_avg, new_y_max), (255,), 2)

        # 返回延长后的直线图、最大黑色区域轮廓、内轮廓列表
    return extended_line_image, max_contour, adjusted_inner

# 输入 图像的左半边，输出 拟合后的边缘直线，黑色大区域外轮廓，黑色大区域范围内的白色区域轮廓
def draw_valid_contours(left_half_image):
    """
    提取左半边图像中所有符合条件的黑色大区域轮廓
    参数：
        left_half_image: 输入的左半边图像（BGR格式）
        min_distance: 去除窄黑色区域的距离阈值（默认10像素）
        min_area: 黑色大区域的最小面积阈值（默认10000像素，可根据实际调整）
    返回：
        all_black_big_contours: 所有黑色大区域的轮廓列表（每个轮廓为numpy.ndarray，格式( n,1,2 )，符合OpenCV要求）
                                无有效区域时返回空列表
    """
    # 1. 提取G通道并二值化（突出黑色区域：G通道值<160的区域转为0（黑色），≥160转为255（白色））
    g_channel = left_half_image[:, :, 1]
    _, binary_g = cv2.threshold(g_channel, 160, 255, cv2.THRESH_BINARY)

    # 2. 形态学优化：填充小孔、去除边缘小突起（保留原逻辑，确保黑色区域完整）
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(binary_g, cv2.MORPH_CLOSE, kernel, iterations=1)  # 闭运算：先膨胀后腐蚀，填充内部小孔
    eroded = cv2.erode(closed, kernel, iterations=1)  # 腐蚀：去除边缘细小白色突起，避免干扰黑色区域轮廓
    binary_g = eroded

    # 3. 去除窄黑色区域（避免细窄黑色条纹被误判为“大区域”）
    inverted = cv2.bitwise_not(binary_g)  # 黑白反转：黑色区域（0）→ 白色（255），便于距离变换计算
    distance = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)  # 计算白色区域（原黑色区域）到最近黑色的距离
    narrow_mask = (distance < 10).astype(np.uint8) * 255  # 距离<min_distance的“窄区域”掩码

    # 4. 生成外围黑色区域掩码（排除图像最外围的无效黑色区域）
    outer_contours, _ = cv2.findContours(binary_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer_black_mask = np.zeros_like(binary_g)
    if outer_contours:
        # 生成所有外围轮廓的凸包（覆盖图像内主要有效区域）
        hull = cv2.convexHull(np.vstack(outer_contours))
        cv2.drawContours(outer_black_mask, [hull], -1, (255,), -1)  # 填充凸包为白色
        outer_black_mask = cv2.bitwise_not(outer_black_mask)  # 反转：凸包内（有效黑色区域范围）→ 白色（255）

    # 5. 生成最终黑色区域二值图（移除窄区域，保留完整黑色大区域）
    remove_mask = cv2.bitwise_and(narrow_mask, cv2.bitwise_not(outer_black_mask))  # 需移除的“窄且在有效范围外”的区域
    result_binary = binary_g.copy()
    result_binary[remove_mask == 255] = 255  # 将需移除的区域设为白色，剩余即为完整黑色大区域

    # 6. 提取所有黑色区域的轮廓（核心：批量获取符合条件的黑色大区域）
    black_regions = cv2.bitwise_not(result_binary)  # 黑色区域→白色（255），便于OpenCV轮廓检测
    all_contours, _ = cv2.findContours(black_regions, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 7. 筛选“面积≥min_area”的黑色大区域轮廓，并统一格式
    all_black_big_contours = []
    for cnt in all_contours:
        # 过滤面积过小的轮廓（排除小黑色斑点）
        if cv2.contourArea(cnt) >= 10000:
            # 统一轮廓格式为 (n, 1, 2)（OpenCV函数标准格式，适配pointPolygonTest）
            if len(cnt.shape) != 3:
                cnt = cnt.reshape(-1, 1, 2).astype(np.int32)
            all_black_big_contours.append(cnt)

    # 8. 容错：无有效黑色大区域时返回空列表
    if not all_black_big_contours:
        return []

    return all_black_big_contours

# 去除窄黑色区域后，输出剩余的黑色大区域（二值化图像）
def remove_narrow_black_regions(binary_g):
    # 1. 预处理：填充小孔和去除边缘突起
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(binary_g, cv2.MORPH_CLOSE, kernel, iterations=1)  # 填充小孔
    eroded = cv2.erode(closed, kernel, iterations=1)  # 去除边缘突起
    binary = eroded

    # 2. 标记需要去除的窄黑色区域
    inverted = cv2.bitwise_not(binary)
    distance = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)
    narrow_mask = (distance < 10).astype(np.uint8) * 255  # 距离<10的窄区域

    # 3. 标记需要保留的外围黑色区域
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer_black_mask = np.zeros_like(binary)
    if contours:
        hull = cv2.convexHull(np.vstack(contours))
        cv2.drawContours(outer_black_mask, [hull], -1, (255,), -1)
        outer_black_mask = cv2.bitwise_not(outer_black_mask)  # 外围黑色区域为255

    # 4. 生成最终去除掩码（仅去除内部窄黑色区域）
    remove_mask = cv2.bitwise_and(narrow_mask, cv2.bitwise_not(outer_black_mask))

    # 5. 去除窄黑色区域，得到初步处理结果
    result = binary.copy()
    result[remove_mask == 255] = 255  # 窄黑色区域→白色

    # 6. 提取并保留黑色大区域（过滤小面积黑色区域）
    # 反转图像：黑色区域→白色（便于轮廓检测）
    black_regions = cv2.bitwise_not(result)
    contours, _ = cv2.findContours(black_regions, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 创建空白图像，用于绘制黑色大区域
    remaining_black = np.full_like(result, 255, dtype=np.uint8)  # 初始全白（背景）
    for cnt in contours:
        # 仅保留面积≥min_area的黑色区域（大区域）
        if cv2.contourArea(cnt) >= 10000:
            cv2.drawContours(remaining_black, [cnt], -1, (0,), -1)  # 填充为黑色（0）

    return remaining_black


def get_large_black_regions(binary_img):
    """
    从二值图像中提取大块黑色区域（去除窄小黑色区域）

    参数:
        binary_img: 输入的二值图像（白色为255，黑色为0）
        min_distance: 最小距离阈值，小于此值的窄黑色区域会被去除

    返回:
        处理后的二值图像，仅保留大块黑色区域
    """
    # 确保输入是二值图像
    _, binary = cv2.threshold(binary_img, 120, 255, cv2.THRESH_BINARY)

    # 闭运算填充内部白色小点
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 腐蚀操作去除边缘小突起
    eroded = cv2.erode(closed, kernel, iterations=1)

    # 对白色区域进行距离变换，计算黑色像素到最近白色区域的距离
    inverted = cv2.bitwise_not(eroded)
    distance = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)

    # 筛选出距离小于阈值的窄黑色区域
    narrow_mask = (distance < 10).astype(np.uint8) * 255

    # 找到白色区域的轮廓，确定外围黑色区域
    contours, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer_black_mask = np.zeros_like(eroded)

    if contours:
        # 填充最外层轮廓之外的区域（外围黑色区域）
        hull = cv2.convexHull(np.vstack(contours))
        cv2.drawContours(outer_black_mask, [hull], -1, (255,), -1)
        outer_black_mask = cv2.bitwise_not(outer_black_mask)

    # 生成最终需要去除的黑色区域掩码（排除外围黑色区域）
    remove_mask = cv2.bitwise_and(narrow_mask, cv2.bitwise_not(outer_black_mask))

    # 去除窄黑色区域，保留大块黑色区域
    result = eroded.copy()
    result[remove_mask == 255] = 255  # 将窄黑色区域转为白色

    return result