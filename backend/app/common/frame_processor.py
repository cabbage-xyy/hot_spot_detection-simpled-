# 帧处理器 (该类实现对每帧的处理操作方法)
import copy
import os.path
from collections import deque

from app.common.normal import *
from app.common.video_zoom import *
from app.common.rect_processor import *
from app.common.rect_numbering import *
from app.common.freeze_processor import *
from app.common.hightlight_processor import *
from app.common.line_contour_processing import *
from app.core.paths import BACKEND_DIR


class FrameProcessor:
    """该类是专门的帧处理类 对帧的一系列处理方法均在这里"""
    def __init__(self, shared_data, update_hotspot_count=None):
        self.shared_data = shared_data
        self._init_shared_data()  # 初始化共享数据
        self.coordinate_buffer = deque(maxlen=6)  # 初始化实例缓冲区
        self.detection_cache = {}  # 添加检测信息缓存 格式: {frame_number: {id: {label, box}, ...}}
        self.draw_photo_cache = []  # 添加画好框线的图片信息
        self.orb = init_orb_detector(max_features=3000)  # 初始化ORB特征检测器
        self.update_hotspot_count = update_hotspot_count  # 记录放大次数

    # 初始化共享数据
    def _init_shared_data(self):
        """初始化共享数据，添加阶段跟踪所需参数 同时对外面的shared_data进行补充"""
        required_keys = {
            'coordinate_buffer': deque(maxlen=6),
            'prev_coords': {'horizontal': None, 'vertical': None},
            'freeze_counter': 0,
            'frozen_feature_points': None,
            'frozen_descriptors': None,
            'frozen_coords': None,
            'frozen_right_feature_points': None,
            'frozen_right_descriptors': None,
            'coordinate_threshold': 5,
            'zoom_state': None,
            'zoom_history': [],
            'zoom_magnification_history': [],
            'zoom_start_frame': 0,
            'cached_zoom_frame': None,
            'frozen_right_frame': None,
            'zoom_process_start_frame': None,
            'zoom_process_magnifications': [],
            'zoom_process_state': None,
            'initial_zoom_frame_left': None,
            # 稳定阶段相关参数
            'stable_phase_start_frame': None,
            'stable_phase_end_frame': None,
            'stable_phase_right_frames': [],
            'stable_phase_captured': False,
            'stage_frame_counts': {
                'zooming': 0,
                'stable': 0,
                'shrinking': 0
            },
            'candidate_stages': [],
            'confirmed_stages': [],
            'current_state': '正常运行',  # 初始状态为正常运行
            'prev_state': None,
            'shrink_stable_scale_checked': False,
            'zoom_stage_counter': 0,
            'counted_zoom_stage_keys': set(),
        }

        for key, value in required_keys.items():
            if key not in self.shared_data:
                self.shared_data[key] = value

        if not isinstance(self.shared_data.get('counted_zoom_stage_keys'), set):
            self.shared_data['counted_zoom_stage_keys'] = set()

    # 资源释放
    def release_resources(self):
        """释放所有占用的资源"""
        # 清空缓存数据
        self.coordinate_buffer.clear()
        self.detection_cache.clear()

        # 释放共享数据中的资源
        if 'coordinate_buffer' in self.shared_data:
            self.shared_data['coordinate_buffer'].clear()
        self.shared_data.pop('frozen_feature_points', None)
        self.shared_data.pop('frozen_descriptors', None)
        self.shared_data.pop('frozen_right_feature_points', None)
        self.shared_data.pop('frozen_right_descriptors', None)
        self.shared_data.pop('frozen_right_frame', None)
        self.shared_data.pop('cached_zoom_frame', None)
        self.shared_data.pop('initial_zoom_frame_left', None)
        self.shared_data.pop('stable_phase_right_frames', None)

        # 释放OpenCV可能持有的全局资源
        cv2.destroyAllWindows()

    # 使用pt模型进行检测
    def _save_max_magnification_frames(self):
        """视频「最大倍率画面阶段」的核心检测逻辑—— 聚焦视频中标记为 “最大倍率” 的关键阶段，提取该阶段的核心帧，用 YOLOv5 模型检测画面中的 “组件破碎 / 裂纹” 缺陷，最终缓存检测结果"""
        # 获取最大倍率阶段参数（保留原帧范围逻辑，确保检测目标帧正确）
        raw_max_start = self.shared_data.get('max_mag_start')
        raw_max_end = self.shared_data.get('max_mag_end')
        stable_frames = self.shared_data.get('stable_phase_right_frames', [])

        # 参数校验（确保输入有效，避免 None - 4 之类的运行时错误）
        if raw_max_start is None or raw_max_end is None:
            print(
                "【DEBUG-最大倍率阶段】未识别到有效最大倍率阶段，跳过缺陷模型检测。"
                f"max_mag_start={raw_max_start}, max_mag_end={raw_max_end}, "
                f"stable_frames={len(stable_frames)}"
            )
            return

        max_start = max(raw_max_start - 4, 0)
        max_end = max(raw_max_end - 4, 0)

        if max_end < max_start:
            print(
                "【DEBUG-最大倍率阶段】最大倍率阶段帧范围异常，跳过缺陷模型检测。"
                f"raw_max_start={raw_max_start}, raw_max_end={raw_max_end}, "
                f"max_start={max_start}, max_end={max_end}"
            )
            return

        if not stable_frames:
            print(
                "【DEBUG-最大倍率阶段】最大倍率阶段没有缓存右半边帧，跳过缺陷模型检测。"
                f"max_start={max_start}, max_end={max_end}"
            )
            return

        # 计算中间1/2帧范围（保留原帧筛选逻辑，聚焦核心检测帧）
        total_frames = max_end - max_start + 1
        # 计算中间3/4帧的长度（向下取整，确保为整数）
        three_quarter_length = (total_frames * 3) // 4
        if three_quarter_length <= 0:
            print(f"【DEBUG-最大倍率阶段】中间帧长度异常 total_frames={total_frames}，跳过处理")
            return

        # 计算中间3/4帧的起始位置：从总长度的1/8处开始（(总长度-3/4长度)/2 = (1/4总长度)/2 = 1/8总长度）
        mid_three_start = max_start + (total_frames - three_quarter_length) // 2
        # 计算中间3/4帧的结束位置（起始+长度-1，确保闭区间）
        mid_three_end = mid_three_start + three_quarter_length - 1

        # 范围有效性检查
        if mid_three_start > mid_three_end or mid_three_start < max_start or mid_three_end > max_end:
            print(f"中间帧范围计算异常（{mid_three_start}-{mid_three_end}），跳过处理")
            return

        # 计算缓存索引范围（映射帧序号到缓存列表索引）
        cache_start_idx = mid_three_start - max_start
        cache_end_idx = mid_three_end - max_start
        if cache_start_idx < 0 or cache_end_idx >= len(stable_frames):
            print(f"缓存索引超出范围（需{cache_start_idx}-{cache_end_idx}，实际缓存{len(stable_frames)}帧），跳过处理")
            return

        # 导入模型并且检测画面
        detect_frame_result = detect_frames_with_progress(stable_frames, max_start, max_end, cache_start_idx, cache_end_idx)
        self.detection_cache = detect_frame_result

    # 阶段判断
    def _confirm_valid_stages(self, candidate_stages, confirmed_stages):
        """对视频帧的阶段状态（如 “放大 / 稳定 / 缩小”）进行筛选、校验、标记和日志输出，最终确认有效阶段并记录关键信息（比如 “最大倍率画面”），属于视频状态分析 / 阶段跟踪的核心逻辑"""
        # 1. 过滤出持续帧数>5的有效候选阶段（仅过滤，不合并任何阶段）
        valid_candidates = [stage for stage in candidate_stages if stage['duration'] > 5]

        # 2. 按帧号排序（确保时序正确）
        valid_candidates.sort(key=lambda x: x['start'])

        # 3. 直接使用过滤排序后的阶段，不进行任何合并操作
        confirmed_stages_list = valid_candidates.copy()

        # 4. 阶段类型修正：严格标记"放大→稳定→缩小"中的稳定为最大倍率画面
        # 初始化最大倍率变量（避免None报错）
        self.shared_data['max_mag_start'] = None
        self.shared_data['max_mag_end'] = None

        # 遍历所有阶段（从第2个到倒数第2个，确保有前、后阶段）
        for i in range(1, len(confirmed_stages_list) - 1):
            prev_stage = confirmed_stages_list[i - 1]
            current_stage = confirmed_stages_list[i]
            next_stage = confirmed_stages_list[i + 1]

            # 核心判断：严格匹配"放大→稳定→缩小"序列
            if (prev_stage['state'] == 'zooming' and
                    current_stage['state'] == 'stable' and
                    next_stage['state'] == 'shrinking'):
                # 将该稳定阶段标记为最大倍率画面
                current_stage['state'] = 'max_magnification'
                # 记录最大倍率阶段的帧范围
                self.shared_data['max_mag_start'] = current_stage['start']
                self.shared_data['max_mag_end'] = current_stage['end']
                print(f"识别到最大倍率阶段：帧 {current_stage['start']}-{current_stage['end']}")
                # 每确认一次完整的“放大 → 最大倍率稳定 → 缩小”阶段，热斑组件数 +1
                # 使用阶段起止帧作为唯一键，避免同一个阶段被重复确认时重复计数
                stage_key = (current_stage['start'], current_stage['end'])
                counted_stage_keys = self.shared_data.setdefault('counted_zoom_stage_keys', set())

                if stage_key not in counted_stage_keys:
                    counted_stage_keys.add(stage_key)
                    self.shared_data['zoom_stage_counter'] = int(self.shared_data.get('zoom_stage_counter', 0)) + 1
                    current_count = int(self.shared_data['zoom_stage_counter'])
                    print(f"热斑组件数更新：检测到第 {current_count} 次有效放大阶段，阶段帧范围 {stage_key}")

                    if self.update_hotspot_count is not None:
                        self.update_hotspot_count(current_count)


            elif (current_stage['state'] == 'stable' and
                  prev_stage['state'] == 'zooming'):
                current_stage['state'] = 'pre_max_stable'  # 放大后稳定（非最大）
            elif (current_stage['state'] == 'stable' and
                  prev_stage['state'] == 'shrinking'):
                current_stage['state'] = 'shrink_pause'  # 缩小后稳定

        # 统一的状态名称映射（包含所有可能状态）
        state_name_map = {
            'zooming': '放大',
            'stable': '放大暂停',
            'shrinking': '缩小',
            'max_magnification': '最大倍率画面',
            'shrink_pause': '缩小暂停',
            'pre_max_stable': '放大后稳定'  # 新增映射，避免KeyError
        }

        # 打印所有确认的阶段（无合并，保留原始阶段+标记后的最大倍率）
        print("\n===== 阶段转换信息 =====")
        for i, stage in enumerate(confirmed_stages_list):
            # 确保状态能找到对应的中文名称
            state_name = state_name_map.get(stage['state'], f"未知状态({stage['state']})")
            print(f"阶段 {i + 1}: {state_name} (帧 {stage['start']}-{stage['end']}, 持续{stage['duration']}帧)")

            # 打印阶段转换（如果不是第一阶段）
            if i > 0:
                prev_stage = confirmed_stages_list[i - 1]
                prev_state_name = state_name_map.get(prev_stage['state'], f"未知状态({prev_stage['state']})")
                transition_start = prev_stage['end']
                transition_end = stage['start']
                print(f"  转换: {prev_state_name} → {state_name} (帧 {transition_start}-{transition_end})")
        print("========================\n")

        # 5. 保存确认的阶段到共享数据
        confirmed_stages.extend(confirmed_stages_list)
        self.shared_data['confirmed_stages'] = confirmed_stages
        self.shared_data['confirmed_stages'] = confirmed_stages

        # 6. 保存最大倍率阶段的右半边画面（从缓存中提取）
        self._save_max_magnification_frames()

        # 打印阶段确认日志
        print("\n===== 确认阶段日志 =====")
        for stage in confirmed_stages_list:
            state_name = state_name_map.get(stage['state'], f"未知状态({stage['state']})")
            print(f"确认阶段: 帧 {stage['start']}-{stage['end']} ({stage['duration']}帧) - {state_name}")

    # 在右边视频进行缺陷画图展示
    def draw_annotations_on_video(self, output_path, input_final_video_path, output_annotated_video_path, total_frames_A):

        # 提取所有带检测信息的帧号（全局唯一，已包含多阶段）
        cached_B_frames = sorted(self.detection_cache.keys())
        if not cached_B_frames:
            print("警告：无检测信息，无需绘制标注")
            return

        # 计算标注帧在最终视频中的范围
        first_B_frame = cached_B_frames[0]
        last_B_frame = cached_B_frames[-1]
        first_final_frame = total_frames_A + first_B_frame
        last_final_frame = total_frames_A + last_B_frame

        # 打开视频并初始化写入器
        cap = cv2.VideoCapture(input_final_video_path)
        if not cap.isOpened():
            print(f"错误：无法打开视频 {input_final_video_path}")
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        half_width = width // 2  # 右半边绘制标注
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # type: ignore

        output_annotated_video_path = os.path.abspath(os.path.dirname(output_path)) + "/" + output_annotated_video_path
        print("模型检测的视频地址", output_annotated_video_path)
        out = cv2.VideoWriter(output_annotated_video_path, fourcc, fps, (width, height))

        # 逐帧处理
        current_final_frame = 0
        cached_idx = 0
        total_cached = len(cached_B_frames)

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            current_final_frame += 1

            # 处理缓存中的帧（含多阶段检测结果）
            if cached_idx < total_cached:
                target_B_frame = cached_B_frames[cached_idx]
                target_final_frame = total_frames_A + target_B_frame

                if current_final_frame == target_final_frame:
                    frame_right = frame[:, half_width:]
                    detection_info = self.detection_cache[target_B_frame]

                    if detection_info:  # 有检测框时才处理
                        # 1. 初始化极值坐标（取第一个框的坐标作为初始值）
                        min_x1 = detection_info[0]["box"][0]
                        min_y1 = detection_info[0]["box"][1]
                        max_x2 = detection_info[0]["box"][2]
                        max_y2 = detection_info[0]["box"][3]
                        # 2. 收集所有标签并去重
                        label_set = set()
                        label_set.add(detection_info[0]["label"])

                        # 3. 遍历所有框，更新极值坐标和标签
                        for item in detection_info[1:]:
                            x1, y1, x2, y2 = item["box"]
                            min_x1 = min(min_x1, x1)  # 最左侧x
                            min_y1 = min(min_y1, y1)  # 最上方y
                            max_x2 = max(max_x2, x2)  # 最右侧x
                            max_y2 = max(max_y2, y2)  # 最下方y
                            label_set.add(item["label"])  # 收集标签去重

                        # 4. 合并标签（按字母/自定义顺序排序，避免乱序）
                        merged_label = "/".join(sorted(label_set))  # 组件破碎/裂纹   等
                        # 加前缀，后续要把训练集中的组件破碎和裂纹标签合并
                        # merged_label = "缺陷类型：" + "/".join(sorted(label_set)) # 缺陷类型：组件破碎/积灰  等
                        # 综合框的最终坐标
                        combine_x1, combine_y1 = min_x1, min_y1
                        combine_x2, combine_y2 = max_x2, max_y2

                        # 绘制综合边界框
                        cv2.rectangle(frame_right, (combine_x1, combine_y1), (combine_x2, combine_y2), (0, 0, 255), 5)

                        # 绘制引导线（基于综合框的左上角）
                        base_line_length = (combine_x2 - combine_x1) // 3
                        angle = 45
                        diagonal_length = int(base_line_length * 1.3)
                        end_x_diag = combine_x1 + int(diagonal_length * np.cos(np.radians(angle)))
                        end_y_diag = combine_y1 - int(diagonal_length * np.sin(np.radians(angle)))
                        cv2.line(frame_right, (combine_x1, combine_y1), (end_x_diag, end_y_diag), (0, 0, 255), 5)

                        # 绘制水平引导线和合并标签
                        (text_width, text_height), _ = cv2.getTextSize(merged_label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                        horizontal_length = text_width + 20
                        end_x_horiz = end_x_diag + horizontal_length
                        cv2.line(frame_right, (end_x_diag, end_y_diag), (end_x_horiz, end_y_diag), (0, 0, 255), 5)

                        # 绘制合并后的中文标签
                        label_x = end_x_diag + (horizontal_length - text_width) // 2
                        label_y = end_y_diag - text_height - 28
                        frame_right = put_chinese_text(
                            frame_right, merged_label, (label_x, max(0, label_y)), font_size=40, color=(0, 0, 255)
                        )

                    # 合并画面并更新索引
                    frame[:, half_width:] = frame_right
                    cached_idx += 1

            out.write(frame)

        # 释放资源并校验
        cap.release()
        out.release()

    # 单独拎出那个模型检测有结果的图片
    # 从self.detection_cache_keys()找出对应的帧号 然后再去视频B进行读取该帧 然后右边画了 再拼接左边 就一整框出来的图片
    def draw_one_annotation_image(self, video_path, target_frame=None, save_path=None, total_frames_A=None):
        """
        从 self.detection_cache 中取一帧，直接从视频里跳到该帧，
        只对右半边画框，然后返回处理后的整张图片。

        参数:
            video_path: 原视频路径
            target_frame: 想取的帧号；如果不传，就默认取 detection_cache 里的第一帧
            save_path: 可选，保存图片路径，比如 "./output/test_433.jpg"

        返回:
            frame: 处理后的整张图片(np.ndarray)
            如果失败返回 None
        """

        # 1. 检查 detection_cache
        if not hasattr(self, "detection_cache") or not self.detection_cache:
            print("警告：self.detection_cache 为空，没有可处理的检测帧")
            return None

        cached_frames = sorted(self.detection_cache.keys())

        # 2. 默认取第一帧
        if target_frame is None:
            target_frame = cached_frames[0]

        if target_frame not in self.detection_cache:
            print(f"错误：target_frame={target_frame} 不在 self.detection_cache 中")
            print(f"可选帧号示例: {cached_frames[:10]}")
            return None

        print(f"准备处理的帧号: {target_frame}")

        # 3. 打开视频
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"错误：无法打开视频 {video_path}")
            return None

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            half_width = width // 2

            print(f"视频总帧数: {total_frames}")
            print(f"视频尺寸: {width} x {height}")

            # 4. 检查帧号范围
            if target_frame < 0 or target_frame >= total_frames:
                print(f"错误：目标帧 {target_frame} 超出视频范围 0 ~ {total_frames - 1}")
                return None

            # 5. 直接跳到指定帧
            ok = cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames_A + target_frame)
            print(f"跳帧结果: {ok}")

            ret, frame = cap.read()
            if not ret or frame is None:
                print(f"错误：无法读取第 {target_frame} 帧")
                return None

            # 6. 取右半边
            frame_right = frame[:, half_width:].copy()

            # 7. 取这一帧的检测结果
            detection_info = self.detection_cache[target_frame]
            print(f"该帧检测结果数量: {len(detection_info)}")

            if detection_info:
                # 初始化综合框
                min_x1 = detection_info[0]["box"][0]
                min_y1 = detection_info[0]["box"][1]
                max_x2 = detection_info[0]["box"][2]
                max_y2 = detection_info[0]["box"][3]

                label_set = set()
                label_set.add(detection_info[0]["label"])

                # 合并所有框
                for item in detection_info[1:]:
                    x1, y1, x2, y2 = item["box"]
                    min_x1 = min(min_x1, x1)
                    min_y1 = min(min_y1, y1)
                    max_x2 = max(max_x2, x2)
                    max_y2 = max(max_y2, y2)
                    label_set.add(item["label"])

                merged_label = "/".join(sorted(label_set))

                combine_x1, combine_y1 = min_x1, min_y1
                combine_x2, combine_y2 = max_x2, max_y2

                # 8. 画综合框
                cv2.rectangle(
                    frame_right,
                    (combine_x1, combine_y1),
                    (combine_x2, combine_y2),
                    (0, 0, 255),
                    5
                )

                # 9. 画引导斜线
                base_line_length = max(30, (combine_x2 - combine_x1) // 3)
                angle = 45
                diagonal_length = int(base_line_length * 1.3)

                end_x_diag = combine_x1 + int(diagonal_length * np.cos(np.radians(angle)))
                end_y_diag = combine_y1 - int(diagonal_length * np.sin(np.radians(angle)))

                cv2.line(
                    frame_right,
                    (combine_x1, combine_y1),
                    (end_x_diag, end_y_diag),
                    (0, 0, 255),
                    5
                )

                # 10. 画水平线
                (text_width, text_height), _ = cv2.getTextSize(
                    merged_label,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    2
                )

                horizontal_length = text_width + 20
                end_x_horiz = end_x_diag + horizontal_length

                cv2.line(
                    frame_right,
                    (end_x_diag, end_y_diag),
                    (end_x_horiz, end_y_diag),
                    (0, 0, 255),
                    5
                )

                # 11. 画中文标签
                label_x = end_x_diag + (horizontal_length - text_width) // 2
                label_y = end_y_diag - text_height - 28

                frame_right = put_chinese_text(
                    frame_right,
                    merged_label,
                    (label_x, max(0, label_y)),
                    font_size=40,
                    color=(0, 0, 255)
                )

            else:
                print(f"警告：第 {target_frame} 帧没有检测结果")

            # 12. 拼回整张图
            frame[:, half_width:] = frame_right

            # 13. 保存图片
            if save_path:
                os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
                cv2.imwrite(save_path, frame)
                print(f"图片已保存到: {save_path}")

            self.draw_photo_cache.append(frame)

            return frame

        finally:
            cap.release()


    # 帧处理过程的核心操作
    def process_frame(self, frame, frame_number, frame_key):
        """对视频每一帧进行多维度分析与处理（包括矩形检测、热斑编号标注、卡顿 / 放大状态识别、最大倍率阶段标记、缺陷检测准备等），最终输出带可视化标注的处理后帧"""
        # 初始化共享数据中的放大检测激活状态（如果不存在）
        if 'dynamic_avg_v' not in self.shared_data:
            self.shared_data['dynamic_avg_v'] = {}
        if 'dynamic_avg_h' not in self.shared_data:
            self.shared_data['dynamic_avg_h'] = {}
        if 'is_zoom_process_active' not in self.shared_data:
            self.shared_data['is_zoom_process_active'] = False
        in_zoom_process = self.shared_data['is_zoom_process_active']
        prev_zoom_process_state = self.shared_data.get('prev_zoom_process_state')
        current_zoom_process_state = self.shared_data.get('zoom_process_state')

        # 保存当前状态到prev_zoom_process_state，用于下一帧判断
        self.shared_data['prev_zoom_process_state'] = current_zoom_process_state

        # 添加：打印当前帧的状态
        # 获取当前状态（优先取处理中的状态，其次取常规状态）
        current_state = self.shared_data.get('zoom_process_state') or self.shared_data.get('current_state', '未知')
        # 状态名称映射（保持与阶段判断一致的中文名称）
        state_name_map = {
            'zooming': '放大',
            'stable': '稳定',
            'shrinking': '缩小',
            'max_magnification': '最大倍率画面',
            'shrink_pause': '缩小暂停',
            'pre_max_stable': '放大后稳定',
            '正常运行': '正常运行'
        }
        # 转换为中文名称并打印
        state_name = state_name_map.get(current_state, f"未知状态({current_state})")
        print(f"帧 {frame_number} 状态: {state_name}")

        # 边缘检测和矩形提取（原有逻辑保持不变）
        original_height, original_width = frame.shape[:2]
        half_width = original_width // 2
        frame_left = frame[:, :half_width].copy()
        frame_right = frame[:, half_width:].copy()
        rectangles = []

        # 读取共享数据（原有逻辑保持不变）
        zoom_state = self.shared_data.get('zoom_state')
        in_zoom_detection = zoom_state is not None and zoom_state in ['zooming', 'shrinking', 'stable']
        zoom_process_state = self.shared_data.get('zoom_process_state')

        # 仅在非放大检测状态下进行完整处理流程（原有逻辑保持不变）
        if not in_zoom_detection and not in_zoom_process:
            # 灰度计算
            gray = 0.6 * frame_left[:, :, 2] + 0.3 * frame_left[:, :, 1] + 0.1 * frame_left[:, :, 0]
            gray = np.uint8(gray)

            # 直线检测边缘
            line_image_0 = perform_edge_detection_and_line_fitting(gray)
            contours_lines_0, _ = cv2.findContours(line_image_0, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            rects_lines_0 = []
            for cnt in contours_lines_0:
                epsilon = 0.05 * cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                if len(approx) >= 4:
                    x, y, w, h = cv2.boundingRect(approx)
                    rects_lines_0.append((x, y, w, h))

            # 延长直线图
            line_image_1 = zhijieyanchang(gray)
            contours_lines_1, _ = cv2.findContours(line_image_1, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            rects_lines_1 = []
            for cnt in contours_lines_1:
                epsilon = 0.05 * cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                if len(approx) >= 4:
                    x, y, w, h = cv2.boundingRect(approx)
                    rects_lines_1.append((x, y, w, h))

            # 直接边缘
            blurred = cv2.GaussianBlur(gray, (9, 9), 2)
            edges = cv2.Canny(blurred, 50, 150)

            contours_edges, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            rectangles_edges = []
            for cnt in contours_edges:
                epsilon = 0.05 * cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                if len(approx) >= 4:
                    x, y, w, h = cv2.boundingRect(approx)
                    rectangles_edges.append((x, y, w, h))

            # 二值边缘
            median_blur = cv2.medianBlur(gray, 5)
            bilateral_blur = cv2.bilateralFilter(median_blur, 5, 50, 50)
            kernel = np.ones((3, 3), np.uint8)

            # 低二值矩形
            _, binary_low = cv2.threshold(bilateral_blur, 60, 255, cv2.THRESH_BINARY)
            dilated_low = cv2.dilate(binary_low, kernel, iterations=1)
            closed_low = cv2.morphologyEx(dilated_low, cv2.MORPH_CLOSE, kernel)
            erzhi_low = cv2.Canny(closed_low, 50, 150)
            contours_erzhi_low, _ = cv2.findContours(erzhi_low, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            rectangles_erzhi_low = []
            for cnt in contours_erzhi_low:
                epsilon = 0.05 * cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                if len(approx) >= 4:
                    x, y, w, h = cv2.boundingRect(approx)
                    rectangles_erzhi_low.append((x, y, w, h))

            # 高二值矩形
            _, binary_high = cv2.threshold(bilateral_blur, 80, 255, cv2.THRESH_BINARY)
            dilated_high = cv2.dilate(binary_high, kernel, iterations=1)
            closed_high = cv2.morphologyEx(dilated_high, cv2.MORPH_CLOSE, kernel)
            erzhi_high = cv2.Canny(closed_high, 50, 150)
            contours_erzhi_high, _ = cv2.findContours(erzhi_high, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            rectangles_erzhi_high = []
            for cnt in contours_erzhi_high:
                epsilon = 0.05 * cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                if len(approx) >= 4:
                    x, y, w, h = cv2.boundingRect(approx)
                    rectangles_erzhi_high.append((x, y, w, h))

            # 合并直线图和延长直线图的矩形
            all_rects = rects_lines_0 + rects_lines_1 + rectangles_edges + rectangles_erzhi_low + rectangles_erzhi_high

            # 去重处理
            seen_rects = set()
            unique_rectangles = []
            for rect in all_rects:
                key = (rect[0], rect[1], rect[2], rect[3])
                if key not in seen_rects:
                    seen_rects.add(key)
                    unique_rectangles.append(rect)

            # 绘制所有矩形
            rectangles = all_rects
            for rect in rectangles:
                x, y, w, h = rect
                # cv2.rectangle(frame_left, (x, y), (x + w, y + h), (255, 255, 255), 2)

            # 根据矩形大轮廓筛选矩形
            g_channel = frame_left[:, :, 1]
            _, binary_g = cv2.threshold(g_channel, 120, 255, cv2.THRESH_BINARY)
            valid_contour = get_large_black_regions(binary_g)
            black_regions_inverted = cv2.bitwise_not(valid_contour)
            contours, _ = cv2.findContours(black_regions_inverted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            contour_rects = []
            if not contours:
                pass
            else:
                for rect in rectangles:
                    x, y, w, h = rect
                    center_x = int(x + w / 2)
                    center_y = int(y + h / 2)
                    is_in_black_area = False

                    for cnt in contours:
                        if cv2.pointPolygonTest(cnt, (center_x, center_y), False) >= 0:
                            is_in_black_area = True
                            break

                    if is_in_black_area:
                        contour_rects.append(rect)
            rectangles = filter_rectangles_1(contour_rects)
            rectangles = handle_overlapping_rectangles(rectangles)

            # initial_groups = group_adjacent_rectangles(rectangles)
            # groups = merge_adjacent_groups(initial_groups)
            # groups = filter_rectangles_by_rows(groups)

            groups = []
            group_bounds = []

            # 绘制筛选后矩形
            for rect in rectangles:
                x, y, w, h = rect
                cv2.rectangle(frame_left, (x, y), (x + w, y + h), (0, 255, 0), 1)

            # 计算所有普通矩形的竖直边长平均值
            all_rect_heights = [rect[3] for rect in rectangles]
            avg_rect_height = sum(all_rect_heights) / len(all_rect_heights) if all_rect_heights else 0
            all_rect_weights = [rect[2] for rect in rectangles]
            avg_rect_weight = sum(all_rect_weights) / len(all_rect_weights) if all_rect_heights else 0
            avg_rect_area = avg_rect_height * avg_rect_weight
            self.shared_data['avg_rect_height'] = avg_rect_height
            self.shared_data['avg_rect_weight'] = avg_rect_weight

            # 过滤符合条件的矩形组
            valid_groups = []

            # 检测高亮区域轮廓
            bright_contours = detect_bright_regions(frame_left, avg_rect_area)

            # 获取左半帧的G通道并提取大黑区域
            large_black_regions = get_large_black_regions(g_channel)  # 得到大黑区域
            # 获取大黑区域的外轮廓
            black_contours = get_multi_large_black_contours(large_black_regions)  # 大黑区域外轮廓列表
            # 过滤中心不在大黑区域内的高亮区域
            filtered_bright_contours = []
            if bright_contours is not None and len(black_contours) > 0:
                for bright_cnt in bright_contours:
                    # 计算高亮区域轮廓的中心
                    M = cv2.moments(bright_cnt)
                    if M["m00"] == 0:  # 避免除以零
                        continue
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])

                    # 检查中心是否在任何大黑区域轮廓内
                    is_inside = False
                    for black_cnt in black_contours:
                        if cv2.pointPolygonTest(black_cnt, (cX, cY), False) >= 0:
                            is_inside = True
                            break

                    if is_inside:
                        filtered_bright_contours.append(bright_cnt)

            # 更新为过滤后的高亮区域轮廓
            bright_contours = filtered_bright_contours if filtered_bright_contours else None

            all_rects = rectangles
        else:
            # 放大检测阶段，跳过矩形检测和筛选
            all_rects = []
            group_bounds = []
            avg_rect_height = 0
            avg_rect_weight = 0
            avg_rect_area = 0
            bright_contours = None

        # 主函数中的处理逻辑（原有逻辑保持不变）
        current_coords = {'horizontal': None, 'vertical': None}

        # 读取共享数据（原有逻辑保持不变）
        row_data = self.shared_data.get('row_data', {})
        prev_max_row = self.shared_data.get('prev_max_row', 0)
        number_frame_history = self.shared_data.get('number_frame_history', {})
        screenshot_cache = self.shared_data.get('screenshot_cache', {})
        delay_counters = self.shared_data.get('delay_counters', {})
        column_data = self.shared_data.get('column_data', {})
        prev_max_col = self.shared_data.get('prev_max_col', 0)
        gap_types = self.shared_data.get('gap_types', None)
        contact_avg = self.shared_data.get('contact_avg', None)
        aisle_avg = self.shared_data.get('aisle_avg', None)
        large_avg = self.shared_data.get('large_avg', None)
        gap_types_v = self.shared_data.get('gap_types_v', None)
        contact_avg_v = self.shared_data.get('contact_avg_v', None)
        aisle_avg_v = self.shared_data.get('aisle_avg_v', None)
        large_avg_v = self.shared_data.get('large_avg_v', None)
        dynamic_avg_v = self.shared_data.get('dynamic_avg_v', {})
        dynamic_avg_h = self.shared_data.get('dynamic_avg_h', {})

        # 仅在非放大检测状态下进行编号程序（原有逻辑保持不变）
        if not in_zoom_detection and not in_zoom_process:
            # 矩形横坐标编号
            horizontal_numbers, column_data, current_max_col, gap_types, contact_avg, aisle_avg, large_avg, dynamic_avg_h = get_horizontal_numbering_righttoleft(
                all_rects,
                prev_known_cols=column_data,
                prev_max_known_col=prev_max_col,
                prev_gap_types=gap_types,
                prev_contact_avg_h=contact_avg,
                prev_aisle_avg_h=aisle_avg,
                prev_large_avg_h=large_avg,
                prev_dynamic_avg_h=dynamic_avg_h  # 新增动态间隔参数
            )

            # 矩形组纵坐标编号
            vertical_numbers, row_data, current_max_row, gap_types_v, contact_avg_v, aisle_avg_v, large_avg_v, dynamic_avg_v = get_vertical_numbering_bottomup(
                all_rects,
                prev_known_rows=row_data,
                prev_max_known_row=prev_max_row,
                prev_gap_types=gap_types_v,
                prev_contact_avg_v=contact_avg_v,
                prev_aisle_avg_v=aisle_avg_v,
                prev_large_avg_v=large_avg_v,
                prev_dynamic_avg_v=dynamic_avg_v  # 新增参数
            )

            # 保存当前帧坐标
            current_coords['horizontal'] = column_data
            current_coords['vertical'] = row_data

            # 确保共享数据中的coordinate_buffer已初始化
            if 'coordinate_buffer' not in self.shared_data:
                self.shared_data['coordinate_buffer'] = deque(maxlen=6)
            coordinate_buffer = self.shared_data['coordinate_buffer']
            coordinate_buffer.append(copy.deepcopy(current_coords))
        else:
            # 放大检测状态下不更新坐标
            horizontal_numbers = None
            vertical_numbers = None
            current_max_col = prev_max_col
            current_max_row = prev_max_row
            # 明确初始化coordinate_buffer避免引用问题
            coordinate_buffer = self.shared_data.get('coordinate_buffer', deque(maxlen=6))

        # 确保实例的coordinate_buffer已初始化（原有逻辑保持不变）
        if not hasattr(self, 'coordinate_buffer'):
            self.coordinate_buffer = deque(maxlen=6)
        self.coordinate_buffer.append(copy.deepcopy(current_coords))

        # 判断是否卡顿（使用新的相隔5帧比较函数）（原有逻辑保持不变）
        is_freeze = False
        if isinstance(coordinate_buffer, deque) and len(coordinate_buffer) >= 6:
            five_ago_coords = coordinate_buffer[0]
            is_freeze = check_freeze_with_5frame_gap(
                current_h=current_coords['horizontal'],
                current_v=current_coords['vertical'],
                five_ago_h=five_ago_coords['horizontal'],
                five_ago_v=five_ago_coords['vertical'],
                threshold=5
            )

        # 处理卡顿状态（原有逻辑保持不变）
        freeze_counter = self.shared_data.get('freeze_counter', 0)
        frozen_feature_points = self.shared_data.get('frozen_feature_points')
        frozen_descriptors = self.shared_data.get('frozen_descriptors')
        frozen_right_feature_points = self.shared_data.get('frozen_right_feature_points')
        frozen_right_descriptors = self.shared_data.get('frozen_right_descriptors')
        frozen_coords = self.shared_data.get('frozen_coords')
        zoom_magnification_history = self.shared_data.get('zoom_magnification_history', [])
        prev_right_kp = self.shared_data.get('prev_right_kp')
        prev_right_des = self.shared_data.get('prev_right_des')

        if (is_freeze or freeze_counter >= 1) and not in_zoom_process:  # 卡顿且不放大时
            freeze_counter += 1

            if freeze_counter == 1:
                kp, des = detect_features(frame_left)
                frozen_feature_points = kp
                frozen_descriptors = des

                right_kp, right_des = detect_features(frame_right)
                frozen_right_feature_points = right_kp
                frozen_right_descriptors = right_des
                prev_right_kp = right_kp
                prev_right_des = right_des

                frozen_coords = copy.deepcopy(current_coords)
                self.shared_data['frozen_right_frame'] = frame_right.copy()
                self.shared_data['zoom_state'] = None
                self.shared_data['zoom_history'] = []
                self.shared_data['zoom_magnification_history'] = []
                self.shared_data['zoom_start_frame'] = frame_number
                self.shared_data['cached_zoom_frame'] = None
                self.shared_data['initial_zoom_frame_left'] = frame_left.copy()

            else:
                current_kp, current_des = detect_features(frame_left)
                movement_result = calculate_movement(
                    frozen_feature_points,
                    frozen_descriptors,
                    current_kp,
                    current_des
                )
                if movement_result is None:
                    # 处理特征匹配失败的情况
                    movement = None
                    src_pts = None
                    dst_pts = None
                else:
                    movement, src_pts, dst_pts = movement_result

                gray_right = cv2.cvtColor(frame_right, cv2.COLOR_BGR2GRAY)
                gray_right = cv2.GaussianBlur(gray_right, (3, 3), 1.2)
                current_right_kp, current_right_des = extract_orb_features(gray_right, self.orb)

                scale = 1.0
                if (prev_right_kp is not None and prev_right_des is not None and
                        current_right_kp is not None and current_right_des is not None):
                    matches = match_orb_features(prev_right_des, current_right_des, match_threshold=30.0)
                    if matches is not None:
                        scale = calculate_magnification_from_matches(prev_right_kp, current_right_kp, matches) or 1.0

                prev_right_kp = current_right_kp
                prev_right_des = current_right_des

                zoom_magnification_history.append(scale)
                if len(zoom_magnification_history) > 5:
                    zoom_magnification_history.pop(0)
                self.shared_data['zoom_magnification_history'] = zoom_magnification_history

                magnification_product = np.prod(zoom_magnification_history) if zoom_magnification_history else 1.0

                if freeze_counter <= 5 or (movement is not None and
                                           (abs(movement[0]) <= 5 and abs(movement[1]) <= 5) and
                                           0.98 <= magnification_product <= 1.03):
                    pass

                elif movement is not None and (
                        abs(movement[0]) > 5 or abs(movement[1]) > 5) and 0.98 <= magnification_product <= 1.03:
                    corrected_coords = apply_movement(frozen_coords, movement)

                    horizontal_numbers, column_data, current_max_col, gap_types, contact_avg, aisle_avg, large_avg, dynamic_avg_h = get_horizontal_numbering_righttoleft(
                        all_rects,
                        prev_known_cols=column_data,
                        prev_max_known_col=prev_max_col,
                        prev_gap_types=gap_types,
                        prev_contact_avg_h=contact_avg,
                        prev_aisle_avg_h=aisle_avg,
                        prev_large_avg_h=large_avg,
                        prev_dynamic_avg_h=dynamic_avg_h  # 新增动态间隔参数
                    )
                    vertical_numbers, row_data, current_max_row, gap_types_v, contact_avg_v, aisle_avg_v, large_avg_v, dynamic_avg_v = get_vertical_numbering_bottomup(
                        all_rects,
                        prev_known_rows=row_data,
                        prev_max_known_row=prev_max_row,
                        prev_gap_types=gap_types_v,
                        prev_contact_avg_v=contact_avg_v,
                        prev_aisle_avg_v=aisle_avg_v,
                        prev_large_avg_v=large_avg_v,
                        prev_dynamic_avg_v=dynamic_avg_v  # 新增参数
                    )

                    current_coords['horizontal'] = column_data
                    current_coords['vertical'] = row_data

                    freeze_counter = 0
                    frozen_feature_points = None
                    frozen_descriptors = None
                    frozen_right_feature_points = None
                    frozen_right_descriptors = None
                    frozen_coords = None
                    prev_right_kp = None
                    prev_right_des = None
                    self.shared_data['zoom_state'] = None
                    self.shared_data['zoom_history'] = []
                    self.shared_data['zoom_magnification_history'] = []

                elif magnification_product > 1.03 and not in_zoom_process:
                    self.shared_data['is_zoom_process_active'] = True
                    in_zoom_process = True
                    self.shared_data['zoom_process_start_frame'] = frame_number
                    self.shared_data['zoom_process_magnifications'] = [scale]
                    self.shared_data['zoom_process_total_magnification'] = scale
                    self.shared_data['zoom_process_state'] = 'zooming'
                    self.shared_data['initial_zoom_feature_points'] = frozen_feature_points
                    self.shared_data['initial_zoom_descriptors'] = frozen_descriptors
                    self.shared_data['initial_zoom_coords'] = frozen_coords
                    self.shared_data['zoom_process_first_right_frame'] = frame_right.copy()
                    self.shared_data['shrink_stable_scale_checked'] = False
                    self.shared_data['zoom_prev_right_kp'] = current_right_kp
                    self.shared_data['zoom_prev_right_des'] = current_right_des

            self.shared_data['freeze_counter'] = freeze_counter
            self.shared_data['frozen_feature_points'] = frozen_feature_points
            self.shared_data['frozen_descriptors'] = frozen_descriptors
            self.shared_data['frozen_right_feature_points'] = frozen_right_feature_points
            self.shared_data['frozen_right_descriptors'] = frozen_right_descriptors
            self.shared_data['frozen_coords'] = frozen_coords
            self.shared_data['prev_right_kp'] = prev_right_kp
            self.shared_data['prev_right_des'] = prev_right_des


        # 处理放大检测过程（核心修改部分）
        elif in_zoom_process:
            # 检测左半边画面中的高亮区域
            # 1. 提取左半帧的G通道用于高亮检测（复用原有逻辑的通道选择）
            g_channel_left = frame_left[:, :, 1] if len(frame_left.shape) == 3 else frame_left
            # 2. 计算平均矩形面积（使用共享数据中已缓存的平均值）
            avg_rect_height = self.shared_data.get('avg_rect_height', 0)
            avg_rect_weight = self.shared_data.get('avg_rect_weight', 0)
            avg_rect_area = avg_rect_height * avg_rect_weight if avg_rect_height and avg_rect_weight else 1000  # fallback值

            # 3. 检测高亮区域轮廓
            bright_contours = detect_bright_regions(frame_left, 4 * avg_rect_area)

            # 4. 筛选出最接近左半边画面中心的高亮区域
            if bright_contours:
                # 计算左半边画面中心坐标
                h, w = frame_left.shape[:2]
                center_x, center_y = w // 2, h // 2

                min_distance = float('inf')
                central_bright_cnt = None
                central_bright_center = None

                for cnt in bright_contours:
                    # 计算高亮区域中心
                    M = cv2.moments(cnt)
                    if M["m00"] == 0:
                        continue  # 跳过面积为0的异常轮廓
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])

                    # 计算与画面中心的欧氏距离
                    distance = np.sqrt((cX - center_x) ** 2 + (cY - center_y) ** 2)

                    # 跟踪最近的高亮区域
                    if distance < min_distance:
                        min_distance = distance
                        central_bright_cnt = cnt
                        central_bright_center = (cX, cY)

                # 5. 绘制标签（使用与原有label相同的格式）
                if central_bright_center and hasattr(self,
                                                     'central_bright_label_cache') and self.central_bright_label_cache:
                    label = self.central_bright_label_cache
                    x1_center, y1_center = central_bright_center  # 斜线起点为高亮区域中心
                    h_left, w_left = frame_left.shape[:2]  # 获取左半画面的高和宽（关键：用于边界判断）

                    # 绘制边界框（围绕高亮区域）
                    x, y, w_cnt, h_cnt = cv2.boundingRect(central_bright_cnt)
                    cv2.rectangle(frame_left, (x, y), (x + w_cnt, y + h_cnt), (0, 255, 0), 2)

                    # 计算引导线参数（基础长度基于高亮区域宽度）
                    base_line_length = w_cnt // 3
                    diagonal_length = int(base_line_length * 1.3)  # 斜线长度

                    # 预先计算标签尺寸（用于判断边界）
                    font_size = 40
                    # 计算标签文本的宽高（使用put_chinese_text相同的字体设置）
                    # 这里通过临时PIL图像计算，确保与实际绘制尺寸一致
                    temp_img = Image.new('RGB', (1, 1))
                    temp_draw = ImageDraw.Draw(temp_img)
                    temp_font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), font_size)
                    text_width = temp_draw.textlength(label, font=temp_font)  # 文本宽度
                    bbox = temp_draw.textbbox((0, 0), label, font=temp_font)  # 边界框：(left, top, right, bottom)
                    text_height = bbox[3] - bbox[1]  # 高度 = bottom - top
                    # 标签实际绘制的边界（基于初始位置计算）
                    # 初始假设水平直线向右，标签在水平线上方
                    label_x_temp = x1_center + int(diagonal_length * np.cos(np.radians(45))) + (
                            base_line_length * 1.3 - text_width) // 2
                    label_y_temp = y1_center - int(diagonal_length * np.sin(np.radians(45))) - text_height - 28
                    # 标签最右端像素坐标（x轴最大值）
                    label_right = label_x_temp + text_width
                    # 标签最上端像素坐标（y轴最小值）
                    label_top = label_y_temp

                    # 根据标签位置与左半画面边界的关系，确定引导线方向
                    if label_right < w_left and label_top > 0:
                        # 情况1：标签在画面内（右不超界，上不超界）→ 右上45度斜线，水平向右
                        angle = 45
                        horizontal_dir = 1  # 1表示向右，-1表示向左
                    elif label_right >= w_left and label_top > 0:
                        # 情况2：标签右超界，上不超界 → 左上45度斜线，水平向左
                        angle = 135  # 135度 = 180-45，即向左上方45度
                        horizontal_dir = -1
                    elif label_right < w_left and label_top <= 0:
                        # 情况3：标签右不超界，上超界 → 右下45度斜线，水平向右
                        angle = -45  # 向下45度
                        horizontal_dir = 1
                    else:
                        # 情况4：标签右超界，上超界 → 左下45度斜线，水平向左
                        angle = -135  # 向左下方45度
                        horizontal_dir = -1

                    # 重新计算斜向引导线终点（基于确定的角度）
                    end_x_diag = int(x1_center + diagonal_length * np.cos(np.radians(angle)))
                    end_y_diag = int(y1_center - int(diagonal_length * np.sin(np.radians(angle))))  # 注意sin的符号由角度决定方向
                    cv2.line(frame_left, (x1_center, y1_center), (end_x_diag, end_y_diag), (0, 255, 0), 5)

                    # 计算水平引导线（基于方向调整长度和终点）
                    horizontal_length = text_width + 20  # 水平线段长度 = 文本宽 + 边距
                    end_x_horiz = int(end_x_diag + horizontal_dir * horizontal_length)  # 方向决定左右
                    cv2.line(frame_left, (end_x_diag, end_y_diag), (end_x_horiz, end_y_diag), (0, 255, 0), 5)

                    # 计算最终标签绘制位置（确保在水平线上方，文字从左到右）
                    if horizontal_dir == 1:
                        # 水平向右：标签左对齐于水平线段起点
                        label_x_zuobiao = end_x_diag + (horizontal_length - text_width) // 2
                    else:
                        # 水平向左：标签右对齐于水平线段终点（保证文字从左到右）
                        label_x_zuobiao = end_x_horiz + (horizontal_length - text_width) // 2
                    # 垂直位置始终在水平线上方（根据斜线方向微调，避免超界）
                    label_y = int(end_y_diag - text_height - 10)  # 10为额外边距
                    # 最终确保标签不超出画面上边界
                    label_y_zuobiao = max(0, label_y)

                    # 绘制中文标签（文字始终从左到右）
                    frame_left = put_chinese_text(
                        frame_left,
                        label,
                        (label_x_zuobiao, label_y_zuobiao),
                        font_size=font_size,
                        color=(0, 255, 0)
                    )

                    # 储存要检测的编号（保持原有逻辑）
                    position_match = re.search(r'(W\d+/Z\d+/L\d+)', label)
                    if position_match:
                        position_info = position_match.group(1)
                        if not hasattr(self, 'frame_position_map'):
                            self.frame_position_map = {}
                        self.frame_position_map[frame_number] = position_info

            zoom_process_state = self.shared_data.get('zoom_process_state')
            zoom_process_magnifications = self.shared_data.get('zoom_process_magnifications', [])
            zoom_process_total_magnification = self.shared_data.get('zoom_process_total_magnification', 1.0)
            zoom_start_frame = self.shared_data.get('zoom_process_start_frame')
            stage_counts = self.shared_data['stage_frame_counts']
            candidate_stages = self.shared_data['candidate_stages']
            confirmed_stages = self.shared_data['confirmed_stages']
            zoom_prev_right_kp = self.shared_data.get('zoom_prev_right_kp')
            zoom_prev_right_des = self.shared_data.get('zoom_prev_right_des')
            zoom_first_right_frame = self.shared_data.get('zoom_process_first_right_frame')
            shrink_stable_scale_checked = self.shared_data.get('shrink_stable_scale_checked', False)
            initial_zoom_kp = self.shared_data.get('initial_zoom_feature_points')
            initial_zoom_des = self.shared_data.get('initial_zoom_descriptors')

            if in_zoom_process and zoom_process_state is not None:
                state_map = {
                    'zooming': '放大',
                    'stable': '最大',
                    'shrinking': '缩小'
                }
                current_state = state_map[zoom_process_state]
                # 2. 判定普通卡顿状态（非放大过程但处于卡顿）
            elif (self.shared_data.get('is_freeze', False) or self.shared_data.get('freeze_counter', 0) >= 1):
                current_state = '普通卡顿'
                # 3. 其他情况为正常运行
            else:
                current_state = '正常运行'

            prev_state = self.shared_data['prev_state']
            if current_state != prev_state:
                # 更新共享数据中的状态记录
                self.shared_data['prev_state'] = current_state
                self.shared_data['current_state'] = current_state

            # 计算当前放大倍率（相邻帧特征点计算）（原有逻辑保持不变）
            gray_right = cv2.cvtColor(frame_right, cv2.COLOR_BGR2GRAY)
            gray_right = cv2.GaussianBlur(gray_right, (3, 3), 1.2)
            current_right_kp, current_right_des = extract_orb_features(gray_right, self.orb)

            scale = 1.0
            if (zoom_prev_right_kp is not None and zoom_prev_right_des is not None and
                    current_right_kp is not None and current_right_des is not None):
                matches = match_orb_features(zoom_prev_right_des, current_right_des, match_threshold=30.0)
                if matches is not None:
                    scale = calculate_magnification_from_matches(zoom_prev_right_kp, current_right_kp, matches) or 1.0

            # 更新上一帧特征为当前帧特征（原有逻辑保持不变）
            self.shared_data['zoom_prev_right_kp'] = current_right_kp
            self.shared_data['zoom_prev_right_des'] = current_right_des

            # 更新累积倍率（原有逻辑保持不变）
            zoom_process_total_magnification *= scale
            self.shared_data['zoom_process_total_magnification'] = zoom_process_total_magnification

            # 维护最近5帧的放大倍率（相邻帧计算的倍率）（原有逻辑保持不变）
            zoom_process_magnifications.append(scale)
            if len(zoom_process_magnifications) > 5:
                zoom_process_magnifications.pop(0)
            self.shared_data['zoom_process_magnifications'] = zoom_process_magnifications

            # 原逻辑：基于5帧倍率乘积判定；新逻辑：基于5帧中每帧倍率的范围判定
            new_state = None
            # 统计5帧中符合各阶段条件的帧数量
            zooming_frame_count = sum(1 for s in zoom_process_magnifications if s > 1.005)
            stable_frame_count = sum(1 for s in zoom_process_magnifications if 0.995 < s < 1.005)
            shrinking_frame_count = sum(1 for s in zoom_process_magnifications if s < 0.995)

            # 判定规则：连续5帧满足对应条件
            if zooming_frame_count == 5:
                new_state = 'zooming'
            elif stable_frame_count == 5:
                new_state = 'stable'
            elif shrinking_frame_count == 5:
                new_state = 'shrinking'
            # 若未满足连续5帧条件，保持当前状态（避免频繁切换）
            else:
                new_state = zoom_process_state if zoom_process_state is not None else 'stable'

            # 阶段持续帧计数更新（原有逻辑保持不变）
            if new_state == zoom_process_state:
                stage_counts[new_state] += 1
            else:
                if zoom_process_state is not None:
                    candidate_stages.append({
                        'start': frame_number - stage_counts[zoom_process_state],
                        'end': frame_number - 1,
                        'state': zoom_process_state,
                        'duration': stage_counts[zoom_process_state]
                    })
                stage_counts = {'zooming': 0, 'stable': 0, 'shrinking': 0}
                stage_counts[new_state] = 1

            # 检查状态转换有效性（原有逻辑保持不变）
            valid_transition = True
            if zoom_process_state == 'zooming' and new_state not in ['zooming', 'stable']:
                valid_transition = False
            elif zoom_process_state == 'stable' and new_state not in ['zooming', 'stable', 'shrinking']:
                valid_transition = False
            elif zoom_process_state == 'shrinking' and new_state not in ['stable', 'shrinking']:
                valid_transition = False

            # 处理缩小-稳定状态转换时的倍率检测（原有逻辑保持不变）
            if (zoom_process_state == 'shrinking' and new_state == 'stable' and not shrink_stable_scale_checked):
                if zoom_first_right_frame is not None:
                    stable_gray_right = cv2.cvtColor(frame_right, cv2.COLOR_BGR2GRAY)
                    stable_gray_right = cv2.GaussianBlur(stable_gray_right, (3, 3), 1.2)
                    stable_right_kp, stable_right_des = extract_orb_features(stable_gray_right, self.orb)
                    first_gray_right = cv2.cvtColor(zoom_first_right_frame, cv2.COLOR_BGR2GRAY)
                    first_gray_right = cv2.GaussianBlur(first_gray_right, (3, 3), 1.2)
                    first_right_kp, first_right_des = extract_orb_features(first_gray_right, self.orb)
                    match_count = 0  # 新增：统计特征匹配数
                    shrink_stable_scale = 1.0
                    if (first_right_kp is not None and first_right_des is not None and
                            stable_right_kp is not None and stable_right_des is not None):
                        matches = match_orb_features(first_right_des, stable_right_des, match_threshold=30.0)

                        if matches is not None:
                            shrink_stable_scale = calculate_magnification_from_matches(
                                first_right_kp, stable_right_kp, matches
                            ) or 1.0

                    # 仅在“缩小→稳定”转换后，执行原有倍率校验逻辑（满足则结束缩小）
                    if shrink_stable_scale < 1.04 and zoom_process_total_magnification < 1.07:
                        self.shared_data['is_zoom_process_active'] = False

                        current_left_kp, current_left_des = detect_features(frame_left)
                        movement = None
                        if (initial_zoom_kp is not None and initial_zoom_des is not None and
                                current_left_kp is not None and current_left_des is not None):
                            movement_result = calculate_movement(
                                initial_zoom_kp, initial_zoom_des,
                                current_left_kp, current_left_des
                            )
                            if movement_result is None:
                                # 处理特征匹配失败的情况
                                movement = None
                                src_pts = None
                                dst_pts = None
                            else:
                                movement, src_pts, dst_pts = movement_result

                        frozen_coords = self.shared_data.get('initial_zoom_coords')
                        corrected_coords = frozen_coords
                        if movement is not None and frozen_coords is not None:
                            corrected_coords = apply_movement(frozen_coords, movement)
                        self._confirm_valid_stages(candidate_stages, confirmed_stages)
                        # 重置放大检测相关共享数据
                        self.shared_data['zoom_process_state'] = None  # 清除放大检测状态
                        self.shared_data['zoom_process_start_frame'] = None  # 清除放大起始帧
                        self.shared_data['zoom_process_magnifications'] = []  # 清空倍率历史
                        self.shared_data['zoom_process_total_magnification'] = 1.0  # 重置累积倍率
                        self.shared_data['stage_frame_counts'] = {'zooming': 0, 'stable': 0, 'shrinking': 0}  # 重置阶段计数
                        self.shared_data['candidate_stages'] = []  # 清空候选阶段
                        self.shared_data['stable_phase_start_frame'] = None  # 清除稳定阶段起始帧
                        self.shared_data['stable_phase_end_frame'] = None  # 清除稳定阶段结束帧
                        self.shared_data['stable_phase_right_frames'] = []  # 清空稳定阶段帧缓存
                        self.shared_data['stable_phase_captured'] = False  # 重置稳定帧捕获标记
                        self.shared_data['zoom_process_first_right_frame'] = None  # 清除放大第一帧
                        self.shared_data['shrink_stable_scale_checked'] = False  # 重置缩小-稳定校验标记
                        # 5. 【核心新增】完全重置卡顿检测相关参数（恢复至卡顿前状态，可重新判断卡顿）
                        self.shared_data['freeze_counter'] = 0  # 重置卡顿计数器（关键：避免残留卡顿状态）
                        self.shared_data['frozen_feature_points'] = None  # 清除冻结特征点
                        self.shared_data['frozen_descriptors'] = None  # 清除冻结描述子
                        self.shared_data['frozen_right_feature_points'] = None  # 清除右侧冻结特征点
                        self.shared_data['frozen_right_descriptors'] = None  # 清除右侧冻结描述子
                        self.shared_data['frozen_coords'] = None  # 清除冻结坐标
                        self.shared_data['zoom_prev_right_kp'] = None  # 清除放大过程特征点缓存
                        self.shared_data['zoom_prev_right_des'] = None  # 清除放大过程描述子缓存
                        self.shared_data['initial_zoom_feature_points'] = None  # 清除初始放大特征点
                        self.shared_data['initial_zoom_descriptors'] = None  # 清除初始放大描述子
                        self.shared_data['initial_zoom_coords'] = None  # 清除初始放大坐标

                        # 6. 【核心新增】重置普通检测相关的辅助参数（确保重新进入普通检测时逻辑正常）
                        self.shared_data['zoom_state'] = None  # 清除 zoom_state 标记（避免误判 in_zoom_detection）
                        self.shared_data['zoom_history'] = []  # 清空 zoom 历史
                        self.shared_data['zoom_magnification_history'] = []  # 清空倍率历史
                        self.shared_data['zoom_start_frame'] = 0  # 重置 zoom 起始帧
                        self.shared_data['cached_zoom_frame'] = None  # 清除缓存 zoom 帧
                        self.shared_data['frozen_right_frame'] = None  # 清除冻结右侧帧

                        # 恢复坐标编号
                        if corrected_coords is not None:
                            current_coords['horizontal'] = corrected_coords['horizontal']
                            current_coords['vertical'] = corrected_coords['vertical']

                            horizontal_numbers, column_data, current_max_col, gap_types, contact_avg, aisle_avg, large_avg, dynamic_avg_h = get_horizontal_numbering_righttoleft(
                                all_rects,
                                prev_known_cols=column_data,
                                prev_max_known_col=prev_max_col,
                                prev_gap_types=gap_types,
                                prev_contact_avg_h=contact_avg,
                                prev_aisle_avg_h=aisle_avg,
                                prev_large_avg_h=large_avg,
                                prev_dynamic_avg_h=dynamic_avg_h  # 新增动态间隔参数
                            )
                            vertical_numbers, row_data, current_max_row, gap_types_v, contact_avg_v, aisle_avg_v, large_avg_v, dynamic_avg_v = get_vertical_numbering_bottomup(
                                all_rects,
                                prev_known_rows=row_data,
                                prev_max_known_row=prev_max_row,
                                prev_gap_types=gap_types_v,
                                prev_contact_avg_v=contact_avg_v,
                                prev_aisle_avg_v=aisle_avg_v,
                                prev_large_avg_v=large_avg_v,
                                prev_dynamic_avg_v=dynamic_avg_v  # 新增参数
                            )
                    # else:
                    # self.shared_data['shrink_stable_scale_checked'] = True

            if not valid_transition and not (zoom_process_state == 'shrinking' and new_state == 'stable'):
                self._confirm_valid_stages(candidate_stages, confirmed_stages)
                self.shared_data['zoom_process_state'] = None
                self.shared_data['zoom_process_start_frame'] = None
                self.shared_data['zoom_process_magnifications'] = []
                self.shared_data['zoom_process_total_magnification'] = 1.0
                self.shared_data['stage_frame_counts'] = {'zooming': 0, 'stable': 0, 'shrinking': 0}
                self.shared_data['candidate_stages'] = []
                self.shared_data['stable_phase_start_frame'] = None
                self.shared_data['stable_phase_end_frame'] = None
                self.shared_data['stable_phase_right_frames'] = []
                self.shared_data['stable_phase_captured'] = False
                self.shared_data['freeze_counter'] = 0
                self.shared_data['frozen_feature_points'] = None
                self.shared_data['frozen_descriptors'] = None
                self.shared_data['frozen_right_feature_points'] = None
                self.shared_data['frozen_right_descriptors'] = None
                self.shared_data['frozen_coords'] = None
                self.shared_data['zoom_prev_right_kp'] = None
                self.shared_data['zoom_prev_right_des'] = None
                self.shared_data['zoom_process_first_right_frame'] = None
                self.shared_data['shrink_stable_scale_checked'] = False

            else:
                if new_state == 'stable':
                    stable_right_frames = self.shared_data.get('stable_phase_right_frames', [])
                    stable_right_frames.append(frame_right.copy())
                    self.shared_data['stable_phase_right_frames'] = stable_right_frames

                self.shared_data['zoom_process_state'] = new_state
                self.shared_data['stage_frame_counts'] = stage_counts

                if new_state == 'shrinking':
                    stable_start = self.shared_data.get('stable_phase_start_frame')
                    stable_end = self.shared_data.get('stable_phase_end_frame')
                    stable_right_frames = self.shared_data.get('stable_phase_right_frames', [])
                    if stable_start and stable_end and not self.shared_data.get('stable_phase_captured', False):
                        if len(stable_right_frames) > 0:
                            mid_index = len(stable_right_frames) // 2
                            stable_frame_right = stable_right_frames[mid_index]
                            screenshot_path = f"zoom_stable_right_{stable_start}_to_{stable_end}.png"
                            cv2.imwrite(screenshot_path, stable_frame_right)
                            print(f"已保存稳定阶段右半边画面: {screenshot_path}")
                            self.shared_data['stable_phase_captured'] = True

        else:
            # 非卡顿状态重置（原有逻辑保持不变）
            freeze_counter = 0
            frozen_feature_points = None
            frozen_descriptors = None
            frozen_right_feature_points = None
            frozen_right_descriptors = None
            frozen_coords = None
            self.shared_data['is_zoom_process_active'] = False
            self.shared_data['zoom_state'] = None
            self.shared_data['zoom_history'] = []
            self.shared_data['zoom_magnification_history'] = []
            self.shared_data['zoom_start_frame'] = 0
            self.shared_data['cached_zoom_frame'] = None
            self.shared_data['frozen_right_frame'] = None
            self.shared_data['zoom_process_state'] = None
            self.shared_data['zoom_process_start_frame'] = None
            self.shared_data['zoom_process_magnifications'] = []
            self.shared_data['zoom_process_total_magnification'] = 1.0
            self.shared_data['stage_frame_counts'] = {'zooming': 0, 'stable': 0, 'shrinking': 0}
            self.shared_data['candidate_stages'] = []
            self.shared_data['confirmed_stages'] = []
            self.shared_data['zoom_process_first_right_frame'] = None
            self.shared_data['shrink_stable_scale_checked'] = False

            # 【核心新增】补充重置放大过程中的特征点缓存（避免残留影响普通检测）
            self.shared_data['zoom_prev_right_kp'] = None
            self.shared_data['zoom_prev_right_des'] = None
            self.shared_data['initial_zoom_feature_points'] = None
            self.shared_data['initial_zoom_descriptors'] = None
            self.shared_data['initial_zoom_coords'] = None

        # 更新共享数据（原有逻辑保持不变）
        self.shared_data['freeze_counter'] = freeze_counter
        self.shared_data['frozen_feature_points'] = frozen_feature_points
        self.shared_data['frozen_descriptors'] = frozen_descriptors
        self.shared_data['frozen_right_feature_points'] = frozen_right_feature_points
        self.shared_data['frozen_right_descriptors'] = frozen_right_descriptors
        self.shared_data['frozen_coords'] = frozen_coords
        self.shared_data['prev_coords'] = copy.deepcopy(current_coords)

        # 仅在非放大检测状态下更新编号相关共享数据（原有逻辑保持不变）
        if not in_zoom_detection and not in_zoom_process:
            self.shared_data['column_data'] = column_data
            self.shared_data['prev_max_col'] = current_max_col
            self.shared_data['row_data'] = row_data
            self.shared_data['prev_max_row'] = current_max_row
            self.shared_data['gap_types'] = gap_types
            self.shared_data['contact_avg'] = contact_avg
            self.shared_data['aisle_avg'] = aisle_avg
            self.shared_data['large_avg'] = large_avg
            self.shared_data['gap_types_v'] = gap_types_v
            self.shared_data['contact_avg_v'] = contact_avg_v
            self.shared_data['aisle_avg_v'] = aisle_avg_v
            self.shared_data['large_avg_v'] = large_avg_v
            self.shared_data['dynamic_avg_v'] = dynamic_avg_v
            self.shared_data['dynamic_avg_h'] = dynamic_avg_h

        # 绘制高亮区域轮廓（原有逻辑保持不变）
        if not in_zoom_detection and not in_zoom_process and bright_contours is not None and len(bright_contours) > 0:
            cv2.drawContours(frame_left, bright_contours, -1, (0, 255, 0), 2)

        # 绘制行列线（原有逻辑保持不变）
        if not in_zoom_detection and not in_zoom_process:
            column_data = self.shared_data.get('column_data', {})
            row_data = self.shared_data.get('row_data', {})
            avg_rect_height = self.shared_data.get('avg_rect_height', 0)
            avg_rect_weight = self.shared_data.get('avg_rect_weight', 0)

            if column_data:
                for col_num, col_x in column_data.items():
                    if col_num == 0:
                        continue
                    start_y = 0
                    end_y = frame_left.shape[0]
                    col_x = int(col_x)
                    # cv2.line(frame_left, (col_x, start_y), (col_x, end_y), (0, 255, 0), 2)
                    label = f"L{col_num}"
                    (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    # cv2.putText(frame_left, label, (col_x - text_width // 2, 30),
                    # cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            if row_data:
                for row_num, row_y in row_data.items():
                    if row_num == 0:
                        continue
                    start_x = 0
                    end_x = frame_left.shape[1]
                    row_y = int(row_y)
                    # cv2.line(frame_left, (start_x, row_y), (end_x, row_y), (0, 255, 0), 2)
                    label = f"H{row_num}"
                    (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    # cv2.putText(frame_left, label, (30, row_y + text_height // 2),
                    # cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # 计算高亮区编号（原有逻辑保持不变）
        region_numbers = []
        if not in_zoom_detection and not in_zoom_process and bright_contours and column_data and row_data:
            region_numbers = calculate_bright_region_numbers(
                bright_contours, column_data, row_data, avg_rect_height, avg_rect_weight)

            for number in region_numbers:
                if number not in number_frame_history:
                    number_frame_history[number] = [False] * 5
                number_frame_history[number][frame_key] = True
                current_sum = sum(number_frame_history[number])
                if current_sum >= 3:
                    if number not in delay_counters:
                        delay_counters[number] = 10

        # 构建编号-轮廓映射（原有逻辑保持不变）
        number_contour_map = defaultdict(list)
        if not in_zoom_detection and not in_zoom_process:
            for idx, number in enumerate(region_numbers):
                number_contour_map[number].append(bright_contours[idx])

        # 处理标签位置重叠及绘制（原有逻辑保持不变）
        label_positions = []
        if not in_zoom_detection and not in_zoom_process:
            for number, contours in number_contour_map.items():
                all_top_points = []
                for cnt in contours:
                    y_coords = cnt[:, :, 1]
                    min_y = np.min(y_coords)
                    x_coords = cnt[:, :, 0]
                    min_y_indices = np.where(y_coords == min_y)[0]
                    min_x = np.min(x_coords[min_y_indices])
                    all_top_points.append((min_x, min_y))
                if not all_top_points:
                    continue
                topmost_x, topmost_y = min(all_top_points, key=lambda p: p[1])
                label_positions.append((number, topmost_x, topmost_y))

        processed_positions = {}
        if not in_zoom_detection and not in_zoom_process:
            sorted_labels = sorted(label_positions, key=lambda item: (item[0][0], item[0][1]))
            for label in sorted_labels:
                number, x, y = label
                line_length = 40
                conflicting = False
                for other_number, (other_x, other_y, other_line_len) in processed_positions.items():
                    if number[0] == other_number[0]:
                        if abs(y - other_y) < 80:
                            line_length = max(line_length, abs(y - other_y) + 30)
                            conflicting = True
                processed_positions[number] = (x, y, line_length)

        if not in_zoom_detection and not in_zoom_process and bright_contours is not None and len(bright_contours) > 0:
            drawn_label_info = []
            for i, number in enumerate(region_numbers):
                if number not in processed_positions:
                    continue
                x, y, line_length = processed_positions[number]
                major_row, col_num = number
                if major_row == 0 or col_num == 0:
                    continue
                roof_id = self.shared_data["roof_info"].get('roof_id', "")
                label = f"热斑，W{roof_id}/Z{major_row}/L{col_num}"
                angle = 45
                diagonal_length = int(line_length * 1.3)
                end_x = x + int(diagonal_length * np.cos(np.radians(angle)))
                end_y = y - int(diagonal_length * np.sin(np.radians(angle)))
                cv2.line(frame_left, (x, y), (end_x, end_y), (0, 255, 0), 5)
                (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                horizontal_length = text_width + 20
                cv2.line(frame_left, (end_x, end_y), (end_x + horizontal_length, end_y), (0, 255, 0), 5)
                label_x = end_x + (horizontal_length - text_width) // 2
                label_y = end_y - text_height - 28
                frame_left = put_chinese_text(frame_left, label, (label_x, label_y), 40, (0, 255, 0))
                self.shared_data['label_history'][number] = (x, y, line_length, frame_number)

                # 关键：记录当前绘制的标签及其对应高亮区域的中心坐标（使用区域原始中心x,y）
                drawn_label_info.append({
                    'label': label,
                    'center': (x, y)  # x,y为高亮区域的中心坐标（与processed_positions一致）
                })

            if drawn_label_info:  # 确保有已绘制的标签
                # 计算左半边画面中心坐标
                frame_left_center = (frame_left.shape[1] // 2, frame_left.shape[0] // 2)
                min_distance = float('inf')
                closest_label = None

                for info in drawn_label_info:
                    # 计算当前标签对应区域中心与左半帧中心的欧氏距离
                    cx, cy = info['center']
                    distance = np.sqrt((cx - frame_left_center[0]) ** 2 + (cy - frame_left_center[1]) ** 2)

                    # 更新最近距离的标签
                    if distance < min_distance:
                        min_distance = distance
                        closest_label = info['label']

                # 记录到缓存（仅保留当前帧的最近标签）
                if closest_label:
                    self.central_bright_label_cache = closest_label

        # 补绘消失的标签（原有逻辑保持不变）
        if not in_zoom_detection and not in_zoom_process:
            current_valid_numbers = set(region_numbers)
            label_history = self.shared_data.get('label_history', {})
            to_remove = []
            for number, (x, y, line_length, last_frame) in label_history.items():
                major_row, col_num = number
                if major_row == 0 or col_num == 0:
                    continue
                if number not in current_valid_numbers and frame_number == last_frame + 1:
                    angle = 45
                    diagonal_length = int(line_length * 1.3)
                    end_x = x + int(diagonal_length * np.cos(np.radians(angle)))
                    end_y = y - int(diagonal_length * np.sin(np.radians(angle)))
                    cv2.line(frame_left, (x, y), (end_x, end_y), (0, 255, 0), 5)
                    roof_id = self.shared_data["roof_info"].get('roof_id', "")
                    label = f"热斑，W{roof_id}/Z{major_row}/L{col_num}"
                    (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                    horizontal_length = text_width + 20
                    cv2.line(frame_left, (end_x, end_y), (end_x + horizontal_length, end_y), (0, 255, 0), 5)
                    label_x = end_x + (horizontal_length - text_width) // 2
                    label_y = end_y - 28
                    frame_left = put_chinese_text(frame_left, label, (label_x, label_y), 40, (0, 255, 0))
                elif frame_number - last_frame > 2:
                    to_remove.append(number)
            for key in to_remove:
                del label_history[key]

        # 最终更新共享数据（原有逻辑保持不变）
        self.shared_data['number_frame_history'] = number_frame_history
        self.shared_data['screenshot_cache'] = screenshot_cache
        self.shared_data['delay_counters'] = delay_counters

        processed_frame = np.hstack((frame_left, frame_right))
        return processed_frame
