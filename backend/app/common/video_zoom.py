# 关于视频放大检测的所有方法

import cv2
import numpy as np

def init_orb_detector(max_features: int = 5000):
    """初始化ORB特征检测器"""
    return cv2.ORB_create(nfeatures=max_features)


def extract_orb_features(image, orb):
    """提取ORB特征点与描述子"""
    try:
        keypoints, descriptors = orb.detectAndCompute(image, None)
        # 检查是否有足够的有效特征点
        if descriptors is None or len(descriptors) < 10:
            return None, None
        return keypoints, descriptors
    except Exception as e:
        print(f"提取ORB特征时出错: {e}")
        return None, None


def match_orb_features(base_descriptors, target_descriptors, match_threshold):
    """匹配ORB特征并筛选高质量匹配对"""
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    try:
        matches = matcher.match(base_descriptors, target_descriptors)
        matches = sorted(matches, key=lambda x: x.distance)
        good_matches = [m for m in matches if m.distance < match_threshold]

        if len(good_matches) < 5:
            return None
        return good_matches
    except Exception:
        return None


def calculate_magnification_from_matches(base_key_points, target_key_points, good_matches):
    """根据匹配结果计算放大倍率"""
    try:
        base_points = np.float32([base_key_points[m.queryIdx].pt for m in good_matches])
        target_points = np.float32([target_key_points[m.trainIdx].pt for m in good_matches])

        base_distances = np.sqrt(np.sum((base_points[:-1] - base_points[1:]) ** 2, axis=1))
        target_distances = np.sqrt(np.sum((target_points[:-1] - target_points[1:]) ** 2, axis=1))

        valid_mask = (base_distances > 1e-6) & (target_distances > 1e-6)
        if not np.any(valid_mask):
            return None

        magnifications = target_distances[valid_mask] / base_distances[valid_mask]
        avg_magnification = np.median(magnifications)

        if 0.1 <= avg_magnification <= 10.0:
            return round(avg_magnification, 3)
        return None
    except Exception as e:
        print(f"计算放大倍数失败：{e}")
        return None