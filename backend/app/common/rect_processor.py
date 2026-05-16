# 对于矩形的操作

import cv2
import numpy as np

# 部分函数的参数量对不上，适量调整
# 判断两个矩形是否相邻，当矩形和矩形最近边之间的距离小于0.5倍的矩形宽时，认为在同一组
def is_adjacent(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2

    # 计算水平方向距离
    horizontal_distance = min(abs(x1 + w1 - x2), abs(x2 + w2 - x1))
    # 计算垂直方向距离
    vertical_distance = min(abs(y1 + h1 - y2), abs(y2 + h2 - y1))

    # 水平相邻且垂直偏移在阈值内，或者垂直相邻且水平偏移在阈值内,或者对角相邻
    horizontal_adjacent = horizontal_distance < 0.5 * min(w1, w2) and abs(y1 - y2) < 0.5 * (h1 + h2)
    vertical_adjacent = vertical_distance < 0.5 * min(h1, h2) and abs(x1 - x2) < 0.5 * (w1 + w2)

    return horizontal_adjacent or vertical_adjacent

# 判断是否对角相邻
def is_diagonal_adjacent(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2

    # 计算水平方向距离
    horizontal_distance = min(abs(x1 + w1 - x2), abs(x2 + w2 - x1))
    # 计算垂直方向距离
    vertical_distance = min(abs(y1 + h1 - y2), abs(y2 + h2 - y1))

    # 垂直偏移在阈值内且水平偏移在阈值内,判断为对角相邻
    diagonal_adjacent = horizontal_distance < 0.5 * min(w1, w2) and vertical_distance < 0.5

    return diagonal_adjacent

# 判断两个矩形是否重叠
def is_overlapping(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2

    # 计算重合部分的坐标
    x_left = max(x1, x2)
    y_top = max(y1, y2)
    x_right = min(x1 + w1, x2 + w2)
    y_bottom = min(y1 + h1, y2 + h2)

    # 计算重合部分的宽度和高度
    overlap_width = max(0, x_right - x_left)
    overlap_height = max(0, y_bottom - y_top)

    # 计算重合部分的面积
    overlap_area = overlap_width * overlap_height

    # 计算两个矩形的面积
    area1 = w1 * h1
    area2 = w2 * h2

    # 判断是否重叠
    return overlap_area >= 0.1 * min(area1, area2)

# 计算矩形与其他矩形在水平和垂直方向的偏差
def calculate_alignment(rect, other_rects):
    horizontal_dev = 0
    vertical_dev = 0
    for other_rect in other_rects:
        x1, y1, w1, h1 = rect
        x2, y2, w2, h2 = other_rect
        horizontal_dev += abs((x1 + x2 + w1 + w2) / 2)
        vertical_dev += abs((y1 + y2 + h1 + h2) / 2)
    return horizontal_dev, vertical_dev

# 筛选矩形，只保留面积大于15000，长宽都在各自中位数*0.7范围内，且长边比短边的比大于 1.7 小于 2.3 的矩形
def filter_rectangles_gai(rectangles, median_width, median_height, median_area):
    filtered_rectangles = []

    # 先过滤面积小于等于 15000 的矩形
    large_rectangles = []
    for rect in rectangles:
        x, y, w, h = rect
        area = w * h
        if median_area * 1.3 > area > median_area * 0.7:
            large_rectangles.append(rect)

    if not large_rectangles:
        return []

    for rect in large_rectangles:
        x, y, w, h = rect
        # 计算长边和短边
        long_side = max(w, h)
        short_side = min(w, h)
        aspect_ratio = long_side / short_side if short_side != 0 else 0
        # 检查矩形长宽长宽比
        if 1.5 < aspect_ratio < 2.3:
            filtered_rectangles.append(rect)

    final_rectangles = []
    for rect in filtered_rectangles:
        x, y, w, h = rect
        if (median_width * 0.7 <= w <= median_width * 1.3) and \
                (median_height * 0.7 <= h <= median_height * 1.3):
            final_rectangles.append(rect)

    return final_rectangles


def filter_rectangles_1(rectangles):
    filtered_rectangles = []

    # 先过滤面积小于等于 15000 的矩形
    large_rectangles = []
    for rect in rectangles:
        x, y, w, h = rect
        area = w * h
        if 30000 > area > 5000:
            large_rectangles.append(rect)

    if not large_rectangles:
        return []

    for rect in large_rectangles:
        x, y, w, h = rect
        # 计算长边和短边
        long_side = max(w, h)
        short_side = min(w, h)
        aspect_ratio = long_side / short_side if short_side != 0 else 0
        # 检查矩形长宽长宽比
        if 1.5 < aspect_ratio < 2.3:
            filtered_rectangles.append(rect)

    widths = [rect[2] for rect in filtered_rectangles]
    heights = [rect[3] for rect in filtered_rectangles]
    width_median = np.median(widths)
    height_median = np.median(heights)
    final_rectangles = []
    for rect in filtered_rectangles:
        x, y, w, h = rect
        if (width_median * 0.7 <= w <= width_median * 1.3) and \
                (height_median * 0.7 <= h <= height_median * 1.3):
            final_rectangles.append(rect)

    return final_rectangles

# 补充缺失的矩形，补充的矩形也要遵循矩形的筛选条件
def supplement_rectangles(image, rectangles):
    new_rectangles = rectangles.copy()
    widths = [rect[2] for rect in rectangles]
    heights = [rect[3] for rect in rectangles]
    width_median = np.median(widths)
    height_median = np.median(heights)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 43, 46])
    upper_green = np.array([77, 255, 255])
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    # 找到最右上方的矩形
    top_right_rect = max(rectangles, key=lambda r: (r[0] + r[2], -r[1]))
    # 找到最左下方的矩形
    bottom_left_rect = min(rectangles, key=lambda r: (r[0], r[1] + r[3]))

    def check_top_adjacent(rect):
        x, y, w, h = rect
        for r in rectangles:
            rx, ry, rw, rh = r
            if abs(y - ry) < h / 2 and x <= rx + rw and rx <= x + w:
                return True
        return False

    def check_bottom_adjacent(rect):
        x, y, w, h = rect
        for r in rectangles:
            rx, ry, rw, rh = r
            if abs(y + h - ry) < h / 2 and x <= rx + rw and rx <= x + w:
                return True
        return False

    # 检测最右上方矩形上方是否有矩形
    if not check_top_adjacent(top_right_rect):
        x, y, w, h = top_right_rect
        new_rect = (x, y - h, w, h)
        if new_rect not in new_rectangles:
            if filter_rectangles_1([new_rect]):
                new_rectangles.append(new_rect)

    # 检测最左下方矩形下方是否有矩形
    if not check_bottom_adjacent(bottom_left_rect):
        x, y, w, h = bottom_left_rect
        new_rect = (x, y + h, w, h)
        if new_rect not in new_rectangles:
            if filter_rectangles_1([new_rect]):
                new_rectangles.append(new_rect)

    return new_rectangles

# 处理重叠的矩形
def handle_overlapping_rectangles(rectangles):
    final_rectangles = []
    for i, rect1 in enumerate(rectangles):
        is_duplicate = False
        for j, rect2 in enumerate(rectangles):
            if i != j and is_overlapping(rect1, rect2):
                is_duplicate = True
                # 检查 rect1 是否与其他矩形都不重叠
                is_rect1_non_overlapping = all(not is_overlapping(rect1, r) for r in rectangles if r != rect1)
                # 检查 rect2 是否与其他矩形都不重叠
                is_rect2_non_overlapping = all(not is_overlapping(rect2, r) for r in rectangles if r != rect2)
                if is_rect1_non_overlapping:
                    final_rectangles.append(rect1)
                elif is_rect2_non_overlapping:
                    final_rectangles.append(rect2)
                else:
                    # 若两个矩形都与其他矩形重叠，保留排列最整齐的
                    dev1 = calculate_alignment(rect1, rectangles)
                    dev2 = calculate_alignment(rect2, rectangles)
                    if sum(dev1) < sum(dev2):
                        final_rectangles.append(rect1)
                    else:
                        final_rectangles.append(rect2)
                break
        if not is_duplicate:
            final_rectangles.append(rect1)
    return final_rectangles

# 过滤亮度明显低于其他矩形的矩形
# 保留亮度角均匀的矩形
def filter_rectangles_by_brightness(image, rectangles):
    if not rectangles:
        return []
    sample_step = 3
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness_stats = []

    # 1. 计算每个矩形的亮度特征
    for rect in rectangles:
        x, y, w, h = rect
        x, y = max(0, x), max(0, y)
        w, h = min(w, image.shape[1] - x), min(h, image.shape[0] - y)

        samples = []
        for i in range(y, y + h, sample_step):
            for j in range(x, x + w, sample_step):
                if i < gray.shape[0] and j < gray.shape[1]:
                    samples.append(gray[i, j])

        if not samples:
            continue

        samples = np.array(samples)
        q1 = np.quantile(samples, 0.25)
        q3 = np.quantile(samples, 0.75)
        brightness_avg = np.mean(samples)

        brightness_stats.append({
            'rect': rect,
            'q1': q1,
            'q3': q3,
            'brightness_avg': brightness_avg,
            'samples': samples
        })

    # 2. 过滤亮度低于阈值的矩形
    if not brightness_stats:
        return []

    brightness_avgs = [stat['brightness_avg'] for stat in brightness_stats]
    median_brightness = np.median(brightness_avgs)
    low_brightness_threshold = median_brightness - 50

    bright_rects = [stat for stat in brightness_stats
                    if stat['brightness_avg'] >= low_brightness_threshold]

    # 3. 计算特定区间亮度平均值并二次过滤
    filtered_rectangles = []
    for stat in bright_rects:
        samples = stat['samples']
        sorted_samples = np.sort(samples)  # 排序以提取区间

        # 计算25%-35%区间平均值
        low_idx_start = int(len(samples) * 0.25)
        low_idx_end = int(len(samples) * 0.35)
        low_range = sorted_samples[low_idx_start:low_idx_end]
        low_avg = np.mean(low_range) if len(low_range) > 0 else 0

        # 计算65%-75%区间平均值
        high_idx_start = int(len(samples) * 0.65)
        high_idx_end = int(len(samples) * 0.75)
        high_range = sorted_samples[high_idx_start:high_idx_end]
        high_avg = np.mean(high_range) if len(high_range) > 0 else 0

        # 计算区间差值并过滤
        brightness_diff = high_avg - low_avg
        if brightness_diff <= 50:
            filtered_rectangles.append(stat['rect'])

    return filtered_rectangles

