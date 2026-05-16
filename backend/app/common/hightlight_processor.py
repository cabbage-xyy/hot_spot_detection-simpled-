# 对于高亮区域的处理 包括筛选，确定，以及轮廓的处理

import cv2
import numpy as np

# 在一张彩色图像中(先转换成只有绿色通道)再检测并提取高亮（bright）区域和亮度梯度突变（gradient）区域，然后将两者合并得到最终的检测结果
def detect_bright_regions(image, avg_rect_area):
    gray = 0 * image[:, :, 2] + 1 * image[:, :, 1] + 0 * image[:, :, 0]
    gray = np.uint8(gray)
    filtered = cv2.medianBlur(gray, 9)
    bilateral = cv2.bilateralFilter(filtered, 9, 50, 50)

    _, bright_regions = cv2.threshold(bilateral, 160, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    opened = cv2.morphologyEx(bright_regions, cv2.MORPH_OPEN, kernel, iterations=1)
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 亮度梯度检测
    laplacian = cv2.Laplacian(bilateral, cv2.CV_64F)
    laplacian_abs = np.absolute(laplacian)
    laplacian_8u = np.uint8(laplacian_abs)

    # 阈值处理梯度图像
    _, gradient_regions = cv2.threshold(laplacian_8u, 90, 255, cv2.THRESH_BINARY)
    gradient_opened = cv2.morphologyEx(gradient_regions, cv2.MORPH_OPEN, kernel, iterations=1)
    gradient_closed = cv2.morphologyEx(gradient_opened, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 第一次检测结果
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filtered_contours = [cnt for cnt in contours if avg_rect_area > cv2.contourArea(cnt) > 10]

    # 二次检测逻辑
    final_contours = []
    for cnt in filtered_contours:
        area = cv2.contourArea(cnt)
        if area > ( avg_rect_area / 2 ):
            perimeter = cv2.arcLength(cnt, closed=True)
            if perimeter == 0:
                final_contours.append(cnt)
                continue

            a = perimeter / (2 * np.sqrt(np.pi * area))
            if a < 3:
                # 创建第一次检测轮廓的掩码，限定二次检测范围
                cnt_mask = np.zeros_like(bilateral)
                cv2.drawContours(cnt_mask, [cnt], -1, (255,), thickness=cv2.FILLED)

                # 在第一次轮廓范围内进行二次检测
                _, bright_regions_second = cv2.threshold(bilateral, 210, 255, cv2.THRESH_BINARY)
                bright_regions_second = cv2.bitwise_and(bright_regions_second, bright_regions_second,
                                                         mask=cnt_mask)  # 应用掩码

                kernel = np.ones((5, 5), np.uint8)
                opened_second = cv2.morphologyEx(bright_regions_second, cv2.MORPH_OPEN, kernel, iterations=2)
                closed_second = cv2.morphologyEx(opened_second, cv2.MORPH_CLOSE, kernel, iterations=3)

                contours_second, _ = cv2.findContours(closed_second, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                filtered_contours_second = [cnt_s for cnt_s in contours_second if cv2.contourArea(cnt_s) > 10]

                if len(filtered_contours_second) > 0:
                    # 合并二次检测轮廓
                    final_contours.extend(filtered_contours_second)
                # 若无二次结果，不添加原轮廓
            else:
                final_contours.append(cnt)
        else:
            final_contours.append(cnt)

    # 合并最终检测结果和梯度变化区域
    combined_mask = np.zeros_like(closed)
    cv2.drawContours(combined_mask, final_contours, -1, (255,), thickness=cv2.FILLED)
    merged = cv2.bitwise_or(combined_mask, gradient_closed)

    # 查找合并后的轮廓
    merged_contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return merged_contours

# 在图像处理中检测并提取高亮区域轮廓的功能增强版本。它不仅能完成基础的亮度检测，还会保存处理过程中的中间图像结果，方便分析和调试。
def detect_bright_regions_1(image, avg_rect_area, output_dir="intermediate_results", filename=""):
    # 创建输出目录保存中间结果
    import os
    os.makedirs(output_dir, exist_ok=True)

    # 生成带文件名前缀的保存路径（处理空文件名情况）
    def get_save_path(step_name):
        if filename:
            return os.path.join(output_dir, f"{filename}_{step_name}")
        return os.path.join(output_dir, step_name)

    # 原始绿色通道提取
    gray = image[:, :, 1]
    gray = np.uint8(gray)

    # 图像平滑处理
    filtered = cv2.medianBlur(gray, 9)
    bilateral = cv2.bilateralFilter(filtered, 9, 50, 50)

    # 首次阈值处理
    _, bright_regions = cv2.threshold(bilateral, 120, 255, cv2.THRESH_BINARY)

    kernel = np.ones((5, 5), np.uint8)
    opened = cv2.morphologyEx(bright_regions, cv2.MORPH_OPEN, kernel, iterations=1)
    # cv2.imwrite(get_save_path("05_after_opening.jpg"), opened)  # 保存开运算结果

    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=1)
    # cv2.imwrite(get_save_path("06_after_closing.jpg"), closed)  # 保存闭运算结果

    # 亮度梯度检测
    laplacian = cv2.Laplacian(bilateral, cv2.CV_64F)
    laplacian_abs = np.absolute(laplacian)
    laplacian_8u = np.uint8(laplacian_abs)
    # cv2.imwrite(get_save_path("07_laplacian_gradient.jpg"), laplacian_8u)  # 保存拉普拉斯梯度

    # 梯度阈值处理
    _, gradient_regions = cv2.threshold(laplacian_8u, 90, 255, cv2.THRESH_BINARY)
    # cv2.imwrite(get_save_path("08_gradient_threshold.jpg"), gradient_regions)  # 保存梯度阈值结果

    gradient_opened = cv2.morphologyEx(gradient_regions, cv2.MORPH_OPEN, kernel, iterations=1)
    # cv2.imwrite(get_save_path("09_gradient_opening.jpg"), gradient_opened)  # 保存梯度开运算结果

    gradient_closed = cv2.morphologyEx(gradient_opened, cv2.MORPH_CLOSE, kernel, iterations=2)
    # cv2.imwrite(get_save_path("10_gradient_closing.jpg"), gradient_closed)  # 保存梯度闭运算结果

    # 第一次检测结果
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filtered_contours = [cnt for cnt in contours if avg_rect_area > cv2.contourArea(cnt)]
    big_contours = [cnt for cnt in contours if 20000 > cv2.contourArea(cnt) > 10]

    # 绘制首次筛选后的轮廓
    first_pass = image.copy()
    first_pass_1 = image.copy()
    cv2.drawContours(first_pass, contours, -1, (0, 255, 0), 2)
    cv2.drawContours(first_pass_1, filtered_contours, -1, (0, 255, 0), 2)
    # cv2.imwrite(get_save_path("11_first_pass_contours.jpg"), first_pass)  # 保存首次轮廓
    # cv2.imwrite(get_save_path("11_first_pass_contours_1.jpg"), first_pass_1)

    # 二次检测逻辑
    final_contours = []
    second_pass = image.copy()  # 用于绘制二次检测结果

    for i, cnt in enumerate(big_contours):
        area = cv2.contourArea(cnt)
        if area > (avg_rect_area / 2):
            perimeter = cv2.arcLength(cnt, closed=True)
            if perimeter == 0:
                final_contours.append(cnt)
                continue

            a = perimeter / (2 * np.sqrt(np.pi * area))
            if a < 3:
                # 创建掩码
                cnt_mask = np.zeros_like(bilateral)
                cv2.drawContours(cnt_mask, [cnt], -1, (255,), thickness=cv2.FILLED)
                # cv2.imwrite(get_save_path(f"12_mask_{i}.jpg"), cnt_mask)  # 保存单个掩码

                # 二次阈值检测
                _, bright_regions_second = cv2.threshold(bilateral, 210, 255, cv2.THRESH_BINARY)
                bright_regions_second = cv2.bitwise_and(bright_regions_second, bright_regions_second, mask=cnt_mask)
                # cv2.imwrite(get_save_path(f"13_second_threshold_{i}.jpg"), bright_regions_second)  # 保存二次阈值结果

                # 二次形态学处理
                opened_second = cv2.morphologyEx(bright_regions_second, cv2.MORPH_OPEN, kernel, iterations=2)
                closed_second = cv2.morphologyEx(opened_second, cv2.MORPH_CLOSE, kernel, iterations=3)
                # cv2.imwrite(get_save_path(f"14_second_morphology_{i}.jpg"), closed_second)  # 保存二次形态学结果

                # 提取二次轮廓
                contours_second, _ = cv2.findContours(closed_second, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                filtered_contours_second = [cnt_s for cnt_s in contours_second if cv2.contourArea(cnt_s) > 10]

                # 绘制二次检测轮廓
                if filtered_contours_second:
                    cv2.drawContours(second_pass, filtered_contours_second, -1, (0, 0, 255), 2)
                    final_contours.extend(filtered_contours_second)
            else:
                final_contours.append(cnt)
                cv2.drawContours(second_pass, [cnt], -1, (255, 0, 0), 2)
        else:
            final_contours.append(cnt)
            cv2.drawContours(second_pass, [cnt], -1, (255, 0, 0), 2)

    # cv2.imwrite(get_save_path("15_second_pass_contours.jpg"), second_pass)  # 保存二次检测结果

    # 合并最终结果和梯度区域
    combined_mask = np.zeros_like(closed)
    cv2.drawContours(combined_mask, final_contours, -1, (255,), thickness=cv2.FILLED)
    # cv2.imwrite(get_save_path("16_combined_mask.jpg"), combined_mask)  # 保存合并掩码

    merged = cv2.bitwise_or(combined_mask, gradient_closed)
    # cv2.imwrite(get_save_path("17_merged_mask.jpg"), merged)  # 保存最终掩码

    # 查找合并后的轮廓
    merged_contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 绘制最终结果
    final_result = image.copy()
    cv2.drawContours(final_result, merged_contours, -1, (0, 255, 0), 2)
    # cv2.imwrite(get_save_path("18_final_result.jpg"), final_result)  # 保存最终结果

    return merged_contours


# 根据高亮区域的轮廓位置，结合已知的行列坐标数据，为每个高亮区域分配一个唯一的 “区域编号
def calculate_bright_region_numbers(bright_contours, column_data, row_data, avg_rect_height, avg_rect_weight):
    region_numbers = []

    for contour in bright_contours:
        # 提取轮廓中所有点的x和y坐标
        x_coords = contour[:, :, 0].flatten()
        y_coords = contour[:, :, 1].flatten()

        # 计算中心（使用最大/最小值的平均值）
        cX = int((np.min(x_coords) + np.max(x_coords)) // 2)
        cY = int((np.min(y_coords) + np.max(y_coords)) // 2)

        # 列编号
        if not column_data:
            continue  # 无列数据时跳过
        nearest_col_num = min(column_data.keys(), key=lambda k: abs(cX - column_data[k]))
        col_x = column_data[nearest_col_num]
        distance_diff_x = abs(cX - col_x)

        # 大行编号和方向
        if not row_data:
            continue  # 无行数据时跳过
        nearest_major_row = min(row_data.keys(), key=lambda k: abs(cY - row_data[k]))
        row_y = row_data[nearest_major_row]
        distance_diff_y = abs(cY - row_y)

        # 距离阈值判断
        if distance_diff_y > avg_rect_height * 0.6 or distance_diff_x > avg_rect_weight * 0.6:
            continue  # 超过阈值，跳过这个高亮区域的编号计算

        region_number = (nearest_major_row, nearest_col_num)
        region_numbers.append(region_number)  # 不进行去重，保留所有检测结果

    return region_numbers


# 判断两个矩形框是否重叠
def is_overlapping(box1, box2):
    # 判断两个标注框是否重叠
    x1_1, y1_1, x2_1, y2_1 = box1
    x1_2, y1_2, x2_2, y2_2 = box2
    return not (x2_1 < x1_2 or x2_2 < x1_1 or y2_1 < y1_2 or y2_2 < y1_1)


# 根据亮度对比条件筛选标注框，主要用于在图像处理中判断一个框内的区域是否 “明显比周围区域更亮”。
def filter_boxes_by_brightness(blurred, boxes):
    # 根据亮度条件筛选标注框
    valid_boxes = []
    for box in boxes:
        x1, y1, x2, y2 = box
        region = blurred[y1:y2, x1:x2]
        region_brightness = np.mean(region)
        # 计算上下左右四个方向相邻区域的平均亮度
        top_region = blurred[max(0, y1 - (y2 - y1)):y1, x1:x2]
        bottom_region = blurred[y2:min(blurred.shape[0], y2 + (y2 - y1)), x1:x2]
        left_region = blurred[y1:y2, max(0, x1 - (x2 - x1)):x1]
        right_region = blurred[y1:y2, x2:min(blurred.shape[1], x2 + (x2 - x1))]
        top_brightness = np.mean(top_region) if top_region.size > 0 else 0
        bottom_brightness = np.mean(bottom_region) if bottom_region.size > 0 else 0
        left_brightness = np.mean(left_region) if left_region.size > 0 else 0
        right_brightness = np.mean(right_region) if right_region.size > 0 else 0
        # 统计满足条件的方向数量
        valid_directions = 0
        if region_brightness - top_brightness >= 60:
            valid_directions += 1
        if region_brightness - bottom_brightness >= 60:
            valid_directions += 1
        if region_brightness - left_brightness >= 60:
            valid_directions += 1
        if region_brightness - right_brightness >= 60:
            valid_directions += 1
        if valid_directions >= 2:
            valid_boxes.append(box)
    return valid_boxes


# 在视频帧（或图像）中检测并筛选出符合亮度条件的区域轮廓
def detect_frame(frame):
    # 转换为灰度图像
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 自适应中值滤波
    gray = cv2.medianBlur(gray, 9)

    # 平滑处理，使用双边滤波
    blurred = cv2.bilateralFilter(gray, 5, 50, 50)

    # 标注所有亮度高于170的区域（保持与原代码一致的阈值逻辑）
    high_brightness_mask = np.where(blurred > 180, 255, 0).astype(np.uint8)

    # 查找轮廓
    contours_high, _ = cv2.findContours(
        high_brightness_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 扩展轮廓并过滤小区域
    expanded_contours = []
    expand_pixels = 2  # 可调整的扩展像素值

    for contour in contours_high:
        # 增大轮廓
        contour = np.clip(contour - expand_pixels, 0, [blurred.shape[1], blurred.shape[0]])
        x, y, w, h = cv2.boundingRect(contour)

        # 过滤过小的区域（保持与原代码一致的尺寸判断）
        if w > 2 * 2 and h > 2 * 2:
            expanded_contours.append(contour)

    # 获取所有标注框对应的轮廓
    valid_contours = []
    for contour in expanded_contours:
        x, y, w, h = cv2.boundingRect(contour)
        box = (x, y, x + w, y + h)

        # 排除与亮度大于170的区域的标注框重叠的框
        overlap = False
        for high_contour in expanded_contours:
            high_x, high_y, high_w, high_h = cv2.boundingRect(high_contour)
            high_box = (high_x, high_y, high_x + high_w, high_y + high_h)

            if is_overlapping(box, high_box):
                overlap = True
                break

        if not overlap:
            valid_contours.append(contour)

    # 根据亮度条件筛选轮廓
    valid_contours_filtered = []
    for contour in valid_contours:
        x, y, w, h = cv2.boundingRect(contour)
        box = (x, y, x + w, y + h)

        if box in filter_boxes_by_brightness(blurred, [box]):
            valid_contours_filtered.append(contour)

    # 过滤边缘区域的轮廓（保持与原代码一致的边缘判断）
    width, height = frame.shape[1], frame.shape[0]
    final_contours = []

    for contour in valid_contours_filtered:
        x, y, w, h = cv2.boundingRect(contour)

        # 排除距离边缘过近的轮廓
        if x < 30 or y < 30 or x + w > width - 30 or y + h > height - 30:
            continue

        final_contours.append(contour)

    return final_contours  # 返回筛选后的轮廓列表


# 根据一个中心位置，在给定的矩形列表中找到距离最近的矩形，并返回其对应的编号
def get_nearest_number(center, rects, numbers):
    min_distance = float('inf')
    nearest_num = 0
    for rect, num in zip(rects, numbers):
        rect_center = (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
        distance = abs(center - rect_center[0]) if isinstance(center, int) else abs(center - rect_center[1])
        if distance < min_distance:
            min_distance = distance
            nearest_num = num
    return nearest_num


#  从二值图像中提取并保留大面积的黑色区域，同时过滤掉细小的黑色斑点和狭窄通道 这是方法1
def get_large_black_regions(binary_img):
    try:
        _, binary = cv2.threshold(binary_img, 120, 255, cv2.THRESH_BINARY)
        kernel = np.ones((3, 3), np.uint8)
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        eroded = cv2.erode(closed, kernel, iterations=1)

        inverted = cv2.bitwise_not(eroded)
        distance = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)
        narrow_mask = (distance < 10).astype(np.uint8) * 255

        contours, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outer_black_mask = np.zeros_like(eroded)
        if contours:
            hull = cv2.convexHull(np.vstack(contours))
            cv2.drawContours(outer_black_mask, [hull], -1, (255,), -1)
            outer_black_mask = cv2.bitwise_not(outer_black_mask)

        remove_mask = cv2.bitwise_and(narrow_mask, cv2.bitwise_not(outer_black_mask))
        result = eroded.copy()
        result[remove_mask == 255] = 255

        return result
    except Exception as e:
        print(f"[函数2调试] 处理出错：{str(e)}")
        return None


# 从灰度图像中提取多个大面积的黑色区域轮廓，并过滤掉形状不规则、面积差异过大的区域 这是对方法1的改进版，是独立的方法
def get_multi_large_black_contours(gray_img, min_area_ratio=0.01, min_hole_area_ratio=0.001):
    h, w = gray_img.shape
    img_total_area = h * w
    min_large_area = img_total_area * min_area_ratio  # 大黑区最小面积阈值

    # 1. 预处理：获取二值化图像
    _, binary = cv2.threshold(gray_img, 127, 255, cv2.THRESH_BINARY)
    binary_inv = cv2.bitwise_not(binary)  # 黑区→白(255)，背景→黑(0)

    # 2. 提取所有连通区域
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary_inv, connectivity=8)

    # 3. 筛选出候选区域并计算凸包
    candidate_regions = []
    for i in range(1, num_labels):  # 跳过背景(0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_large_area:
            # 创建当前区域掩码
            region_mask = (np.array(labels == i, dtype=np.bool_)).astype(np.uint8) * 255
            # 提取轮廓并计算凸包
            contours, _ = cv2.findContours(region_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                hull = cv2.convexHull(np.vstack(contours))
                candidate_regions.append((i, hull, area))

    if not candidate_regions:
        return []

    # 4. 确定需要去除的区域（这里以凸包面积与实际面积差异过大为判断依据）
    regions_to_remove = set()
    for i, hull, area in candidate_regions:
        # 计算凸包面积
        hull_area = cv2.contourArea(hull)
        # 当凸包面积远大于实际面积时，判定为需要去除的区域（可调整阈值）
        if hull_area > area * 1.5:
            regions_to_remove.add(i)

    # 5. 在原始二值图中移除这些区域
    filtered_mask = binary_inv.copy()
    for region_id in regions_to_remove:
        filtered_mask[labels == region_id] = 0  # 将需要去除的区域设为背景

    # 6. 对处理后的图像提取外轮廓
    contours, _ = cv2.findContours(filtered_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 过滤面积过小的轮廓
    filtered_contours = []
    for cnt in contours:
        if cv2.contourArea(cnt) >= min_large_area * 0.5:
            filtered_contours.append(cnt)

    return filtered_contours