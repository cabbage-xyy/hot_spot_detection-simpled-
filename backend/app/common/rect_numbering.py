# 对矩形进行编号

import re
from collections import defaultdict


# 计算矩形的中心纵坐标 y坐标轴
def get_rect_center_y(rect):
    x, y, w, h = rect
    return y + h / 2

# 计算矩形的中心横坐标 x坐标轴
def get_rect_center_x(rect):
    x, y, w, h = rect
    return x + w / 2

# 是一个自下而上的矩形行编号算法，主要用于在视频帧或图像中对矩形对象进行垂直方向的行划分和编号。它可以处理第一帧的初始化，也能在后续帧中根据历史信息进行行匹配、更新和扩展
def get_vertical_numbering_bottomup(all_rects, prev_known_rows=None, prev_max_known_row=None,
                                    prev_gap_types=None, prev_contact_avg_v=None,
                                    prev_aisle_avg_v=None, prev_large_avg_v=None,
                                    prev_dynamic_avg_v=None):
    # 第一帧处理（逻辑不变，确保初始匹配行坐标正确）
    if prev_known_rows is None:
        known_rows = {}  # {行编号: 中心y坐标}
        gap_types = {}  # { (行1, 行2): 间隔类型 }（行1在下，行2在上）
        contact_avg_v = 0
        aisle_avg_v = 0
        large_avg_v = 0
        max_known_row = 0
        dynamic_avg_v = {}

        sorted_rects = sorted(all_rects, key=lambda r: get_rect_center_y(r), reverse=True)
        if not sorted_rects:
            return {}, {}, 0, {}, 0, 0, 0, {}

        # 初始行划分（从下往上编号1,2,3...）
        vertical_numbers = {}
        row_num = 1
        vertical_numbers[sorted_rects[0]] = row_num
        current_y = get_rect_center_y(sorted_rects[0])
        current_h = sorted_rects[0][3]

        for rect in sorted_rects[1:]:
            center_y = get_rect_center_y(rect)
            rect_h = rect[3]
            avg_height = (current_h + rect_h) / 2
            if abs(center_y - current_y) < avg_height * 0.3:
                vertical_numbers[rect] = row_num
            else:
                row_num += 1
                vertical_numbers[rect] = row_num
                current_y = center_y
                current_h = rect_h

        # 计算已知行坐标（平均值）
        row_centers = defaultdict(list)
        for rect, num in vertical_numbers.items():
            row_centers[num].append(get_rect_center_y(rect))
        known_rows = {num: sum(ys) / len(ys) for num, ys in row_centers.items()}
        max_known_row = max(known_rows.keys()) if known_rows else 0

        # 计算相邻行间隔及分类（修改为阶梯式判断）
        sorted_rows = sorted(known_rows.keys())
        gaps = []
        for i in range(len(sorted_rows) - 1):
            row1, row2 = sorted_rows[i], sorted_rows[i + 1]
            gap = known_rows[row1] - known_rows[row2]
            gaps.append((row1, row2, gap))

        avg_rect_height = sum(rect[3] for rect in all_rects) / len(all_rects) if all_rects else 0
        contact_gaps = [g for _, _, g in gaps if avg_rect_height < g < avg_rect_height * 1.2]
        remaining_gaps = [g for _, _, g in gaps if g >= avg_rect_height * 1.2]
        contact_avg_v = sum(contact_gaps) / len(contact_gaps) if contact_gaps else 0

        # 聚类剩余间隔（动态扩展聚类）
        gap_clusters = []
        for gap in remaining_gaps:
            matched = False
            # 按现有聚类依次匹配（偏差≤20%则加入）
            for i, cluster in enumerate(gap_clusters):
                cluster_avg = sum(cluster) / len(cluster)
                if abs(gap - cluster_avg) <= cluster_avg * 0.2:
                    cluster.append(gap)
                    matched = True
                    break
            # 所有现有聚类偏差>20%则新建聚类
            if not matched:
                gap_clusters.append([gap])
        cluster_avgs = sorted([sum(c) / len(c) for c in gap_clusters]) if gap_clusters else []
        aisle_avg_v = cluster_avgs[0] if len(cluster_avgs) >= 1 else 0
        large_avg_v = cluster_avgs[1] if len(cluster_avgs) >= 2 else 0

        # 标记间隔类型（阶梯式动态分类）
        gap_type_names = ['contact_v', 'aisle_v', 'large_v']  # 基础类型
        for row1, row2, gap in gaps:
            if gap < avg_rect_height * 1.2:
                gap_types[(row1, row2)] = 'contact_v'
            else:
                # 阶梯式判断：依次检查每个聚类（偏差>20%则进入下一级）
                assigned = False
                for i in range(len(cluster_avgs)):
                    cluster_avg = cluster_avgs[i]
                    if abs(gap - cluster_avg) <= cluster_avg * 0.2:
                        if i < len(gap_type_names) - 1:
                            gap_types[(row1, row2)] = gap_type_names[i + 1]
                        else:
                            # 超过基础类型则动态命名（间隔四、间隔五...）
                            gap_types[(row1, row2)] = f'gap_{i + 2}_v'
                        assigned = True
                        break
                # 所有聚类偏差>20%则新建类型
                if not assigned and len(cluster_avgs) > 0:
                    new_type = f'gap_{len(cluster_avgs) + 1}_v'
                    gap_types[(row1, row2)] = new_type

        # 计算第一帧动态类型的平均值
        dynamic_gap_types = [gt for gt in set(gap_types.values())
                             if gt.startswith('gap_') and gt not in gap_type_names]
        for gap_type in dynamic_gap_types:
            current_dynamic = [g for r1, r2, g in gaps if gap_types.get((r1, r2)) == gap_type]
            if current_dynamic:
                dynamic_avg_v[gap_type] = abs(sum(current_dynamic) / len(current_dynamic))
            else:
                dynamic_avg_v[gap_type] = 0

        # 修改返回值：新增dynamic_avg_v
        return vertical_numbers, known_rows, max_known_row, gap_types, contact_avg_v, aisle_avg_v, large_avg_v, dynamic_avg_v

    # 后续帧处理（核心修改）
    else:
        dynamic_avg_v = prev_dynamic_avg_v.copy() if prev_dynamic_avg_v else {}  # 沿用历史值
        known_rows = prev_known_rows.copy()
        prev_gap_types = prev_gap_types or {}
        gap_types = prev_gap_types.copy()
        max_known_row = prev_max_known_row if prev_max_known_row is not None else 0

        contact_avg_v = prev_contact_avg_v if prev_contact_avg_v is not None else 0
        aisle_avg_v = prev_aisle_avg_v if prev_aisle_avg_v is not None else 0
        large_avg_v = prev_large_avg_v if prev_large_avg_v is not None else 0

        # 计算矩形中心和平均高度
        rect_centers = {rect: get_rect_center_y(rect) for rect in all_rects}
        avg_rect_height = sum(rect[3] for rect in all_rects) / len(all_rects) if all_rects else 0
        match_threshold = avg_rect_height * 0.45
        secondary_threshold = avg_rect_height * 0.45

        # 第一步：第一轮匹配，记录匹配行并计算坐标（仅用矩形中心平均值）
        matched_rects = set()
        row_matches = defaultdict(list)  # {行编号: [匹配的矩形中心y]}
        for rect in all_rects:
            center_y = rect_centers[rect]
            best_row = None
            min_diff = float('inf')
            for row_num in sorted(known_rows.keys()):
                row_y = known_rows[row_num]
                diff = abs(center_y - row_y)
                if diff < match_threshold and diff < min_diff:
                    min_diff = diff
                    best_row = row_num
            if best_row is not None:
                row_matches[best_row].append(center_y)
                matched_rects.add(rect)

        # 更新匹配行坐标（仅用矩形中心平均值，此为最终坐标，不再修改）
        matched_rows = set(row_matches.keys())  # 标记匹配行
        for row_num, ys in row_matches.items():
            known_rows[row_num] = sum(ys) / len(ys)  # 匹配行坐标锁定

        # 计算当前帧间隔（用于更新平均值，但不影响匹配行坐标）
        sorted_current_rows = sorted(known_rows.keys())
        current_gaps = []
        for i in range(len(sorted_current_rows) - 1):
            row1, row2 = sorted_current_rows[i], sorted_current_rows[i + 1]
            gap = known_rows[row1] - known_rows[row2]
            current_gaps.append((row1, row2, gap))

        # 区分历史间隔和新间隔，更新间隔类型（修改为阶梯式聚类）
        new_gaps = [(r1, r2, g) for r1, r2, g in current_gaps if (r1, r2) not in prev_gap_types]
        if new_gaps:
            all_current_gap_values = [g for _, _, g in current_gaps]
            contact_candidates = [g for g in all_current_gap_values if avg_rect_height < g < avg_rect_height * 1.2]
            remaining_candidates = [g for g in all_current_gap_values if g >= avg_rect_height * 1.2]

            # 动态扩展聚类：偏差>20%则新建聚类
            gap_clusters = []
            for gap in remaining_candidates:
                matched = False
                for i, cluster in enumerate(gap_clusters):
                    cluster_avg = sum(cluster) / len(cluster)
                    if abs(gap - cluster_avg) <= cluster_avg * 0.2:
                        cluster.append(gap)
                        matched = True
                        break
                if not matched:
                    gap_clusters.append([gap])
            cluster_avgs = sorted([sum(c) / len(c) for c in gap_clusters]) if gap_clusters else []

            # 阶梯式标记间隔类型
            gap_type_names = ['contact_v', 'aisle_v', 'large_v']
            for r1, r2, g in new_gaps:
                if g < avg_rect_height * 1.2:
                    gap_types[(r1, r2)] = 'contact_v'
                else:
                    assigned = False
                    for i in range(len(cluster_avgs)):
                        cluster_avg = cluster_avgs[i]
                        if abs(g - cluster_avg) <= cluster_avg * 0.2:
                            if i < len(gap_type_names) - 1:
                                gap_types[(r1, r2)] = gap_type_names[i + 1]
                            else:
                                gap_types[(r1, r2)] = f'gap_{i + 2}_v'
                            assigned = True
                            break
                    if not assigned and len(cluster_avgs) > 0:
                        new_type = f'gap_{len(cluster_avgs) + 1}_v'
                        gap_types[(r1, r2)] = new_type

        # 按类型更新平均值（逻辑不变）
        current_contact = [g for r1, r2, g in current_gaps if gap_types.get((r1, r2)) == 'contact_v']
        current_aisle = [g for r1, r2, g in current_gaps if gap_types.get((r1, r2)) == 'aisle_v']
        current_large = [g for r1, r2, g in current_gaps if gap_types.get((r1, r2)) == 'large_v']

        contact_avg_v = avg_rect_height if current_contact else contact_avg_v
        aisle_avg_v = abs(sum(current_aisle) / len(current_aisle)) if current_aisle else aisle_avg_v
        large_avg_v = abs(sum(current_large) / len(current_large)) if current_large else large_avg_v

        # 强制保证aisle_avg_v ≥ contact_avg_v × 1.15，否则重置为contact_avg_v × 1.3
        if contact_avg_v > 0:  # 避免接触间隔为0时的无效计算
            min_aisle_threshold = contact_avg_v * 1.15  # 最低阈值：接触间隔的1.15倍
            reset_aisle_value = contact_avg_v * 1.3  # 重置值：接触间隔的1.3倍
            if aisle_avg_v < min_aisle_threshold:
                aisle_avg_v = reset_aisle_value
        # 动态间隔类型平均值更新
        # 1. 收集所有动态间隔类型（gap_4_v/gap_5_v...）
        dynamic_gap_types = [gt for gt in set(gap_types.values())
                             if gt.startswith('gap_') and gt not in ['contact_v', 'aisle_v', 'large_v']]

        # 2. 初始化动态类型平均值字典（沿用历史值）
        dynamic_avg_v = prev_dynamic_avg_v.copy() if prev_dynamic_avg_v else {}
        for gt in dynamic_gap_types:
            # 仅当历史值不存在时初始化为0，否则保留历史值
            if gt not in dynamic_avg_v:
                dynamic_avg_v[gt] = 0  # 首次出现时初始化，后续沿用历史值

        # 3. 更新动态类型平均值（与基础类型逻辑一致）
        for gap_type in dynamic_gap_types:
            current_dynamic = [g for r1, r2, g in current_gaps if gap_types.get((r1, r2)) == gap_type]
            # 仅当有有效实测样本（current_dynamic非空）时，才更新间隔值；无则保留历史值
            if current_dynamic and len(current_dynamic) > 0:
                # 校验：确保样本不是仅由未匹配行推导的无效值（可选，增强鲁棒性）
                # 过滤极小值，避免推导误差覆盖历史超大间隔
                valid_dynamic = [g for g in current_dynamic if g > contact_avg_v * 2]  # 仅保留超大间隔样本
                if valid_dynamic:
                    dynamic_avg_v[gap_type] = abs(sum(valid_dynamic) / len(valid_dynamic))
            # 无新值时沿用历史值（无需修改）

        # 第二步：计算未匹配行坐标（仅处理未匹配行，跳过匹配行）
        if matched_rows:
            max_matched_row = max(matched_rows)
            max_known_row = max(max_known_row, max_matched_row)

            # 向上计算未匹配行（仅处理未匹配的行）
            all_row_nums = sorted(known_rows.keys())
            rows_above = [num for num in all_row_nums if num > max_matched_row and num not in matched_rows]
            for row_num in rows_above:
                lower_row = row_num - 1
                if lower_row in known_rows:
                    gap_type = gap_types.get((lower_row, row_num), 'contact_v')
                    if gap_type == 'contact_v':
                        known_rows[row_num] = known_rows[lower_row] - contact_avg_v
                    elif gap_type == 'aisle_v':
                        known_rows[row_num] = known_rows[lower_row] - aisle_avg_v
                    elif gap_type == 'large_v':
                        known_rows[row_num] = known_rows[lower_row] - large_avg_v
                    # 动态类型适配（核心：此时dynamic_avg_v已保留历史超大值）
                    elif gap_type in dynamic_avg_v:
                        known_rows[row_num] = known_rows[lower_row] - dynamic_avg_v[gap_type]
                    else:
                        known_rows[row_num] = known_rows[lower_row] - (
                            large_avg_v if large_avg_v > 0 else contact_avg_v)

            # 向下计算未匹配行（仅处理未匹配的行）
            rows_below = [num for num in reversed(all_row_nums) if num < max_matched_row and num not in matched_rows]
            for row_num in rows_below:
                upper_row = row_num + 1
                if upper_row in known_rows:
                    gap_type = gap_types.get((row_num, upper_row), 'contact_v')
                    if gap_type == 'contact_v':
                        known_rows[row_num] = known_rows[upper_row] + contact_avg_v
                    elif gap_type == 'aisle_v':
                        known_rows[row_num] = known_rows[upper_row] + aisle_avg_v
                    elif gap_type == 'large_v':
                        known_rows[row_num] = known_rows[upper_row] + large_avg_v
                    # 动态类型适配（核心：使用保留的历史超大间隔值）
                    elif gap_type in dynamic_avg_v:
                        known_rows[row_num] = known_rows[upper_row] + dynamic_avg_v[gap_type]
                    else:
                        known_rows[row_num] = known_rows[upper_row] + (
                            large_avg_v if large_avg_v > 0 else contact_avg_v)

        # 第三步：计算扩展行（逻辑不变）
        extended_row_num = max_known_row + 1 if known_rows else 1
        extended_rows = {}
        # 定义扩展行优先级顺序：接触间隔→过道间隔→大间隔→动态间隔（按名称排序）
        ext_priority_order = []

        # 1. 基础间隔类型（按优先级加入）
        if contact_avg_v > 0:
            ext_priority_order.append(('contact', contact_avg_v, 'contact_v'))
        if aisle_avg_v > 0:
            ext_priority_order.append(('aisle', aisle_avg_v, 'aisle_v'))
        if large_avg_v > 0:
            ext_priority_order.append(('large', large_avg_v, 'large_v'))

        # 2. 动态间隔类型（按名称排序：gap_4_v→gap_5_v→...，确保顺序一致）
        dynamic_ext = []
        for gap_type in sorted(dynamic_avg_v.keys()):
            if dynamic_avg_v[gap_type] > 0:
                # 提取动态间隔编号（如gap_4_v→4），用于排序和后缀
                gap_num = re.search(r'gap_(\d+)_v', gap_type)
                if gap_num:
                    dynamic_ext.append((gap_type, dynamic_avg_v[gap_type], gap_type, int(gap_num.group(1))))
        # 按动态间隔编号升序排序（gap_4_v在前，gap_5_v在后...）
        dynamic_ext.sort(key=lambda x: x[3])
        # 加入优先级顺序（移除编号字段，保留原格式）
        ext_priority_order.extend([(item[0], item[1], item[2]) for item in dynamic_ext])

        # 按优先级顺序生成扩展行（每个间隔类型对应一个扩展行）
        suffix_offset = 0.15  # 基础后缀偏移量（依次递增0.1）
        for name, avg_val, gap_type in ext_priority_order:
            if known_rows and max_known_row in known_rows:
                max_known_y = known_rows[max_known_row]
                # 生成唯一编号（避免冲突，按顺序递增后缀）
                unique_num = float(f"{extended_row_num + suffix_offset}")
                extended_rows[name] = {
                    'num': unique_num,
                    'y': max_known_y - avg_val,
                    'type': gap_type
                }
                suffix_offset += 0.1  # 每个扩展行后缀+0.1（如1.15→1.25→1.35→1.45...）

        # 第四步：二次匹配（仅更新未匹配行，匹配行坐标不变）
        all_matching_rows = known_rows.copy()
        for ext in extended_rows.values():
            all_matching_rows[ext['num']] = ext['y']

        secondary_matches = defaultdict(list)
        for rect in all_rects:
            center_y = rect_centers[rect]
            best_row = None
            min_diff = float('inf')
            for row_num in sorted(all_matching_rows.keys()):
                row_y = all_matching_rows[row_num]
                diff = abs(center_y - row_y)
                if diff < secondary_threshold and diff < min_diff:
                    min_diff = diff
                    best_row = row_num
            if best_row is not None:
                secondary_matches[best_row].append(center_y)

        # 二次匹配仅更新未匹配行（跳过匹配行）
        for row_num, ys in secondary_matches.items():
            if row_num in known_rows and row_num not in matched_rows:
                known_rows[row_num] = sum(ys) / len(ys)

        # 处理扩展行（逻辑不变）
        extended_matched = {k: v for k, v in secondary_matches.items() if
                            isinstance(k, float) and k >= extended_row_num}
        if extended_matched:
            type_scores = defaultdict(lambda: {'count': 0})
            for row_num, matches in extended_matched.items():
                # 计算小数部分（如8.15→0.15→1.5→取整为1，对应优先级顺序）
                decimal_part = (row_num - int(row_num)) * 100
                suffix_int = int(decimal_part // 10)  # 1.15→11.5→1（对应第一个扩展行）
                suffix_str = str(suffix_int)

                # 匹配优先级顺序（通过后缀偏移量反向映射到间隔类型）
                if 0 <= suffix_int - 1 < len(ext_priority_order):
                    type_key = ext_priority_order[suffix_int - 1][0]
                else:
                    print(f"[调试] 无效的suffix_str: {suffix_str}，row_num: {row_num}")
                    continue

                unique_centers = set()
                for center_y in matches:
                    rounded_center = round(center_y, 2)
                    unique_centers.add(rounded_center)
                unique_count = len(unique_centers)

                # 基于去重后的数量更新匹配质量（≥2才有效）
                if unique_count >= 2:
                    if unique_count > type_scores[type_key]['count']:
                        type_scores[type_key] = {'count': unique_count}

            # 选择最优类型（仅按匹配数量）
            if type_scores:
                best_type = max(type_scores, key=lambda t: type_scores[t]['count'])
                # 从优先级顺序中找到对应的扩展行信息
                best_ext_info = next(
                    (ext for name, avg_val, gap_type, *rest in ext_priority_order if name == best_type), None)
                if best_ext_info and best_type in extended_rows:
                    best_ext_info = extended_rows[best_type]
                    best_count = type_scores[best_type]['count']
                    if best_count >= 2:
                        known_rows[extended_row_num] = best_ext_info['y']  # 加入已知行
                        gap_types[(max_known_row, extended_row_num)] = best_ext_info['type']
                        max_known_row = max(max_known_row, extended_row_num)

        # 检测现有扩展行上方是否有符合要求的矩形集群，生成新行和新间隔类型
        if known_rows and extended_rows:
            # 1. 获取所有扩展行的y坐标，找到最小y（最上方的扩展行）
            ext_ys = [ext['y'] for ext in extended_rows.values()]
            min_ext_y = min(ext_ys) if ext_ys else float('inf')

            # 2. 筛选出「在最小扩展行上方」且「未匹配到任何已知行/扩展行」的矩形
            # （未匹配矩形 = 所有矩形 - 第一轮匹配矩形 - 二次匹配矩形）
            secondary_matched_rects = set()
            for row_num, matches in secondary_matches.items():
                # 二次匹配的矩形是所有贡献到secondary_matches的矩形（通过center_y反向查找）
                for center_y in matches:
                    # 找到center_y对应的矩形（假设rect_centers是{rect: center_y}，反向映射）
                    for rect, cy in rect_centers.items():
                        if abs(cy - center_y) < 1e-3:  # 浮点数精度容忍
                            secondary_matched_rects.add(rect)
            unmatched_rects = set(all_rects) - matched_rects - secondary_matched_rects

            # 3. 筛选出「在最小扩展行上方」的未匹配矩形（y < min_ext_y，因自下而上y递减）
            upper_unmatched_rects = [
                rect for rect in unmatched_rects
                if rect_centers[rect] < min_ext_y - 1e-3  # 确保在扩展行上方
            ]

            # 4. 聚类上方未匹配矩形，判断是否有≥2个矩形形成同一行
            if len(upper_unmatched_rects) >= 2:
                # 按中心y坐标排序，聚类（同原代码初始行划分逻辑：偏差<平均高度30%）
                upper_centers = [rect_centers[rect] for rect in upper_unmatched_rects]
                upper_centers.sort(reverse=True)  # 从下往上排序（与行编号逻辑一致）
                current_center = upper_centers[0]
                cluster = [current_center]

                for center in upper_centers[1:]:
                    # 计算当前矩形与聚类中心的平均高度（简化为用当前矩形高度）
                    # 实际可优化为：找到center对应的rect，取其高度
                    rect = next(r for r in upper_unmatched_rects if abs(rect_centers[r] - center) < 1e-3)
                    rect_h = rect[3]
                    avg_h = (rect_h + rect[3]) / 2  # 简化：用当前矩形高度自身平均
                    if abs(center - current_center) < avg_h * 0.3:
                        cluster.append(center)
                        current_center = sum(cluster) / len(cluster)  # 更新聚类中心

                # 5. 若聚类数量≥2，生成新行和新间隔类型
                if len(cluster) >= 2:
                    new_row_num = max_known_row + 1
                    new_row_y = sum(cluster) / len(cluster)  # 新行中心y坐标（聚类平均值）
                    new_gap = known_rows[max_known_row] - new_row_y  # 最大已知行与新行的间隔（下-上）

                    # 6. 生成新间隔类型名称（gap_X_v，X为现有动态间隔最大编号+1）
                    # 提取现有动态间隔编号（如gap_4_v→4）
                    existing_dynamic_nums = []
                    for gap_type in dynamic_avg_v.keys():
                        match = re.search(r'gap_(\d+)_v', gap_type)
                        if match:
                            existing_dynamic_nums.append(int(match.group(1)))
                    # 新间隔编号 = 现有最大编号+1，若没有则从4开始（接在large_v之后）
                    new_gap_num = max(existing_dynamic_nums) + 1 if existing_dynamic_nums else 4
                    new_gap_type = f'gap_{new_gap_num}_v'

                    # 7. 更新全局状态
                    known_rows[new_row_num] = new_row_y  # 新增行加入已知行
                    gap_types[(max_known_row, new_row_num)] = new_gap_type  # 标记间隔类型
                    dynamic_avg_v[new_gap_type] = new_gap  # 新增动态间隔平均值
                    max_known_row = new_row_num  # 更新最大已知行编号

        # 生成映射（逻辑不变）
        vertical_numbers = {}
        for rect in all_rects:
            center_y = rect_centers[rect]
            best_row = min(known_rows.keys(), key=lambda r: abs(center_y - known_rows[r]))
            vertical_numbers[rect] = best_row

        return vertical_numbers, known_rows, max_known_row, gap_types, contact_avg_v, aisle_avg_v, large_avg_v, dynamic_avg_v


# 是一个从右到左的矩形列编号算法，主要用于在视频帧或图像中对矩形对象进行水平方向的列划分和编号。它可以处理第一帧的初始化，也能在后续帧中根据历史信息进行列匹配、更新和扩展。
def get_horizontal_numbering_righttoleft(all_rects, prev_known_cols=None, prev_max_known_col=None,
                                        prev_gap_types=None, prev_contact_avg_h=None,
                                        prev_aisle_avg_h=None, prev_large_avg_h=None,
                                        prev_dynamic_avg_h=None):
    # 第一帧处理（初始化列编号）
    if prev_known_cols is None:
        known_cols = {}  # {列编号: 中心x坐标}
        gap_types = {}  # {(列1, 列2): 间隔类型}（列1在右，列2在左）
        contact_avg_h = 0
        aisle_avg_h = 0
        large_avg_h = 0
        max_known_col = 0
        dynamic_avg_h = {}  # 新增：动态间隔类型平均值

        # 按水平中心x坐标从右到左排序（右→左：x值递减）
        sorted_rects = sorted(all_rects, key=lambda r: get_rect_center_x(r), reverse=True)
        if not sorted_rects:
            return {}, {}, 0, {}, 0, 0, 0, {}  # 新增返回dynamic_avg_h

        # 初始列划分（从右往左编号1,2,3...）
        horizontal_numbers = {}
        col_num = 1
        horizontal_numbers[sorted_rects[0]] = col_num
        current_x = get_rect_center_x(sorted_rects[0])  # 初始中心x（最右侧）
        current_w = sorted_rects[0][2]  # 初始宽度

        for rect in sorted_rects[1:]:
            center_x = get_rect_center_x(rect)
            rect_w = rect[2]
            avg_width = (current_w + rect_w) / 2  # 平均宽度作为阈值参考
            # 若当前矩形中心与上一列中心距离小于平均宽度的30%，视为同一列
            if abs(center_x - current_x) < avg_width * 0.3:
                horizontal_numbers[rect] = col_num
            else:
                col_num += 1  # 从右往左递增（右侧为1，左侧为2,3...）
                horizontal_numbers[rect] = col_num
                current_x = center_x
                current_w = rect_w

        # 计算已知列坐标（列中心x的平均值）
        col_centers = defaultdict(list)
        for rect, num in horizontal_numbers.items():
            col_centers[num].append(get_rect_center_x(rect))
        known_cols = {num: sum(xs) / len(xs) for num, xs in col_centers.items()}
        max_known_col = max(known_cols.keys()) if known_cols else 0

        # 计算相邻列间隔及分类（间隔=右列中心x - 左列中心x，因从右到左编号）
        sorted_cols = sorted(known_cols.keys())  # 列编号1,2,3...（右→左）
        gaps = []
        for i in range(len(sorted_cols) - 1):
            col1, col2 = sorted_cols[i], sorted_cols[i + 1]  # col1在右，col2在左
            gap = known_cols[col1] - known_cols[col2]  # 右列x - 左列x（间隔为正）
            gaps.append((col1, col2, gap))

        avg_rect_width = sum(rect[2] for rect in all_rects) / len(all_rects) if all_rects else 0
        contact_gaps = [g for _, _, g in gaps if avg_rect_width < g < avg_rect_width * 1.2]
        remaining_gaps = [g for _, _, g in gaps if g >= avg_rect_width * 1.2]
        contact_avg_h = sum(contact_gaps) / len(contact_gaps) if contact_gaps else 0

        # 聚类剩余间隔（动态扩展聚类）
        gap_clusters = []
        for gap in remaining_gaps:
            matched = False
            # 按现有聚类依次匹配（偏差≤20%则加入）
            for i, cluster in enumerate(gap_clusters):
                cluster_avg = sum(cluster) / len(cluster)
                if abs(gap - cluster_avg) <= cluster_avg * 0.2:
                    cluster.append(gap)
                    matched = True
                    break
            # 所有现有聚类偏差>20%则新建聚类
            if not matched:
                gap_clusters.append([gap])
        cluster_avgs = sorted([sum(c) / len(c) for c in gap_clusters]) if gap_clusters else []
        aisle_avg_h = cluster_avgs[0] if len(cluster_avgs) >= 1 else 0
        large_avg_h = cluster_avgs[1] if len(cluster_avgs) >= 2 else 0

        # 标记间隔类型（阶梯式动态分类）
        gap_type_names = ['contact_h', 'aisle_h', 'large_h']  # 基础类型
        for col1, col2, gap in gaps:
            if gap < avg_rect_width * 1.2:
                gap_types[(col1, col2)] = 'contact_h'
            else:
                # 阶梯式判断：依次检查每个聚类（偏差>20%则进入下一级）
                assigned = False
                for i in range(len(cluster_avgs)):
                    cluster_avg = cluster_avgs[i]
                    if abs(gap - cluster_avg) <= cluster_avg * 0.2:
                        if i < len(gap_type_names) - 1:
                            gap_types[(col1, col2)] = gap_type_names[i + 1]
                        else:
                            # 超过基础类型则动态命名（间隔四、间隔五...）
                            gap_types[(col1, col2)] = f'gap_{i + 2}_h'
                        assigned = True
                        break
                # 所有聚类偏差>20%则新建类型
                if not assigned and len(cluster_avgs) > 0:
                    new_type = f'gap_{len(cluster_avgs) + 1}_h'
                    gap_types[(col1, col2)] = new_type

        # 新增：计算第一帧动态类型的平均值
        dynamic_gap_types = [gt for gt in set(gap_types.values())
                             if gt.startswith('gap_') and gt not in gap_type_names]
        for gap_type in dynamic_gap_types:
            current_dynamic = [g for c1, c2, g in gaps if gap_types.get((c1, c2)) == gap_type]
            if current_dynamic:
                dynamic_avg_h[gap_type] = abs(sum(current_dynamic) / len(current_dynamic))
            else:
                dynamic_avg_h[gap_type] = 0

        # 新增返回dynamic_avg_h
        return horizontal_numbers, known_cols, max_known_col, gap_types, contact_avg_h, aisle_avg_h, large_avg_h, dynamic_avg_h

    # 后续帧处理（核心逻辑与垂直方向一致，仅方向调整）
    else:
        dynamic_avg_h = prev_dynamic_avg_h.copy() if prev_dynamic_avg_h else {}  # 沿用历史值
        known_cols = prev_known_cols.copy()
        prev_gap_types = prev_gap_types or {}
        gap_types = prev_gap_types.copy()
        max_known_col = prev_max_known_col if prev_max_known_col is not None else 0

        contact_avg_h = prev_contact_avg_h if prev_contact_avg_h is not None else 0
        aisle_avg_h = prev_aisle_avg_h if prev_aisle_avg_h is not None else 0
        large_avg_h = prev_large_avg_h if prev_large_avg_h is not None else 0

        # 计算矩形中心x和平均宽度
        rect_centers = {rect: get_rect_center_x(rect) for rect in all_rects}
        avg_rect_width = sum(rect[2] for rect in all_rects) / len(all_rects) if all_rects else 0
        match_threshold = avg_rect_width * 0.45
        secondary_threshold = avg_rect_width * 0.45

        # 第一步：第一轮匹配，记录匹配列并计算坐标
        matched_rects = set()
        col_matches = defaultdict(list)  # {列编号: [匹配的矩形中心x]}
        for rect in all_rects:
            center_x = rect_centers[rect]
            best_col = None
            min_diff = float('inf')
            for col_num in sorted(known_cols.keys()):
                col_x = known_cols[col_num]
                diff = abs(center_x - col_x)
                if diff < match_threshold and diff < min_diff:
                    min_diff = diff
                    best_col = col_num
            if best_col is not None:
                col_matches[best_col].append(center_x)
                matched_rects.add(rect)

        # 更新匹配列坐标（中心x平均值，锁定不变）
        matched_cols = set(col_matches.keys())
        for col_num, xs in col_matches.items():
            known_cols[col_num] = sum(xs) / len(xs)

        # 计算当前帧列间隔（用于更新平均值）
        sorted_current_cols = sorted(known_cols.keys())  # 列编号1,2,3...（右→左）
        current_gaps = []
        for i in range(len(sorted_current_cols) - 1):
            col1, col2 = sorted_current_cols[i], sorted_current_cols[i + 1]  # 右→左
            gap = known_cols[col1] - known_cols[col2]  # 右列x - 左列x
            current_gaps.append((col1, col2, gap))

        # 区分新间隔并更新类型（修改为阶梯式聚类）
        new_gaps = [(c1, c2, g) for c1, c2, g in current_gaps if (c1, c2) not in prev_gap_types]
        if new_gaps:
            all_current_gap_values = [g for _, _, g in current_gaps]
            contact_candidates = [g for g in all_current_gap_values if avg_rect_width < g < avg_rect_width * 1.2]
            remaining_candidates = [g for g in all_current_gap_values if g >= avg_rect_width * 1.2]

            # 动态扩展聚类：偏差>20%则新建聚类
            gap_clusters = []
            for gap in remaining_candidates:
                matched = False
                for i, cluster in enumerate(gap_clusters):
                    cluster_avg = sum(cluster) / len(cluster)
                    if abs(gap - cluster_avg) <= cluster_avg * 0.2:
                        cluster.append(gap)
                        matched = True
                        break
                if not matched:
                    gap_clusters.append([gap])
            cluster_avgs = sorted([sum(c) / len(c) for c in gap_clusters]) if gap_clusters else []

            # 阶梯式标记间隔类型
            gap_type_names = ['contact_h', 'aisle_h', 'large_h']
            for c1, c2, g in new_gaps:
                if g < avg_rect_width * 1.2:
                    gap_types[(c1, c2)] = 'contact_h'
                else:
                    assigned = False
                    for i in range(len(cluster_avgs)):
                        cluster_avg = cluster_avgs[i]
                        if abs(g - cluster_avg) <= cluster_avg * 0.2:
                            if i < len(gap_type_names) - 1:
                                gap_types[(c1, c2)] = gap_type_names[i + 1]
                            else:
                                gap_types[(c1, c2)] = f'gap_{i + 2}_h'
                            assigned = True
                            break
                    if not assigned and len(cluster_avgs) > 0:
                        new_type = f'gap_{len(cluster_avgs) + 1}_h'
                        gap_types[(c1, c2)] = new_type

        # 按类型更新水平间隔平均值
        current_contact = [g for c1, c2, g in current_gaps if gap_types.get((c1, c2)) == 'contact_h']
        current_aisle = [g for c1, c2, g in current_gaps if gap_types.get((c1, c2)) == 'aisle_h']
        current_large = [g for c1, c2, g in current_gaps if gap_types.get((c1, c2)) == 'large_h']

        contact_avg_h = avg_rect_width if current_contact else contact_avg_h
        aisle_avg_h = abs(sum(current_aisle) / len(current_aisle)) if current_aisle else aisle_avg_h
        large_avg_h = abs(sum(current_large) / len(current_large)) if current_large else large_avg_h
        # 强制保证aisle_avg_h ≥ contact_avg_h × 1.15，否则重置为contact_avg_h × 1.3
        if contact_avg_h > 0:  # 避免接触间隔为0时的无效计算
            min_aisle_threshold = contact_avg_h * 1.15  # 最低阈值：接触间隔的1.15倍
            reset_aisle_value = contact_avg_h * 1.3  # 重置值：接触间隔的1.3倍
            if aisle_avg_h < min_aisle_threshold:
                aisle_avg_h = reset_aisle_value

        # 动态间隔类型平均值更新
        # 1. 收集所有动态间隔类型（gap_4_h/gap_5_h...）
        dynamic_gap_types = [gt for gt in set(gap_types.values())
                             if gt.startswith('gap_') and gt not in ['contact_h', 'aisle_h', 'large_h']]

        # 2. 初始化动态类型平均值字典（核心修改：沿用历史值，而非清空为0）
        # 接收prev_dynamic_avg_h参数
        dynamic_avg_h = prev_dynamic_avg_h.copy() if prev_dynamic_avg_h else {}  # 保留历史值
        for gt in dynamic_gap_types:
            # 仅当历史值不存在时初始化为0，否则沿用历史值
            if gt not in dynamic_avg_h:
                dynamic_avg_h[gt] = 0

        # 3. 更新动态类型平均值（核心修改：仅有有效实测样本时更新，无则保留历史值）
        for gap_type in dynamic_gap_types:
            current_dynamic = [g for c1, c2, g in current_gaps if gap_types.get((c1, c2)) == gap_type]
            # 仅当有有效样本时更新，无样本则保留历史值（避免推导值覆盖）
            if current_dynamic and len(current_dynamic) > 0:
                # 可选：过滤极小值（仅保留超大间隔，避免推导误差覆盖真实值）
                valid_dynamic = [g for g in current_dynamic if g > contact_avg_h * 2]
                if valid_dynamic:
                    dynamic_avg_h[gap_type] = abs(sum(valid_dynamic) / len(valid_dynamic))
                # 若无有效超大样本，仍保留历史值，不更新
            # 无新值时不执行任何操作，直接沿用历史值

        # 第二步：计算未匹配列坐标（仅处理未匹配列）
        if matched_cols:
            max_matched_col = max(matched_cols)  # 最左侧的匹配列（编号最大）
            max_known_col = max(max_known_col, max_matched_col)

            # 向左计算未匹配列（编号>max_matched_col，更左侧）
            all_col_nums = sorted(known_cols.keys())
            cols_left = [num for num in all_col_nums if num > max_matched_col and num not in matched_cols]
            for col_num in cols_left:
                right_col = col_num - 1  # 右侧相邻列（编号小1）
                if right_col in known_cols:
                    gap_type = gap_types.get((right_col, col_num), 'contact_h')
                    if gap_type == 'contact_h':
                        known_cols[col_num] = known_cols[right_col] - contact_avg_h  # 左列x = 右列x - 间隔
                    elif gap_type == 'aisle_h':
                        known_cols[col_num] = known_cols[right_col] - aisle_avg_h
                    elif gap_type == 'large_h':
                        known_cols[col_num] = known_cols[right_col] - large_avg_h
                    # 动态类型适配（使用保留的历史超大间隔值）
                    elif gap_type in dynamic_avg_h:
                        known_cols[col_num] = known_cols[right_col] - dynamic_avg_h[gap_type]
                    else:
                        known_cols[col_num] = known_cols[right_col] - contact_avg_h

            # 向右计算未匹配列（编号<max_matched_col，更右侧）
            cols_right = [num for num in reversed(all_col_nums) if num < max_matched_col and num not in matched_cols]
            for col_num in cols_right:
                left_col = col_num + 1  # 左侧相邻列（编号大1）
                if left_col in known_cols:
                    gap_type = gap_types.get((col_num, left_col), 'contact_h')
                    if gap_type == 'contact_h':
                        known_cols[col_num] = known_cols[left_col] + contact_avg_h  # 右列x = 左列x + 间隔
                    elif gap_type == 'aisle_h':
                        known_cols[col_num] = known_cols[left_col] + aisle_avg_h
                    elif gap_type == 'large_h':
                        known_cols[col_num] = known_cols[left_col] + large_avg_h
                    # 动态类型适配（使用保留的历史超大间隔值）
                    elif gap_type in dynamic_avg_h:
                        known_cols[col_num] = known_cols[left_col] + dynamic_avg_h[gap_type]
                    else:
                        known_cols[col_num] = known_cols[left_col] + contact_avg_h

        # 第三步：计算扩展列（按优先级顺序生成）
        extended_col_num = max_known_col + 1 if known_cols else 1
        extended_cols = {}
        # 定义扩展列优先级顺序：接触间隔→过道间隔→大间隔→动态间隔（按名称排序）
        ext_priority_order = []

        # 1. 基础间隔类型（按优先级加入）
        if contact_avg_h > 0:
            ext_priority_order.append(('contact', contact_avg_h, 'contact_h'))
        if aisle_avg_h > 0:
            ext_priority_order.append(('aisle', aisle_avg_h, 'aisle_h'))
        if large_avg_h > 0:
            ext_priority_order.append(('large', large_avg_h, 'large_h'))

        # 2. 动态间隔类型（按名称排序：gap_4_h→gap_5_h→...，确保顺序一致）
        dynamic_ext = []
        for gap_type in sorted(dynamic_avg_h.keys()):
            if dynamic_avg_h[gap_type] > 0:
                # 提取动态间隔编号（如gap_4_h→4），用于排序和后缀
                gap_num = re.search(r'gap_(\d+)_h', gap_type)
                if gap_num:
                    dynamic_ext.append((gap_type, dynamic_avg_h[gap_type], gap_type, int(gap_num.group(1))))
        # 按动态间隔编号升序排序（gap_4_h在前，gap_5_h在后...）
        dynamic_ext.sort(key=lambda x: x[3])
        # 加入优先级顺序（移除编号字段，保留原格式）
        ext_priority_order.extend([(item[0], item[1], item[2]) for item in dynamic_ext])

        # 按优先级顺序生成扩展列（每个间隔类型对应一个扩展列）
        suffix_offset = 0.15  # 基础后缀偏移量（依次递增0.1）
        for name, avg_val, gap_type in ext_priority_order:
            if known_cols and max_known_col in known_cols:
                max_known_x = known_cols[max_known_col]  # 最左侧已知列的x坐标
                # 生成唯一编号（避免冲突，按顺序递增后缀）
                unique_num = float(f"{extended_col_num + suffix_offset}")
                extended_cols[name] = {
                    'num': unique_num,
                    'x': max_known_x - avg_val,  # 左移一个对应间隔
                    'type': gap_type
                }
                suffix_offset += 0.1  # 每个扩展列后缀+0.1（如1.15→1.25→1.35→1.45...）

        # 第四步：二次匹配（更新未匹配列）
        all_matching_cols = known_cols.copy()
        for ext in extended_cols.values():
            all_matching_cols[ext['num']] = ext['x']

        secondary_matches = defaultdict(list)
        for rect in all_rects:
            center_x = rect_centers[rect]
            best_col = None
            min_diff = float('inf')
            for col_num in sorted(all_matching_cols.keys()):
                col_x = all_matching_cols[col_num]
                diff = abs(center_x - col_x)
                if diff < secondary_threshold and diff < min_diff:
                    min_diff = diff
                    best_col = col_num
            if best_col is not None:
                secondary_matches[best_col].append(center_x)

        # 二次匹配更新未匹配列
        for col_num, xs in secondary_matches.items():
            if col_num in known_cols and col_num not in matched_cols:
                known_cols[col_num] = sum(xs) / len(xs)

        # 新增：未匹配矩形强制创建新列
        unmatched_rects = [rect for rect in all_rects if rect not in matched_rects]
        if unmatched_rects:
            # 计算未匹配矩形的中心x坐标和平均位置
            unmatched_centers = [rect_centers[rect] for rect in unmatched_rects]
            avg_unmatched_x = sum(unmatched_centers) / len(unmatched_centers)
            min_unmatched_x = min(unmatched_centers)
            max_unmatched_x = max(unmatched_centers)

            # 与已知列的位置边界对比，判断新列方向
            if known_cols:
                min_known_x = known_cols[max(known_cols.keys())]  # 已知列最左侧x（最小）
                max_known_x = known_cols[min(known_cols.keys())]  # 已知列最右侧x（最大）
                # 新列在已知列左侧（未匹配矩形整体在已知列左侧，且间隔>1.5倍矩形宽度）
                if max_unmatched_x < min_known_x - avg_rect_width * 1.5:
                    new_col_num = max(known_cols.keys()) + 1
                    # 直接用未匹配矩形的平均x作为新列坐标
                    known_cols[new_col_num] = avg_unmatched_x
                    # 标记间隔类型为大间隔（宽间隔场景）
                    gap_types[(max(known_cols.keys()) - 1, new_col_num)] = 'large_h'
                    max_known_col = new_col_num
                # 新列在已知列右侧（未匹配矩形整体在已知列右侧，且间隔>1.5倍矩形宽度）
                elif min_unmatched_x > max_known_x + avg_rect_width * 1.5:
                    new_col_num = min(known_cols.keys()) - 1
                    known_cols[new_col_num] = avg_unmatched_x
                    gap_types[(new_col_num, min(known_cols.keys()))] = 'large_h'
            else:
                # 无已知列时直接创建列1
                known_cols[1] = avg_unmatched_x
                max_known_col = 1

        # 处理扩展列（修改：降低匹配阈值，适配少量矩形场景）
        extended_matched = {k: v for k, v in secondary_matches.items() if
                            isinstance(k, float) and k >= extended_col_num}
        if extended_matched:
            type_scores = defaultdict(lambda: {'count': 0})
            for col_num, matches in extended_matched.items():
                # 计算小数部分（如8.15→0.15→1.5→取整为1，对应优先级顺序）
                decimal_part = (col_num - int(col_num)) * 100
                suffix_int = int(decimal_part // 10)  # 1.15→11.5→1（对应第一个扩展列）
                suffix_str = str(suffix_int)

                # 匹配优先级顺序（通过后缀偏移量反向映射到间隔类型）
                if 0 <= suffix_int - 1 < len(ext_priority_order):
                    type_key = ext_priority_order[suffix_int - 1][0]
                else:
                    print(f"[调试] 无效的suffix_str: {suffix_str}，col_num: {col_num}")
                    continue

                unique_centers = set()
                for center_x in matches:
                    rounded_center = round(center_x, 2)
                    unique_centers.add(rounded_center)
                unique_count = len(unique_centers)

                # 修改：匹配数量≥1即可（适配新列只有1个矩形的场景）
                if unique_count >= 1:
                    if unique_count > type_scores[type_key]['count']:
                        type_scores[type_key] = {'count': unique_count}

            if type_scores:
                best_type = max(type_scores, key=lambda t: type_scores[t]['count'])
                # 从优先级顺序中找到对应的扩展列信息
                best_ext_info = next(
                    (ext for name, avg_val, gap_type, *rest in ext_priority_order if name == best_type), None)
                if best_ext_info and best_type in extended_cols:
                    best_ext_info = extended_cols[best_type]
                    best_count = type_scores[best_type]['count']
                    # 修改：创建阈值≥1（降低门槛）
                    if best_count >= 1:
                        known_cols[extended_col_num] = best_ext_info['x']  # 加入已知列
                        gap_types[(max_known_col, extended_col_num)] = best_ext_info['type']
                        max_known_col = max(max_known_col, extended_col_num)

        # 生成最终列编号映射（修改：强制拆分远距矩形）
        horizontal_numbers = {}
        for rect in all_rects:
            center_x = rect_centers[rect]

            if not known_cols:
                known_cols[1] = center_x
                horizontal_numbers[rect] = 1
                continue

            # 找到距离最近的已知列
            best_col = min(known_cols.keys(), key=lambda c: abs(center_x - known_cols[c]))
            min_distance = abs(center_x - known_cols[best_col])

            # 修改：距离>1.2倍矩形宽度时，强制创建新列（处理单个分散矩形）
            if min_distance > avg_rect_width * 1.2:
                if center_x < known_cols[best_col]:  # 新列在左侧
                    new_col_num = max(known_cols.keys()) + 1
                    known_cols[new_col_num] = center_x
                    horizontal_numbers[rect] = new_col_num
                    max_known_col = new_col_num
                    # 补充间隔类型
                    gap_types[(max_known_col - 1, new_col_num)] = 'large_h'
                else:  # 新列在右侧
                    new_col_num = min(known_cols.keys()) - 1
                    known_cols[new_col_num] = center_x
                    horizontal_numbers[rect] = new_col_num
                    gap_types[(new_col_num, min(known_cols.keys()))] = 'large_h'
            else:
                horizontal_numbers[rect] = best_col

        # 新增返回dynamic_avg_h
        return horizontal_numbers, known_cols, max_known_col, gap_types, contact_avg_h, aisle_avg_h, large_avg_h, dynamic_avg_h