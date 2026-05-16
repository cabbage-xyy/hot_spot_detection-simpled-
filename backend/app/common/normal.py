# 通用的常用方法 比如保存word文件，使用中文字显示。。。等
# 通用库
import os
import sys
import math
import pathlib
import re
from datetime import datetime

import cv2
import numpy as np

# Word文档处理
from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT, WD_TABLE_ALIGNMENT
from docx.shared import Pt, Inches
from docx.oxml.ns import qn

# 图像处理
from PIL import Image, ImageDraw, ImageFont
# 进度条
from tqdm import tqdm
# PyTorch & YOLOv5 相关
import torch

from app.core.paths import BACKEND_DIR, OUTPUT_VIDEOS_DIR, REPORTS_DIR, WEIGHT_BEST_PATH
from app.models.yolo import Model
from app.utils.dataloaders import letterbox
from app.utils.general import non_max_suppression, check_img_size
from app.utils.torch_utils import select_device
from app.UI.sqlite_utils import *




global_normal_infos = {
    "db_result":"",
    "roof_info":"",
    "time_str":"",
    "unique_defects_set":""
}


# ========== Word报告保存路径辅助 ==========
def _safe_report_path_name(value, fallback="未填写"):
    text = str(value or fallback).strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text or fallback


def build_report_word_path(roof_info):
    finished_time = datetime.now()
    date_folder = finished_time.strftime("%Y-%m-%d")
    time_part = finished_time.strftime("%H%M%S")


    company_name = (
        roof_info.get("company_name")
        or roof_info.get("company")
        or roof_info.get("name")
        or "未知公司"
    )
    station_name = roof_info.get("station_name") or "未知电站"
    roof_name = roof_info.get("roof_name") or "未知屋顶"

    report_dir = (
        REPORTS_DIR
        / date_folder
        / _safe_report_path_name(company_name)
        / _safe_report_path_name(station_name)
    )
    report_dir.mkdir(parents=True, exist_ok=True)

    report_path = report_dir / f"{_safe_report_path_name(roof_name)}_{time_part}.docx"
    return str(report_path)


# ========== 报告正文信息处理辅助 ==========
def _report_text(value, fallback="未填写"):
    text = str(value or "").strip()
    return text or fallback


def normalize_report_roof_info(roof_info):
    """
    统一报告正文使用的屋顶信息。

    company_name / station_name / roof_name 来自前端当前选择，优先级最高。
    如果这些当前选择字段存在，说明本次报告是从页面选择链路进入的，
    station_address 不能继续盲目使用 SRT 里解析出的旧地址，避免出现
    “选择了电站s1，但报告里仍显示庄臣电站地址”的问题。
    """
    report_info = dict(roof_info or {})

    has_selected_context = bool(
        report_info.get("company_name")
        or report_info.get("station_name")
        or report_info.get("roof_name")
    )

    report_info["company_name"] = _report_text(
        report_info.get("company_name") or report_info.get("company") or report_info.get("name"),
        "未填写公司",
    )
    report_info["station_name"] = _report_text(report_info.get("station_name"), "未填写电站")
    report_info["roof_name"] = _report_text(report_info.get("roof_name"), "未填写屋顶")

    if has_selected_context:
        report_info["station_address"] = _report_text(
            report_info.get("selected_station_address")
            or report_info.get("station_address_from_db")
            or report_info.get("address_from_db"),
            "未填写",
        )
    else:
        report_info["station_address"] = _report_text(
            report_info.get("station_address") or report_info.get("address"),
            "未填写",
        )

    report_info["roof_number"] = _report_text(report_info.get("roof_number"), "未填写")
    report_info["size"] = _report_text(report_info.get("size"), "未填写")
    report_info["type"] = _report_text(report_info.get("type"), "未填写")
    report_info["person"] = _report_text(report_info.get("person") or report_info.get("people"), "未填写")
    report_info["weather"] = _report_text(report_info.get("weather"), "未填写")

    return report_info

 # 生成结尾的关于热斑信息的word文件
def save_to_word(unique_defects_set, word_filename, roof_info, date):

    roof_info = normalize_report_roof_info(roof_info)

    print("unique_defects_set", unique_defects_set)
    print("word_filename", word_filename)
    print("roof_info", roof_info)
    print("date", date)

    doc = Document()
    if not unique_defects_set:
        doc.add_heading("无检测结果", level=1).alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        doc.save(word_filename)
        print(f"已保存空报告至 {word_filename}")
        return []

    style = doc.styles['Normal']
    # 西文字体设为宋体的英文名称
    style.font.name = 'SimSun'
    # 中文字体强制设为宋体
    style._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    style.font.size = Pt(12)

    # 第一页标题
    title = doc.add_heading(level=0)
    title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    # 第一行标题：电站名称（一号、加粗）
    title_run1 = title.add_run(f"{roof_info['station_name']}\n")
    title_run1.font.name = 'SimSun'
    title_run1._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    title_run1.font.size = Pt(24)
    title_run1.font.bold = True

    # 第二行标题：红外无人机巡检（一号、加粗）
    title_run2 = title.add_run("光伏组件热斑多模态动态诊断与智能定位系统报告")
    title_run2.font.name = 'SimSun'
    title_run2._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    title_run2.font.size = Pt(24)
    title_run2.font.bold = True
    doc.add_paragraph("")  # 标题下方空行

    # 屋顶信息表格（三列布局，全居中）
    table = doc.add_table(rows=10, cols=2)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER  # 表格整体居中
    table.autofit = False
    table.allow_autofit = False

    initial_cell_height = Pt(18)# 竖直高度
    # 调整列宽（左侧2.5cm，中间2.5cm，右侧剩余宽度）
    table.columns[0].width = Inches(1.8)  # 左侧列宽（稍宽于4字）
    table.columns[1].width = Inches(4.2)  # 右侧列宽
    # 验证列宽设置
    # print(f"左列宽度：{table.columns[0].width}")
    # print(f"中列宽度：{table.columns[1].width}")
    # print(f"右列宽度：{table.columns[2].width}")

    # 所有单元格垂直+水平居中
    for row in table.rows:
        row.height = initial_cell_height
        row.height_rule = WD_ROW_HEIGHT.EXACTLY
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for p in cell.paragraphs:
                # 确保段落有运行对象
                if not p.runs:
                    p.add_run('')
                run = p.runs[0]
                run.font.name = 'SimSun'
                run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
                p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    # 处理缺陷集合，构建编号-缺陷类型映射
    defect_map = {}  # 键：编号（如W1/Z3/L6），值：缺陷类型列表
    parsed_codes = []  # 存储从缺陷集合中解析的有效编号（用于生成表格行）
    for item in unique_defects_set:
        # 分割“编号-缺陷类型”（仅按第一个"-"分割，支持缺陷类型含"-"）
        parts = item.split("-", 1)
        if len(parts) == 2:
            code, defect_type = parts
            parsed_codes.append(code)  # 记录有效编号
            # 构建缺陷类型列表（去重）
            if code in defect_map:
                if defect_type not in defect_map[code]:
                    defect_map[code].append(defect_type)
            else:
                defect_map[code] = [defect_type]

    parsed_codes = list(sorted(set(parsed_codes)))  # 去重+排序一步完成

    # 表格内容填充
    # 第1行：电站名字（合并左中列）
    table.cell(0, 0).text = "电站名称"  # 第一列
    run = table.cell(0, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(0, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(0, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(0, 1).text = roof_info['station_name']  # 第二列
    table.cell(0, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(0, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第2行：电站地址
    table.cell(1, 0).text = "电站地址"
    run = table.cell(1, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(1, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(1, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(1, 1).text = roof_info['station_address']
    table.cell(1, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(1, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第3行：屋顶个数
    table.cell(2, 0).text = "屋顶个数"
    run = table.cell(2, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(2, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(2, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(2, 1).text = str(roof_info['roof_number'])
    table.cell(2, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(2, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第4行：屋顶名字
    table.cell(3, 0).text = "屋顶名字"
    run = table.cell(3, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(3, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(3, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(3, 1).text = roof_info['roof_name']
    table.cell(3, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(3, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第5行：装机容量
    table.cell(4, 0).text = "装机容量"
    run = table.cell(4, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(4, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(4, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(4, 1).text = roof_info['size']
    table.cell(4, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(4, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第6行：组件类型
    table.cell(5, 0).text = "组件类型"
    run = table.cell(5, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(5, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(5, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(5, 1).text = roof_info['type']
    table.cell(5, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(5, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第7行：扫描时间
    table.cell(6, 0).text = "扫描时间"
    run = table.cell(6, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(6, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(6, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(6, 1).text = date
    table.cell(6, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(6, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第8行：扫描人员
    table.cell(7, 0).text = "扫描人员"
    run = table.cell(7, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(7, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(7, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(7, 1).text = roof_info['person']
    table.cell(7, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(7, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第9行：扫描天气
    table.cell(8, 0).text = "扫描天气"
    run = table.cell(8, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(8, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(8, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    table.cell(8, 1).text = roof_info['weather']
    table.cell(8, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(8, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 第10行：扫描结果
    table.cell(9, 0).text = "扫描结果"
    run = table.cell(9, 0).paragraphs[0].runs[0]
    run.font.bold = True
    table.cell(9, 0).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(9, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    dynamic_data = [item for item in unique_defects_set if item[:3] != (-10, -10, '上')]
    table.cell(9, 1).text = f"共检测到 {len(parsed_codes)} 个热斑组件"
    table.cell(9, 1).paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    table.cell(9, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    # 表格下方说明
    doc.add_paragraph("")  # 空行
    doc.add_paragraph("W：屋顶编号   Z：从南往北数阵列数   L：从东往西数块数", style='Normal')
    doc.add_paragraph("U：上方组件   D：下方组件", style='Normal')
    doc.add_paragraph("")  # 空行
    doc.add_page_break()  # 分页

    # 第二页及后续内容
    if parsed_codes:
        # 创建标题并设置字体为宋体
        heading = doc.add_heading(level=2)
        run = heading.add_run("热斑组件详情")
        run.font.name = 'SimSun'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

        detail_table = doc.add_table(rows=1, cols=4)
        detail_table.style = 'Table Grid'
        detail_table.autofit = False # 固定列宽

        # 定义中文字符宽度（根据实际字体和字号调整）
        char_width = Inches(0.35)  # 约等于四号字(15pt)下一个中文字符的宽度

        # 设置四列宽度（按字符数计算）
        detail_table.columns[0].width = Inches(char_width * 2.8)  # 第一列：3个字符宽
        detail_table.columns[1].width = Inches(char_width * 6.5)  # 第二列：7个字符宽
        detail_table.columns[2].width = Inches(char_width * 8)  # 第三列：5个字符宽
        detail_table.columns[3].width = Inches(char_width * 11.7)  # 第四列：12个字符宽

        # 验证总宽度是否超过页面可用范围
        section = doc.sections[0]
        page_width = section.page_width.inches
        left_margin = section.left_margin.inches
        right_margin = section.right_margin.inches
        available_width = page_width - left_margin - right_margin

        total_width = sum(col.width.inches for col in detail_table.columns)

        # 如果总宽度超过可用宽度，按比例缩小所有列宽
        if total_width > available_width:
            scale_factor = available_width / total_width
            for i in range(4):
                new_width = detail_table.columns[i].width.inches * scale_factor
                detail_table.columns[i].width = Inches(new_width)

            # print(f"警告：表格总宽度({total_width:.2f}英寸)超过页面可用宽度({available_width:.2f}英寸)")
            # print(f"已按比例({scale_factor:.2%})缩小所有列宽")

        # 表头设置（小三号字、加粗、居中）
        header_labels = ['序号', '红外图像编号', '缺陷类型', '缺陷位置坐标']
        hdr_cells = detail_table.rows[0].cells
        for i, label in enumerate(header_labels):
            cell = hdr_cells[i]
            cell.text = label
            run = cell.paragraphs[0].runs[0]
            run.font.name = 'SimSun'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            run.font.size = Pt(14)
            run.font.bold = True
            cell.paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

        # 若没有有效缺陷数据，返回空列表
        if not parsed_codes:
            return []

        # 填充表格内容
        for idx, code in enumerate(parsed_codes, start=0):
            # 解析编号（格式：W{roof_id}/Z{major_row}/L{col_num}）
            code_parts = code.split("/")
            if len(code_parts) == 3:
                # 提取屋顶ID、组号、列号（去除前缀字母）
                roof_id = code_parts[0][1:] if code_parts[0].startswith('W') else code_parts[0]
                major_row = code_parts[1][1:] if code_parts[1].startswith('Z') else code_parts[1]
                col_num = code_parts[2][1:] if code_parts[2].startswith('L') else code_parts[2]
            else:
                # 格式异常时的默认值
                roof_id, major_row, col_num = "未知", "未知", "未知"

            # 添加新行并填充内容
            row_cells = detail_table.add_row().cells

            for cell in row_cells:
                # 确保段落有运行对象
                if not cell.paragraphs[0].runs:
                    cell.paragraphs[0].add_run('')
                run = cell.paragraphs[0].runs[0]
                run.font.name = 'SimSun'
                run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
                cell.paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER  # 按需设置对齐方式

            # 序号（格式化为001、002...）
            row_cells[0].text = f"{idx + 1:03d}"
            row_cells[0].paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

            # 红外图像编号
            row_cells[1].text = code
            row_cells[1].paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

            # 缺陷类型（固定为"热斑"）
            if code in defect_map:
                # 同一个编号下的热斑缺陷都放在一起 用/隔开
                row_cells[2].text = "/".join(defect_map[code])  # 如"组件破碎/裂纹"
            else:
                row_cells[2].text = "无缺陷"
            row_cells[2].paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

            # 缺陷位置坐标
            row_cells[3].text = f"{roof_id}号屋顶，第{major_row}组，第{col_num}列"
            row_cells[3].paragraphs[0].alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    else:
        doc.add_paragraph("未检测到热斑组件。")

    doc.save(word_filename)

# 单位转换，pt到像素
def pt_to_px(pt, dpi=300):
    return int((pt * dpi) / 72)

# 单位转换，英寸到像素
def inches_to_px(inches, dpi=300):
    return int(inches * dpi)

# 电站信息页
# 计算图片尺寸（A4纸大小：210mm x 297mm），297*3/4=222.75
# 放大图片，只显示上面的3/4
# 电站信息页
def generate_first_page(data,roof_info, time_str, dpi=300):
    roof_info = normalize_report_roof_info(roof_info)
    # 计算图片尺寸（A4纸大小：210mm x 297mm），297*3/4=222.75
    # 放大图片，只显示上面的3/4
    width_mm, height_mm = 210, 223
    width_px = int(width_mm * dpi / 25.4)
    height_px = int(height_mm * dpi / 25.4)

    # 创建空白图像（白色背景）
    img = np.ones((height_px, width_px, 3), dtype=np.uint8) * 255

    # 标题文本
    title1 = roof_info.get("station_name", "station_name")
    title2 = "光伏组件热斑多模态动态诊断与智能定位系统"
    title3 = "报告"

    # 标题字体大小(pt)和位置
    title_font_size = 24  # 增大标题字体
    title_margin_top = pt_to_px(24)  # 距离上边缘24pt

    # 计算标题位置（居中）
    title_px = pt_to_px(title_font_size)

    # 确保标题是字符串类型
    title1 = str(title1)
    title2 = str(title2)
    title3 = str(title3)

    # 尝试计算标题文本宽度
    title1_width, title2_width, title2_width = 0, 0, 0

    try:
        # 使用PIL精确计算文本宽度
        img_pil = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(img_pil)
        font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), title_px)
        title1_width = draw.textlength(title1, font=font)
        title2_width = draw.textlength(title2, font=font)
        title3_width = draw.textlength(title3, font=font)
    except Exception as e:
        # 计算失败时使用默认估计值
        title1_width = len(title1) * title_px * 0.6
        title2_width = len(title2) * title_px * 0.6
        title3_width = len(title3) * title_px * 0.6

    # 水平居中计算
    title1_x = max(0, int((width_px - title1_width) // 2))
    title1_y = title_margin_top + title_px // 2

    title2_x = max(0, int((width_px - title2_width) // 2))
    title2_y = title1_y + title_px + 10  # 标题1下方

    title3_x = max(0, int((width_px - title3_width) // 2))
    title3_y = title2_y + title_px + 10  # 标题2下方

    # 绘制标题（确保居中）
    img = put_chinese_text(img, title1, (title1_x, title1_y), title_font_size * 4, (0, 0, 0))
    img = put_chinese_text(img, title2, (title2_x, title2_y), title_font_size * 4, (0, 0, 0))
    img = put_chinese_text(img, title3, (title3_x, title3_y), title_font_size * 4, (0, 0, 0))

    # 表格参数（调整列宽比例）
    table_rows, table_cols = 10, 2
    table_margin_top = pt_to_px(48)  # 标题下方边距增加
    cell_height = pt_to_px(18)  # 每格高度18pt

    # 调整列宽比例，保持表格整体居中
    table_total_width = inches_to_px(6.0)  # 表格总宽度
    col1_width = int(table_total_width * 0.3)  # 左侧列宽占30%
    col2_width = table_total_width - col1_width  # 右侧列宽占70%

    # 计算表格水平居中位置
    table_left_margin = (width_px - table_total_width) // 2

    # 计算表格垂直位置
    table_y = title3_y + table_margin_top
    table_height = table_rows * cell_height

    # 绘制表格边框（使用居中后的坐标）
    for row in range(table_rows + 1):  # +1 绘制底部边框
        y = table_y + row * cell_height
        cv2.line(img, (table_left_margin, y),
                 (table_left_margin + table_total_width, y), (0, 0, 0), 2)  # 水平线

    for col in range(table_cols + 1):  # +1 绘制右侧边框
        x = table_left_margin + (col1_width if col == 1 else 0 if col == 0 else table_total_width)
        cv2.line(img, (x, table_y), (x, table_y + table_height), (0, 0, 0), 2)  # 垂直线

    # 表格标签内容
    table_labels = [
        ("电站名称", "station_name"),
        ("电站地址", "station_address"),
        ("屋顶个数", "roof_number"),
        ("屋顶名字", "roof_name"),
        ("装机容量", "size"),
        ("组件类型", "type"),
        ("扫描时间", "date"),
        ("扫描人员", "person"),
        ("扫描天气", "weather"),
        ("扫描结果", "hot_spot_count")
    ]

    # 表格字体大小(pt)
    left_font_size = 12  # 左侧标签字体大小
    right_font_size = 12  # 右侧内容字体大小


    # 绘制表格内容（使用居中后的坐标）
    for row, (label, key) in enumerate(table_labels):
        for col in range(table_cols):
            x1 = table_left_margin + (0 if col == 0 else col1_width)
            y1 = table_y + row * cell_height
            x2 = x1 + (col1_width if col == 0 else col2_width)
            y2 = y1 + cell_height

            # 文本内容
            if col == 0:
                text = label  # 第一列内容固定
            else:
                if key == "date":
                    text = time_str
                elif key == "hot_spot_count":
                    hot_spot_count = [item for item in data if item[:3] != (-10, -10, '上')]
                    print("hot_spot_count的默认内容",hot_spot_count)
                    spot_codes = []
                    for spot in hot_spot_count:
                        # 确保元素是字符串且包含-，才提取编号，否则跳过（兼容异常数据）
                        if isinstance(spot, str) and "-" in spot:
                            code = spot.split("-")[0].strip()  # strip()去除编号前后空格
                            spot_codes.append(code)
                    # 3. 重新赋值文本，展示去重后的编号数量
                    print(f"总共检测到热斑的形式有哪些{hot_spot_count}")
                    text = f"共检测到 {len(set(spot_codes))} 个热斑"
                else:
                    # 确保文本是字符串类型
                    text = label if col == 0 else str(roof_info.get(key, "未知"))

            # 字体大小
            font_size = left_font_size if col == 0 else right_font_size

            # 计算文本位置（居中）
            font_px = pt_to_px(font_size)

            # 尝试计算文本宽度
            text_width = 0
            try:
                img_pil = Image.new('RGB', (1, 1))
                draw = ImageDraw.Draw(img_pil)
                font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), font_px)
                text_width = draw.textlength(text, font=font)
            except:
                text_width = len(text) * font_px * 0.6

            text_x = x1 + (x2 - x1 - text_width) // 2
            text_y = y1 + (y2 - y1) // 2 - font_px // 4  # 微调垂直位置

            # 绘制文本
            img = put_chinese_text(img, text, (text_x, text_y), font_px, (0, 0, 0))

    # 标注标签
    note1 = "W：屋顶编号   Z：从南往北数阵列数   L：从东往西数列数"
    note2 = "U：上方组件   D：下方组件"

    note_font_size = 12

    # 计算标注位置（居中）
    note_y = table_y + table_height + pt_to_px(24)  # 表格下方24pt

    # 计算标注文本宽度
    note_width = 0
    try:
        img_pil = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(img_pil)
        font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), pt_to_px(note_font_size))
        note_width = max(draw.textlength(note1, font=font), draw.textlength(note2, font=font))
    except:
        note_width = max(len(note1), len(note2)) * pt_to_px(note_font_size) * 0.6

    note_x = (width_px - note_width) // 2

    # 绘制标注
    img = put_chinese_text(img, note1, (note_x, note_y), pt_to_px(note_font_size), (0, 0, 0))
    img = put_chinese_text(img, note2, (note_x, note_y + pt_to_px(12) + 3),
                           pt_to_px(note_font_size), (0, 0, 0))

    return img

# 具体检测页
def generate_detail_pages(unique_defects_set, dpi=300):
    # 计算图片尺寸（A4纸大小：210mm x 297mm），297*3/4=222.75
    # 放大图片，只显示上面的3/4
    width_mm, height_mm = 210, 223
    width_px = int(width_mm * dpi / 25.4)
    height_px = int(height_mm * dpi / 25.4)

    # 处理缺陷集合，构建编号-缺陷类型映射
    defect_map = {}  # 键：编号（如W1/Z3/L6），值：缺陷类型列表
    parsed_codes = []  # 存储从缺陷集合中解析的有效编号（用于生成表格行）
    for item in unique_defects_set:
        # 分割“编号-缺陷类型”（仅按第一个"-"分割，支持缺陷类型含"-"）
        parts = item.split("-", 1)
        if len(parts) == 2:
            code, defect_type = parts
            parsed_codes.append(code)  # 记录有效编号
            # 构建缺陷类型列表（去重）
            if code in defect_map:
                if defect_type not in defect_map[code]:
                    defect_map[code].append(defect_type)
            else:
                defect_map[code] = [defect_type]

    parsed_codes = list(sorted(set(parsed_codes)))  # 去重+排序一步完成

    # 若没有有效缺陷数据，返回空列表
    if not parsed_codes:
        return []

    # 每页行数
    rows_per_page = 30

    # 计算需要的页数
    total_pages = math.ceil(len(parsed_codes) / rows_per_page)

    # 表格参数
    col_widths = [
        inches_to_px(0.98),  # 第一列宽度
        inches_to_px(2),  # 第二列宽度
        inches_to_px(1.5),  # 第三列宽度
        inches_to_px(3.5)  # 第四列宽度
    ]
    table_total_width = sum(col_widths)
    cell_height = pt_to_px(18)  # 每格高度18pt
    table_margin_top = pt_to_px(24)  # 顶部边距

    # 标题字体和大小
    title_font_size = 13
    # 表格内容字体
    content_font_size = 12
    page_num_font_size = pt_to_px(8, dpi)  # 页码字体大小

    # 生成所有页
    pages = []
    for page_num in range(total_pages):
        # 创建新页面
        img = np.ones((height_px, width_px, 3), dtype=np.uint8) * 255

        # 标题文本
        title = "热斑组件详情"

        # 计算标题位置（居中）
        title_px = pt_to_px(title_font_size)

        # 确保标题是字符串类型
        title = str(title)

        # 计算标题文本宽度
        title_width = 0
        try:
            img_pil = Image.new('RGB', (1, 1))
            draw = ImageDraw.Draw(img_pil)
            font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), title_px)
            title_width = draw.textlength(title, font=font)
        except:
            title_width = len(title) * title_px * 0.6

        title_x = (width_px - title_width) // 2
        title_y = table_margin_top + title_px // 2

        # 绘制标题
        img = put_chinese_text(img, title, (title_x, title_y), title_px, (0, 0, 0))

        # 计算表格水平居中位置
        table_left_margin = (width_px - table_total_width) // 2

        # 计算表格垂直位置
        table_y = title_y + pt_to_px(12)  # 标题下方12pt

        # 计算当前页的数据范围
        start_idx = page_num * rows_per_page
        end_idx = min(start_idx + rows_per_page, len(parsed_codes))
        current_page_codes = parsed_codes[start_idx:end_idx]

        # 表格行数（包括标题行）
        table_rows = len(current_page_codes) + 1

        # 绘制表格边框（使用居中后的坐标）
        for row in range(table_rows + 1):  # +1 绘制底部边框
            y = table_y + row * cell_height
            cv2.line(img, (table_left_margin, y),
                     (table_left_margin + table_total_width, y), (0, 0, 0), 2)  # 水平线

        for col in range(5):  # 5条垂直线（4列）
            x = table_left_margin + sum(col_widths[:col])
            cv2.line(img, (x, table_y), (x, table_y + table_rows * cell_height), (0, 0, 0), 2)  # 垂直线

        # 表格标题行
        header = ['序号', '红外图像编号', '缺陷类型', '缺陷位置坐标']

        # 绘制标题行（使用居中后的坐标）
        for col_idx, text in enumerate(header):
            x1 = table_left_margin + sum(col_widths[:col_idx])
            y1 = table_y
            x2 = x1 + col_widths[col_idx]
            y2 = y1 + cell_height

            # 确保文本是字符串类型
            text = str(text)

            # 计算文本位置（居中）
            font_px = pt_to_px(content_font_size)

            # 计算文本宽度
            text_width = 0
            try:
                img_pil = Image.new('RGB', (1, 1))
                draw = ImageDraw.Draw(img_pil)
                font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), font_px)
                text_width = draw.textlength(text, font=font)
            except:
                text_width = len(text) * font_px * 0.6

            text_x = x1 + (x2 - x1 - text_width) // 2
            text_y = y1 + (y2 - y1) // 2 - font_px // 4  # 微调垂直位置

            # 绘制文本
            img = put_chinese_text(img, text, (text_x, text_y), font_px, (0, 0, 0))

        # 绘制数据行（使用居中后的坐标）
        for row_idx, code in enumerate(current_page_codes):
            # 解析编号（格式：W{roof_id}/Z{major_row}/L{col_num}）
            code_parts = code.split("/")
            if len(code_parts) == 3:
                # 提取屋顶ID、组号、列号（去除前缀字母）
                roof_id = code_parts[0][1:] if code_parts[0].startswith('W') else code_parts[0]
                major_row = code_parts[1][1:] if code_parts[1].startswith('Z') else code_parts[1]
                col_num = code_parts[2][1:] if code_parts[2].startswith('L') else code_parts[2]
            else:
                # 格式异常时的默认值
                roof_id, major_row, col_num = "未知", "未知", "未知"

            # 1. 序号（全局连续编号，补零至3位）
            col1_text = f"{start_idx + row_idx + 1:03d}"

            # 2. 红外图像编号（直接使用解析出的完整编号）
            col2_text = code

            # 3. 缺陷类型（去重合并）
            if code in defect_map:
                col3_text = "/".join(defect_map[code])  # 如"组件破碎/裂纹"
            else:
                col3_text = "无缺陷"

            # 4. 缺陷位置坐标
            col4_text = f"{roof_id}号屋顶，第{major_row}组，第{col_num}列"

            # 绘制当前行的4列数据
            row_data = [col1_text, col2_text, col3_text, col4_text]
            for col_idx, text in enumerate(row_data):
                x1 = table_left_margin + sum(col_widths[:col_idx])
                y1 = table_y + (row_idx + 1) * cell_height  # +1 跳过标题行
                x2 = x1 + col_widths[col_idx]
                y2 = y1 + cell_height
                # 确保文本是字符串类型
                text = str(text)

                # 计算文本位置（居中）
                font_px = pt_to_px(content_font_size)

                # 计算文本居中位置
                try:
                    img_pil = Image.new('RGB', (1, 1))
                    draw = ImageDraw.Draw(img_pil)
                    font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), font_px)
                    text_width = draw.textlength(text, font=font)
                except:
                    text_width = len(text) * font_px * 0.6
                text_x = x1 + (x2 - x1 - text_width) // 2
                text_y = y1 + (y2 - y1) // 2 - font_px // 4

                img = put_chinese_text(img, text, (text_x, text_y), font_px, (0, 0, 0))

        # 添加页码（居中）
        page_num_text = f"第 {page_num + 1} 页，共 {total_pages} 页"
        page_num_y = height_px - pt_to_px(12)  # 底部边距
        page_num_px = pt_to_px(8)

        # 计算页码文本宽度
        page_num_width = 0
        try:
            img_pil = Image.new('RGB', (1, 1))
            draw = ImageDraw.Draw(img_pil)
            font = ImageFont.truetype(str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"), page_num_px)
            page_num_width = draw.textlength(page_num_text, font=font)
        except:
            page_num_width = len(page_num_text) * page_num_px * 0.6

        page_num_x = (width_px - page_num_width) // 2

        img = put_chinese_text(img, page_num_text, (page_num_x, page_num_y), page_num_px, (0, 0, 0))

        pages.append(img)

    return pages

# 插入截图到视频末尾,30帧
def insert_cached_images_to_video(video_writer, image_cache, fps, frames_per_image=45, transition_frames=15):
    if not video_writer or not video_writer.isOpened():
        print("错误：视频写入器未初始化或已关闭")
        return

    # 视频固定尺寸
    VIDEO_WIDTH, VIDEO_HEIGHT = 1920, 1080

    success_count = 0
    prev_frame = None

    for i, img_info in enumerate(image_cache):
        try:
            img_cv = None
            # 检查img_info类型
            if isinstance(img_info, dict):
                # 字典格式：尝试获取PIL图像
                pil_img = img_info.get('pil_image')
                page_num = img_info.get('page_number', i + 1)
            elif isinstance(img_info, np.ndarray):
                # NumPy数组格式：直接使用
                pil_img = None
                img_cv = img_info
                page_num = i + 1
            else:
                print(f"警告：第{i + 1}张图片格式不支持，类型: {type(img_info)}")
                continue

            # 如果是PIL图像，转换为OpenCV格式
            if pil_img:
                # 打印PIL图像尺寸信息
                pil_width, pil_height = pil_img.size
                img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            elif 'img_cv' not in locals():
                print(f"警告：第{page_num}张图片数据缺失")
                continue

            # 获取图片尺寸
            img_height, img_width = img_cv.shape[:2]

            # 计算保持长宽比的缩放尺寸
            img_ratio = img_width / img_height
            video_ratio = VIDEO_WIDTH / VIDEO_HEIGHT

            if img_ratio > video_ratio:
                # 图片比视频宽，以宽度为基准缩放
                new_width = VIDEO_WIDTH
                new_height = int(VIDEO_WIDTH / img_ratio)
            else:
                # 图片比视频高，以高度为基准缩放
                new_height = VIDEO_HEIGHT
                new_width = int(VIDEO_HEIGHT * img_ratio)

            # 缩放图片
            img_scaled = cv2.resize(img_cv, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)

            # 创建黑色背景
            current_frame = np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8)

            # 计算居中位置
            x_offset = (VIDEO_WIDTH - new_width) // 2
            y_offset = (VIDEO_HEIGHT - new_height) // 2

            # 将缩放后的图片放置在黑色背景上
            current_frame[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = img_scaled

            # 如果不是第一张图片，创建翻页过渡效果
            if prev_frame is not None:
                for t in range(transition_frames):
                    progress = t / transition_frames
                    transition_frame = create_page_turn_effect(prev_frame, current_frame, progress)
                    if video_writer.isOpened():
                        video_writer.write(transition_frame)
                    else:
                        print(f"错误：写入过渡帧 {t+1}/{transition_frames} 时视频写入器已关闭")
                        break

            # 写入当前图片的静态帧
            for frame_idx in range(frames_per_image):
                if video_writer.isOpened():
                    video_writer.write(current_frame)
                else:
                    print(f"错误：写入第{frame_idx + 1}帧时视频写入器已关闭")
                    break

            prev_frame = current_frame
            success_count += 1

        except Exception as e:
            page_num = i + 1  # 默认页码
            print(f"插入第{page_num}页图片失败: {str(e)}")
            # 打印详细的错误堆栈
            import traceback
            print(traceback.format_exc())

# TODO 这个地方进行修改 就是只要报告图和一张对应位置左右两边的框线
# 目前的思路就是报告图和所有截出来的都放在一起 然后报告图放在前面 后面的按照帧数依次加到后面
def create_page_turn_effect1(prev_frame, next_frame, progress):
    """
    从右向左翻页过渡
    progress: 0.0 ~ 1.0
    """
    height, width = prev_frame.shape[:2]
    result = np.zeros_like(prev_frame)

    center_x = width - int(width * progress * 0.8)
    curl_width = max(1, int(width * 0.2 * (1 - progress)))

    for y in range(height):
        for x in range(width):
            dist_to_center = x - center_x

            if dist_to_center < -curl_width:
                result[y, x] = prev_frame[y, x]
            elif dist_to_center > curl_width:
                result[y, x] = next_frame[y, x]
            else:
                normalized_dist = dist_to_center / curl_width
                angle = normalized_dist * np.pi / 2
                curl_x = center_x + int(curl_width * np.cos(angle))
                next_x = x - 2 * curl_width

                if 0 <= next_x < width:
                    result[y, x] = next_frame[y, next_x]
                else:
                    curl_x = max(0, min(width - 1, curl_x))
                    result[y, x] = prev_frame[y, curl_x]

    shadow_mask = np.ones((height, width), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            dist_to_center = x - center_x
            if -curl_width <= dist_to_center <= curl_width:
                shadow_intensity = 0.3 * (1 - np.cos((dist_to_center / curl_width) * np.pi / 2))
                shadow_mask[y, x] = 1 - shadow_intensity

    result = result.astype(np.float32)
    result[:, :, 0] *= shadow_mask
    result[:, :, 1] *= shadow_mask
    result[:, :, 2] *= shadow_mask
    result = np.clip(result, 0, 255).astype(np.uint8)

    highlight_width = max(1, int(curl_width * 0.2))
    for y in range(height):
        for x in range(max(0, center_x - curl_width), min(width, center_x + curl_width)):
            dist = x - (center_x - curl_width)
            if dist < highlight_width:
                highlight = int(25 * (1 - dist / highlight_width))
                result[y, x] = np.clip(result[y, x] + highlight, 0, 255)

    return result
# 将报告图片格式转变为视频格式
def images_to_video(output_video_path, image_cache, fps):
    """
    把 image_cache 里的图片生成一个 mp4 视频

    参数:
        output_video_path: 输出视频路径，例如 "./output_videos/report_video.mp4"
        image_cache: 图片列表，支持:
            1) np.ndarray
            2) {"pil_image": PIL.Image, "page_number": 1}
        fps: 输出视频帧率，例如 25 或 30
    """
    if not image_cache:
        print("错误：image_cache 为空，无法生成视频")
        return False

    video_width = 1920
    video_height = 1080
    frames_per_image = 45
    transition_frames = 15

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    video_writer = cv2.VideoWriter(
        output_video_path,
        fourcc,
        fps,
        (video_width, video_height)
    )

    if not video_writer.isOpened():
        print(f"错误：无法创建视频文件 {output_video_path}")
        return False

    prev_frame = None
    success_count = 0

    for i, img_info in enumerate(image_cache):
        try:
            img_cv = None
            page_num = i + 1

            if isinstance(img_info, dict):
                pil_img = img_info.get("pil_image")
                page_num = img_info.get("page_number", i + 1)
                if pil_img is not None:
                    img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

            elif isinstance(img_info, np.ndarray):
                img_cv = img_info

            else:
                print(f"警告：第{i + 1}张图片格式不支持，类型: {type(img_info)}")
                continue

            if img_cv is None:
                print(f"警告：第{page_num}张图片数据为空")
                continue

            img_height, img_width = img_cv.shape[:2]
            img_ratio = img_width / img_height
            video_ratio = video_width / video_height

            if img_ratio > video_ratio:
                new_width = video_width
                new_height = int(video_width / img_ratio)
            else:
                new_height = video_height
                new_width = int(video_height * img_ratio)

            img_scaled = cv2.resize(
                img_cv,
                (new_width, new_height),
                interpolation=cv2.INTER_LANCZOS4
            )

            current_frame = np.zeros((video_height, video_width, 3), dtype=np.uint8)

            x_offset = (video_width - new_width) // 2
            y_offset = (video_height - new_height) // 2
            current_frame[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = img_scaled

            if prev_frame is not None:
                for t in range(transition_frames):
                    progress = t / transition_frames
                    transition_frame = create_page_turn_effect1(prev_frame, current_frame, progress)
                    video_writer.write(transition_frame)

            for _ in range(frames_per_image):
                video_writer.write(current_frame)

            prev_frame = current_frame
            success_count += 1
            print(f"已写入第 {page_num} 张图片")

        except Exception as e:
            print(f"插入第{i + 1}张图片失败: {str(e)}")
            import traceback
            print(traceback.format_exc())

    video_writer.release()
    print(f"报告视频生成完成：{output_video_path}，共写入 {success_count} 张图片")
    return True
# 在上面报告图片视频后面再追加对应的热斑图片
def append_images_to_video(input_video_path, output_video_path, image_cache, fps=30):
    """
    把 image_cache 中的图片追加到 input_video_path 对应视频末尾，输出为一个新视频

    参数:
        input_video_path: 原视频路径
        output_video_path: 输出新视频路径
        image_cache: 图片列表，元素支持:
            1) np.ndarray
            2) {"pil_image": PIL.Image, "page_number": 1}
        fps: 可选。不传就沿用原视频fps
    """
    if not os.path.exists(input_video_path):
        print(f"错误：输入视频不存在 -> {input_video_path}")
        return False

    if not image_cache:
        print("错误：image_cache 为空，无法追加图片")
        return False

    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        print(f"错误：无法打开输入视频 -> {input_video_path}")
        return False

    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = src_fps if src_fps > 0 else 30

        video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(f"原视频尺寸: {video_width}x{video_height}")
        print(f"原视频帧率: {fps}")
        print(f"原视频总帧数: {total_frames}")

        os.makedirs(os.path.dirname(output_video_path) or ".", exist_ok=True)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(
            output_video_path,
            fourcc,
            fps,
            (video_width, video_height)
        )

        if not writer.isOpened():
            print(f"错误：无法创建输出视频 -> {output_video_path}")
            return False

        try:
            # 1. 先写入原视频所有帧
            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                writer.write(frame)
                frame_idx += 1

            print(f"原视频帧写入完成，共写入 {frame_idx} 帧")

            # 2. 再写入图片段
            frames_per_image = 45
            transition_frames = 15
            prev_frame = None
            success_count = 0

            for i, img_info in enumerate(image_cache):
                try:
                    img_cv = None
                    page_num = i + 1

                    if isinstance(img_info, dict):
                        pil_img = img_info.get("pil_image")
                        page_num = img_info.get("page_number", i + 1)
                        if pil_img is not None:
                            img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

                    elif isinstance(img_info, np.ndarray):
                        img_cv = img_info

                    else:
                        print(f"警告：第{i + 1}张图片格式不支持，类型: {type(img_info)}")
                        continue

                    if img_cv is None:
                        print(f"警告：第{page_num}张图片数据为空")
                        continue

                    img_height, img_width = img_cv.shape[:2]
                    img_ratio = img_width / img_height
                    video_ratio = video_width / video_height

                    if img_ratio > video_ratio:
                        new_width = video_width
                        new_height = int(video_width / img_ratio)
                    else:
                        new_height = video_height
                        new_width = int(video_height * img_ratio)

                    img_scaled = cv2.resize(
                        img_cv,
                        (new_width, new_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )

                    current_frame = np.zeros((video_height, video_width, 3), dtype=np.uint8)

                    x_offset = (video_width - new_width) // 2
                    y_offset = (video_height - new_height) // 2
                    current_frame[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = img_scaled

                    if prev_frame is not None:
                        for t in range(transition_frames):
                            progress = t / transition_frames
                            transition_frame = create_page_turn_effect1(prev_frame, current_frame, progress)
                            writer.write(transition_frame)

                    for _ in range(frames_per_image):
                        writer.write(current_frame)

                    prev_frame = current_frame
                    success_count += 1
                    print(f"已追加第 {page_num} 张图片")

                except Exception as e:
                    print(f"追加第{i + 1}张图片失败: {str(e)}")
                    import traceback
                    print(traceback.format_exc())

            print(f"新视频生成完成：{output_video_path}")
            print(f"成功追加图片数量：{success_count}")
            return True

        finally:
            writer.release()

    finally:
        cap.release()

# 翻书特效
def create_page_turn_effect(prev_frame, next_frame, progress):
    """从右向左翻页，翻卷部分显示下一张图片"""
    height, width = prev_frame.shape[:2]
    result = np.zeros_like(prev_frame)

    # 翻页中心点位置，从右向左移动
    center_x = width - int(width * progress * 0.8)

    # 翻卷区域宽度
    curl_width = int(width * 0.2 * (1 - progress))

    for y in range(height):
        for x in range(width):
            # 计算到中心点的距离
            dist_to_center = x - center_x

            # 左侧区域：显示上一张图片
            if dist_to_center < -curl_width:
                result[y, x] = prev_frame[y, x]

            # 右侧区域：显示下一张图片
            elif dist_to_center > curl_width:
                result[y, x] = next_frame[y, x]

            # 翻卷区域：计算翻卷效果
            else:
                # 归一化距离 (-1 到 1)
                normalized_dist = dist_to_center / curl_width

                # 计算弯曲角度 (从0到π弧度)
                angle = normalized_dist * np.pi / 2

                # 计算翻卷后的X坐标 (使用余弦函数模拟翻卷)
                curl_x = center_x + int(curl_width * np.cos(angle))

                # 计算对应下一张图片的位置
                next_x = x - 2 * curl_width

                # 如果在有效范围内，显示下一张图片的对应位置
                if 0 <= next_x < width:
                    result[y, x] = next_frame[y, next_x]
                else:
                    # 超出范围时，显示上一张图片的翻卷效果
                    result[y, x] = prev_frame[y, curl_x]

    # 添加翻页阴影效果
    shadow_mask = np.ones((height, width), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            dist_to_center = x - center_x
            if -curl_width <= dist_to_center <= curl_width:
                # 在弯曲区域添加阴影
                shadow_intensity = 0.3 * (1 - np.cos((dist_to_center / curl_width) * np.pi / 2))
                shadow_mask[y, x] = 1 - shadow_intensity

    # 应用阴影
    result = result.astype(np.float32)
    result[:, :, 0] *= shadow_mask
    result[:, :, 1] *= shadow_mask
    result[:, :, 2] *= shadow_mask
    result = np.clip(result, 0, 255).astype(np.uint8)

    # 添加翻页边缘的高光效果，增强真实感
    for y in range(height):
        for x in range(max(0, center_x - curl_width), min(width, center_x + curl_width)):
            dist = x - (center_x - curl_width)
            if dist < curl_width * 0.2:  # 只在边缘的一小部分添加高光
                highlight = int(25 * (1 - dist / (curl_width * 0.2)))
                result[y, x] = np.clip(result[y, x] + highlight, 0, 255)

    return result

# 报告图片
def generate_images_from_report(data, roof_info, date):
    images = []

    # 确保data是可迭代的列表
    if data is None:
        data = []
    elif not isinstance(data, list):
        try:
            data = list(data) # noqa # 已保证不为空。静态检测的问题
        except:
            data = [data]

    # 处理roof_info中的默认值，确保关键字段存在
    roof_info = {
        **{
            "station_name": "未知电站",
            "station_address": "未知地址",
            "roof_number": "未知数量",
            "roof_name": "未知屋顶",
            "size": "未知容量",
            "type": "未知类型",
            "people": "未知人员",
            "weather": "未知天气",
            "roof_id": "未知编号"
        },
        **roof_info  # 用传入的roof_info覆盖默认值
    }

    # 首先处理第一页内容
    if not data:
        print("无检测结果，生成提示页")
        img = generate_no_result_image()
        if img is not None:
            images.append(img)
        else:
            print("警告：generate_no_result_image返回None")
        return images

    # 第一页图片生成
    page1_img = generate_first_page_image(roof_info, date)
    if page1_img is not None:
        images.append(page1_img)
    else:
        print("警告：generate_first_page_image返回None")

    # 处理动态数据部分（第二页及后续）
    dynamic_data = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            if item[:3] != (-10, -10, '上'):
                dynamic_data.append(item)
        else:
            print(f"跳过格式不正确的数据项: {item}")

    if dynamic_data:
        # 按每页40条数据分批次生成图片
        batches = [dynamic_data[i:i + 40] for i in range(0, len(dynamic_data), 40)]
        for i, batch in enumerate(batches):
            page_img = generate_detail_page_image(batch, roof_info)

            if page_img is not None:
                images.append(page_img)
            else:
                print(f"警告：第{i + 1}页详情页生成失败")
    else:
        # 无动态数据时生成提示页
        print("无有效热斑数据，生成提示页")
        img = generate_no_detail_image()
        if img is not None:
            images.append(img)
        else:
            print("警告：generate_no_detail_image返回None")

    # 统一缩放所有图片高度到1080像素
    valid_images = []
    for i, img in enumerate(images):
        if img is not None and img.size > 0:
            try:
                height_ratio = 1080 / img.shape[0]
                new_width = int(img.shape[1] * height_ratio)
                valid_images.append(cv2.resize(img, (new_width, 1080), interpolation=cv2.INTER_LANCZOS4))
            except Exception as e:
                print(f"警告：第{i + 1}张图片缩放失败: {str(e)}")
        else:
            print(f"警告：第{i + 1}张图片无效")

    return valid_images

# 第一页图片
def generate_first_page_image(roof_info, date):
    # 页面尺寸设置（A4纸尺寸，210mm×297mm，300dpi）
    dpi = 300
    page_width_mm, page_height_mm = 210, 297
    page_width = int(page_width_mm * dpi / 25.4)
    page_height = int(page_height_mm * dpi / 25.4)

    # 上下各留一个文字高度的空白
    text_height = int(Pt(12).pt * dpi / 72)  # 12pt文字的高度
    img = np.ones((page_height + 2 * text_height, page_width, 3), dtype=np.uint8) * 255

    # 字体设置
    title_font = cv2.FONT_HERSHEY_TRIPLEX
    normal_font = cv2.FONT_HERSHEY_SIMPLEX

    # 字体大小计算
    title_font_size = Pt(24).pt * dpi / 72 / 10  # 转换为OpenCV字体大小
    normal_font_size = Pt(12).pt * dpi / 72 / 10

    # 绘制标题
    title_y = text_height  # 从上方空白下方开始绘制
    station_name = roof_info['station_name']
    text_size = cv2.getTextSize(station_name, title_font, title_font_size, 2)[0]
    # 加粗效果：绘制两次文字，略微偏移
    cv2.putText(img, station_name, (page_width // 2 - text_size[0] // 2 + 1, title_y + 1),
                title_font, title_font_size, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, station_name, (page_width // 2 - text_size[0] // 2, title_y),
                title_font, title_font_size, (0, 0, 0), 2, cv2.LINE_AA)
    title_y += int(Pt(24).pt * dpi / 72) + 10  # 标题行间距

    report_title = "光伏电站组件热斑自动检测识别与定位报告"
    text_size = cv2.getTextSize(report_title, title_font, title_font_size, 2)[0]
    cv2.putText(img, report_title, (page_width // 2 - text_size[0] // 2 + 1, title_y + 1),
                title_font, title_font_size, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, report_title, (page_width // 2 - text_size[0] // 2, title_y),
                title_font, title_font_size, (0, 0, 0), 2, cv2.LINE_AA)
    title_y += int(Pt(24).pt * dpi / 72) + 20  # 标题下方空行

    # 绘制屋顶信息表格
    table_y = title_y
    table = draw_table(img, page_width, table_y, roof_info, date, is_first_page=True,
                       normal_font=normal_font, normal_font_size=normal_font_size, dpi=dpi)
    table_y = table[1]  # 获取表格底部y坐标

    # 绘制表格下方说明文字
    note_y = table_y + 20
    notes = [
        "W：屋顶编号   Z：从南往北数阵列数   L：从东往西数块数",
        "U：上方组件   D：下方组件"
    ]
    for note in notes:
        text_size = cv2.getTextSize(note, normal_font, normal_font_size, 1)[0]
        cv2.putText(img, note, (page_width // 2 - text_size[0] // 2, note_y),
                    normal_font, normal_font_size, (0, 0, 0), 1, cv2.LINE_AA)
        note_y += int(Pt(12).pt * dpi / 72) + 5

    return img

# 详情页图片
def generate_detail_page_image(data, roof_info):
    # 页面尺寸设置（A4纸尺寸，210mm×297mm，300dpi）
    dpi = 300
    page_width_mm, page_height_mm = 210, 297
    page_width = int(page_width_mm * dpi / 25.4)
    page_height = int(page_height_mm * dpi / 25.4)

    # 上下各留一个文字高度的空白
    text_height = int(Pt(12).pt * dpi / 72)
    img = np.ones((page_height + 2 * text_height, page_width, 3), dtype=np.uint8) * 255

    # 字体设置
    heading_font = cv2.FONT_HERSHEY_TRIPLEX
    normal_font = cv2.FONT_HERSHEY_SIMPLEX

    # 字体大小计算
    heading_font_size = Pt(16).pt * dpi / 72 / 10
    normal_font_size = Pt(12).pt * dpi / 72 / 10
    header_font_size = Pt(14).pt * dpi / 72 / 10

    # 绘制标题
    title_y = text_height
    heading = "热斑组件详情"
    text_size = cv2.getTextSize(heading, heading_font, heading_font_size, 2)[0]
    # 标题加粗效果
    cv2.putText(img, heading, (page_width // 2 - text_size[0] // 2 + 1, title_y + 1),
                heading_font, heading_font_size, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, heading, (page_width // 2 - text_size[0] // 2, title_y),
                heading_font, heading_font_size, (0, 0, 0), 2, cv2.LINE_AA)
    title_y += int(Pt(16).pt * dpi / 72) + 20  # 标题下方空行

    # 绘制详情表格
    table_y = title_y
    table = draw_table(img, page_width, table_y, roof_info, None, is_first_page=False,
                       normal_font=normal_font, normal_font_size=normal_font_size,
                       header_font_size=header_font_size, data=data, dpi=dpi)
    table_y = table[1]  # 获取表格底部y坐标

    return img

# 中文注释
# 在 OpenCV 图像上绘制中文文本
def put_chinese_text(img, text, position, font_size, color=(0, 255, 0)):
    # 临时复制图像避免修改原始数据
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    # 字体路径（统一从 backend/fonts 读取）
    font_paths = [
        str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"),
    ]

    font = None
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()  # 兜底方案

    # 绘制文本（注意Pillow使用RGB颜色）
    draw.text(position, text, font=font, fill=(color[2], color[1], color[0]))

    # 转换回OpenCV的BGR格式
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# 绘制图片中的中文
def put_chinese_text_1(img, text, position, font_size, color=(0, 255, 0)):
    """在图像上绘制中文字符"""
    # 临时复制图像避免修改原始数据
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    # 字体路径（统一从 backend/fonts 读取）
    font_paths = [
        str(BACKEND_DIR / "fonts" / "SIMHEI.TTF"),
    ]

    font = None
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()  # 兜底方案

    # 绘制文本（注意Pillow使用RGB颜色）
    draw.text(position, text, font=font, fill=(color[2], color[1], color[0]))

    # 转换回OpenCV的BGR格式
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# 表格
def draw_table(img, page_width, y_pos, roof_info, date, is_first_page,
               normal_font, normal_font_size=0.5, header_font_size=0.5, data=None, dpi=300):

    """绘制表格内容，使用put_chinese_text函数绘制文本"""

    # 计算字体大小（将相对大小转换为绝对大小）
    normal_size = int(normal_font_size * 30)
    header_size = int(header_font_size * 30)

    if is_first_page:
        # 第一页屋顶信息表格
        rows, cols = 10, 2
        cell_height = int(Pt(18).pt * dpi / 72)  # 18pt行高
        col_widths = [int(Inches(1.8).inches * dpi), int(Inches(4.2).inches * dpi)]

        # 计算表格总宽度
        table_width = sum(col_widths)

        # 居中放置表格
        table_x = (page_width - table_width) // 2

        # 创建表格边框
        table_y = y_pos
        table_height = rows * cell_height

        # 使用OpenCV绘制表格边框
        for row in range(rows):
            for col in range(cols):
                x1 = table_x + (0 if col == 0 else sum(col_widths[:col]))
                y1 = table_y + row * cell_height
                x2 = x1 + col_widths[col]
                y2 = y1 + cell_height
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 0), 1)

        # 安全计算热斑组件数量
        print(f"data的内容是啥{data}")
        hot_spot_count = 0
        if data:
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) >= 3:
                    if item[:3] != (-10, -10, '上'):
                        hot_spot_count += 1

        # 表格数据
        table_data = [
            ("电站名称", roof_info.get("station_name", "未知电站")),
            ("电站地址", roof_info.get("station_address", "未知地址")),
            ("屋顶个数", roof_info.get("roof_number", "未知数量")),
            ("屋顶名字", roof_info.get("roof_name", "未知屋顶")),
            ("装机容量", roof_info.get("size", "未知容量")),
            ("组件类型", roof_info.get("type", "未知类型")),
            ("扫描时间", str(date) if date else "未知时间"),
            ("扫描人员", roof_info.get("person", "未知人员")),
            ("扫描天气", roof_info.get("weather", "未知天气")),
            ("扫描结果", f"共检测到 {hot_spot_count} 个热斑组件")
        ]

        # 使用put_chinese_text绘制表格内容
        for row, (label, value) in enumerate(table_data):
            for col in range(cols):
                x1 = table_x + (0 if col == 0 else sum(col_widths[:col]))
                y1 = table_y + row * cell_height
                x2 = x1 + col_widths[col]
                y2 = y1 + cell_height

                text = label if col == 0 else value
                font_size = header_size if col == 0 else normal_size

                # 使用getbbox()计算文本尺寸
                img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(img_pil)
                font_paths = [str(BACKEND_DIR / "fonts" / "SIMHEI.TTF")]
                font = None
                for path in font_paths:
                    try:
                        font = ImageFont.truetype(path, font_size)
                        break
                    except:
                        continue
                if font is None:
                    font = ImageFont.load_default()

                bbox = font.getbbox(text)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                # 居中对齐
                text_x = x1 + (x2 - x1 - text_width) // 2
                text_y = y1 + (y2 - y1 - text_height) // 2 + 5  # 微调垂直位置

                # 使用put_chinese_text绘制文本
                img = put_chinese_text(img, text, (text_x, text_y), font_size, (0, 0, 0))

        return (y_pos, table_y + table_height + 20)
    else:
        # 详情页表格
        header_labels = ['序号', '红外图像编号', '缺陷类型', '缺陷位置坐标']

        # 计算列宽（基于字符宽度）
        char_width = int(Inches(0.35).inches * dpi)  # 一个中文字符宽度
        col_widths = [
            int(char_width * 2.8),  # 序号列
            int(char_width * 6.5),  # 图像编号列
            int(char_width * 4.5),  # 缺陷类型列
            int(char_width * 15.2)  # 坐标列
        ]

        # 验证总宽度
        total_width = sum(col_widths)
        if total_width > page_width:
            scale_factor = page_width / total_width
            col_widths = [int(w * scale_factor) for w in col_widths]

        rows = len(data) + 1  # 加表头行
        cell_height = int(Pt(14).pt * dpi / 72)  # 表头行高
        detail_cell_height = int(Pt(12).pt * dpi / 72)  # 详情行高

        # 计算表格总宽度
        table_width = sum(col_widths)

        # 居中放置表格
        table_x = (page_width - table_width) // 2

        # 创建表格边框
        table_y = y_pos
        table_height = cell_height + rows * detail_cell_height  # 假设所有行高一致

        # 使用OpenCV绘制表格边框
        # 绘制表头
        header_y = table_y
        for col in range(len(col_widths)):
            x1 = table_x + (0 if col == 0 else sum(col_widths[:col]))
            x2 = x1 + col_widths[col]
            cv2.rectangle(img, (x1, header_y), (x2, header_y + cell_height), (0, 0, 0), 1)

            # 绘制表头文字
            text = header_labels[col]

            # 使用getbbox()计算文本尺寸
            img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)
            font_paths = [str(BACKEND_DIR / "fonts" / "SIMHEI.TTF")]
            font = None
            for path in font_paths:
                try:
                    font = ImageFont.truetype(path, header_size)
                    break
                except:
                    continue
            if font is None:
                font = ImageFont.load_default()

            bbox = font.getbbox(text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            text_x = x1 + (x2 - x1 - text_width) // 2
            text_y = header_y + (cell_height - text_height) // 2 + 5  # 微调垂直位置

            # 使用put_chinese_text绘制文本
            img = put_chinese_text(img, text, (text_x, text_y), header_size, (0, 0, 0))

        # 绘制详情行
        for row, item in enumerate(data):
            row_y = header_y + cell_height + row * detail_cell_height
            for col in range(len(col_widths)):
                x1 = table_x + (0 if col == 0 else sum(col_widths[:col]))
                x2 = x1 + col_widths[col]
                y1 = row_y
                y2 = y1 + detail_cell_height
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 0), 1)

                # 确保text变量在使用前被明确赋值
                text = ""
                try:
                    if col == 0:
                        text = f"{row + 1:03d}"
                    elif col == 1:
                        # 确保item有足够的元素
                        if isinstance(item, (list, tuple)) and len(item) >= 3:
                            major_row, col_num, vertical_pos = item[0], item[1], item[2]
                            position_flag = "U" if vertical_pos == "上" else "D"
                            roof_id = roof_info.get('roof_id', '未知编号')
                            text = f"W{roof_id}/Z{major_row}/L{col_num}/{position_flag}"
                        else:
                            text = "数据格式错误"
                    elif col == 2:
                        text = "热斑"
                    elif col == 3:
                        # 确保item有足够的元素
                        if isinstance(item, (list, tuple)) and len(item) >= 3:
                            major_row, col_num, vertical_pos = item[0], item[1], item[2]
                            roof_id = roof_info.get('roof_id', '未知编号')
                            text = f"{roof_id}号屋顶，第{major_row}组，第{col_num}列，{vertical_pos}组件"
                        else:
                            text = "数据格式错误"
                except Exception as e:
                    print(f"警告：第{row + 1}行数据处理错误: {str(e)}")
                    text = "数据处理错误"

                # 使用getbbox()计算文本尺寸
                img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(img_pil)
                font_paths = [str(BACKEND_DIR / "fonts" / "SIMHEI.TTF")]
                font = None
                for path in font_paths:
                    try:
                        font = ImageFont.truetype(path, normal_size)
                        break
                    except:
                        continue
                if font is None:
                    font = ImageFont.load_default()

                bbox = font.getbbox(text)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                text_x = x1 + (x2 - x1 - text_width) // 2 if col < 3 else x1 + 10
                text_y = y1 + (detail_cell_height - text_height) // 2 + 5  # 微调垂直位置

                # 使用put_chinese_text绘制文本
                img = put_chinese_text(img, text, (text_x, text_y), normal_size, (0, 0, 0))

        return (y_pos, table_y + table_height + 20)

# 无检测结果的图片
def generate_no_result_image():
    width, height = 800, 600
    img = np.ones((height, width, 3), dtype=np.uint8) * 255
    font = cv2.FONT_HERSHEY_TRIPLEX
    font_size = 1.0
    text = "无检测结果"
    text_size = cv2.getTextSize(text, font, font_size, 2)[0]
    cv2.putText(img, text, (width // 2 - text_size[0] // 2, height // 2 + text_size[1] // 2),
                font, font_size, (0, 0, 0), 2, cv2.LINE_AA)
    return img

# 详细信息的图片
def generate_no_detail_image():
    width, height = 800, 600
    img = np.ones((height, width, 3), dtype=np.uint8) * 255
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_size = 0.8
    text = "未检测到热斑组件。"
    text_size = cv2.getTextSize(text, font, font_size, 1)[0]
    cv2.putText(img, text, (width // 2 - text_size[0] // 2, height // 2 + text_size[1] // 2),
                font, font_size, (0, 0, 0), 1, cv2.LINE_AA)
    return img

# 中文文本
def draw_text_with_chinese(img, text, position, font_size=24, color=(0, 0, 0)):
    # 转换为PIL图像
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    # 字体路径（请根据实际情况修改）
    font_path = str(BACKEND_DIR / "fonts" / "SIMHEI.TTF")
    try:
        font = ImageFont.truetype(font_path, font_size)
    except:
        font = ImageFont.load_default()

    # 绘制文本
    draw.text(position, text, font=font, fill=color)

    # 转换回OpenCV格式
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# 模型导入并且检测每帧
def detect_frames_with_progress(stable_frames, max_start, max_end, cache_start_idx, cache_end_idx,
                                model_path=None, class_names=None, imgsz=640, conf_thres=0.5, iou_thres=0.45):
    """
    使用YOLOv5模型对视频帧进行检测，并返回检测结果缓存（带进度条）。

    参数:
        stable_frames (list[np.ndarray]): 稳定帧列表（BGR格式）。
        max_start (int): 起始帧编号。
        max_end (int): 结束帧编号。
        cache_start_idx (int): 缓存起始索引。
        cache_end_idx (int): 缓存结束索引。
        model_path (str): YOLOv5模型权重文件路径（默认 best.pt）。
        class_names (list[str]): 类别名称列表（默认 ["组件破碎", "裂纹"]）。
        imgsz (int): 模型输入尺寸（默认 640）。
        conf_thres (float): 置信度阈值（默认 0.5）。
        iou_thres (float): NMS的IOU阈值（默认 0.45）。

    返回:
        detection_cache (dict): 检测结果缓存，键为帧编号，值为检测框列表。
    """
    if class_names is None:
        class_names = ["组件破碎", "裂纹"]

    # 创建保存目录
    save_dir = f"max_magnification_mid_half_{max_start}-{max_end}"
    detect_dir = os.path.join(save_dir, "detection_results")
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(detect_dir, exist_ok=True)

    #TODO 系统兼容 使得win上训练出来的模型 可以在mac上使用(如果要在win上跑 那就需要注释下面4行)
    pathlib.WindowsPath = pathlib.PosixPath
    pathlib.PureWindowsPath = pathlib.PurePosixPath
    sys.modules['pathlib'].WindowsPath = pathlib.PosixPath
    sys.modules['pathlib'].PureWindowsPath = pathlib.PurePosixPath

    # 加载模型
    if model_path is None:
        model_path = WEIGHT_BEST_PATH
    else:
        model_path = pathlib.Path(model_path)
        if not model_path.is_absolute():
            model_path = BACKEND_DIR / model_path

    model_path = model_path.resolve()
    print("YOLO模型权重路径：", model_path)

    if not model_path.exists():
        raise FileNotFoundError(f"YOLO模型权重不存在: {model_path}")

    device = select_device(device='')
    ckpt = torch.load(str(model_path), map_location=device, weights_only=False, encoding="utf-8")
    model = Model(ckpt["model"].yaml, ch=3, nc=len(class_names)).to(device)
    model.load_state_dict(ckpt["model"].float().state_dict(), strict=False)
    model.eval()
    imgsz = check_img_size(imgsz, s=model.stride.max())

    detection_cache = {}

    # 遍历帧（带进度条）
    for cache_idx in tqdm(range(cache_start_idx, cache_end_idx + 1), desc="检测进度", unit="帧"):
        frame_num = max_start + cache_idx
        current_frame = stable_frames[cache_idx].copy()

        # 预处理
        img = letterbox(current_frame, new_shape=imgsz, auto=True)[0]
        img = img[:, :, ::-1].transpose(2, 0, 1)
        img = np.ascontiguousarray(img)
        img = torch.from_numpy(img).to(device).float() / 255.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # 推理
        with torch.no_grad():
            pred = model(img, augment=False, visualize=False)
            pred = non_max_suppression(pred, conf_thres=conf_thres, iou_thres=iou_thres)

        # 解析结果
        frame_cache = {}
        for det in pred:
            if len(det) == 0:
                continue
            h0, w0 = current_frame.shape[:2]
            gn = torch.tensor(current_frame.shape)[[1, 0, 1, 0]]
            for *xyxy, conf, cls in reversed(det):
                xyxy = torch.tensor(xyxy).view(-1, 4)
                xyxy = (xyxy / torch.tensor([imgsz, imgsz, imgsz, imgsz])) * gn
                xyxy = xyxy.round().int().tolist()[0]
                x1, y1, x2, y2 = xyxy
                x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w0, x2), min(h0, y2)
                if x1 >= x2 or y1 >= y2:
                    continue
                cls_name = class_names[int(cls)] if int(cls) < len(class_names) else f"未知类别_{int(cls)}"
                unique_key = (cls_name, (x1, y1, x2, y2))
                if unique_key not in frame_cache:
                    frame_cache[unique_key] = {
                        "label": cls_name,
                        "box": (x1, y1, x2, y2),
                        "confidence": round(float(conf), 2)
                    }
        if frame_cache:
            detection_cache[frame_num] = list(frame_cache.values())

    return detection_cache

# 视频处理过程中的一个数据清理逻辑，主要用来维护和清理编号（数字）的出现历史记录
def cleanup_number_history(shared_data,cleanup_threshold,cleanup_interval):

    number_history = shared_data['number_frame_history']
    valid_numbers = []

    # 筛选有效编号：50帧前出现≥3次（原有逻辑）
    for num, history in number_history.items():
        if len(history) > 50:
            old_history = history[:-50]
            if sum(old_history) >= 3:
                valid_numbers.append(num)
        else:
            valid_numbers.append(num)  # 历史不足50帧默认保留

    # 清理无效编号（从历史中删除）
    for num in list(number_history.keys()):
        if num not in valid_numbers:
            del number_history[num]
    # 清理延迟计数器（原有逻辑）
    delay_counters = shared_data['delay_counters']
    for num in list(delay_counters.keys()):
        if num not in valid_numbers and delay_counters[num] <= 0:
            del delay_counters[num]

    # 更新共享数据与清理阈值
    shared_data['number_frame_history'] = number_history
    shared_data['delay_counters'] = delay_counters
    cleanup_threshold += cleanup_interval

# 遍历detection_cache中每个值对象（就是检测结果列表），对每个检测结果提取标签信息，格式：帧号-缺陷类型 并存储到defect_labels
def collect_detect_labels(processor)->list[str]:
  # 存储提取的缺陷标签（沿用之前的逻辑，改为通过processor访问）
    defect_labels = []
    # 遍历类实例processor的detection_cache（即原self.detection_cache）
    for frame_num, detection_items in processor.detection_cache.items():
        for item in detection_items:
            # 提取标签（缺陷类型 + 置信度，与原检测逻辑一致）
            current_label = f"{frame_num} - {item['label']}"
            # 去重：避免重复添加相同标签（按需保留）
            if current_label not in defect_labels:
                defect_labels.append(current_label)
    return defect_labels

# 从缺陷标签列表中提取帧号和缺陷类型，并与帧位置映射表进行匹配，生成新的组合标签
def match_defect_with_position(processor,defect_labels:list[str])->list[str]:
 # 匹配帧号对应的编号和缺陷类型
    matched_defects = []
    # 遍历缺陷标签提取帧号和缺陷类型
    for label in defect_labels:
        # 分割帧号和缺陷类型（假设格式为 "帧号 - 缺陷类型"）
        parts = label.split(" - ", 1)
        if len(parts) != 2:
            continue  # 跳过格式异常的标签
        frame_num_str, defect_type = parts
        try:
            frame_num = int(frame_num_str)
        except ValueError:
            continue  # 跳过帧号不是数字的标签

        # 检查该帧号是否在位置映射中存
        if hasattr(processor, 'frame_position_map') and frame_num in processor.frame_position_map:
            position_info = processor.frame_position_map[frame_num]
            # 组合成 "帧号-编号-缺陷类型" 格式
            matched_defect = f"{frame_num}-{position_info}-{defect_type}"
            matched_defects.append(matched_defect)

    return matched_defects

# 对缺陷标签进行去重
def deduplicate_defect_labels(matched_defects):
    # 提取“编号-缺陷类型”并去重（使用集合自动去重）
    unique_defects_set = set()
    for item in matched_defects:
        # 分割格式：帧号-编号-缺陷类型 → 取后两部分组合
        parts = item.split("-", 1)  # 只分割一次，避免缺陷类型含“-”时出错
        if len(parts) >= 2:
            # 保留“编号-缺陷类型”部分（parts[1]即为“编号-缺陷类型”）
            unique_key = parts[1]
            unique_defects_set.add(unique_key)  # 集合自动去重
    return unique_defects_set

# 筛选出现次数 ≥ 3 次的编号并按编号的两个部分排序
def filter_and_sort_valid_numbers(shared_data)->list[str]:
    valid_numbers_final = []
    number_history = shared_data['number_frame_history']
    # 最终筛选：历史中出现≥3次的编号（原有逻辑）
    for num, history in number_history.items():
        if sum(history) >= 3:
            valid_numbers_final.append(num)
    sorted_valid_nums = sorted(valid_numbers_final, key=lambda x: (x[0], x[1]))
    return sorted_valid_nums

# 将热斑检测的结果数据转化为一份包含文字描述和可视化图片的完整报告
def generate_report_and_images(db_results, roof_info, time_str, unique_defects_set):
    global global_normal_infos
    roof_info = normalize_report_roof_info(roof_info)
    word_filename = build_report_word_path(roof_info)

    # 【未改动】生成Word报告（保留原有逻辑，不修改）
    save_to_word(unique_defects_set, word_filename, roof_info, time_str)
    global_normal_infos['db_result'] = db_results
    global_normal_infos['roof_info'] = roof_info
    global_normal_infos['time_str'] = time_str
    global_normal_infos['report_path'] = word_filename

    print(f"报告归档路径:{word_filename}")

    print("正在生成封面图片....")
    global_normal_infos['unique_defects_set'] = unique_defects_set
    first_page = generate_first_page(unique_defects_set, roof_info, time_str, dpi=300)
    print(f"unique_defects_set: {unique_defects_set}")
    print(f"db_results: {db_results}")

    print("正在生成详细缺陷图片...")
    detail_pages = []

    # ========== 新增/修改部分：按编号分组，合并缺陷类型 ==========
    # 1. 初始化分组字典：key=编号（如W1/Z3/L6），value=缺陷类型列表（如["热斑","组件破碎"]）
    defect_group = {}
    # 假设 unique_defects_set 里的元素格式是 "编号-缺陷类型"（如"W1/Z3/L6-热斑"）
    for defect in unique_defects_set:
        # 拆分编号和缺陷类型（按"-"分割，兼容格式异常）
        if "-" in defect:
            code, defect_type = defect.split("-", 1)  # 只分割一次，避免类型含"-"
            # 把同编号的缺陷类型加入列表
            if code in defect_group:
                defect_group[code].append(defect_type)
            else:
                defect_group[code] = [defect_type]
        else:
            # 格式异常时，编号=缺陷本身，类型="未知缺陷"
            defect_group[defect] = ["未知缺陷"]

    # 2. 重构合并后的缺陷条目（格式："编号-缺陷类型1/缺陷类型2"）
    merged_defects = []
    for code, types in defect_group.items():
        # 合并缺陷类型（用"/"拼接，和Word里的格式一致）
        merged_type = "/".join(types)
        merged_defects.append(f"{code}-{merged_type}")

    # ========== 生成图片：遍历合并后的条目（一个编号仅一页） ==========
    # 遍历合并后的缺陷条目，而非原unique_defects_set
    for defect in tqdm(merged_defects, desc="生成缺陷图片"):
        page = generate_detail_pages([defect], dpi=300)
        detail_pages.extend(page)

    # 返回封面+合并后的详情页图片
    return [first_page] + detail_pages

# 将生成的word报告插入到视频中
def insert_images_to_video(out, image_cache, fps=30):
    """
    将报告图片插入视频结尾
    """
    if image_cache and out.isOpened():
        insert_cached_images_to_video(out, image_cache, fps)
        report_video_path = OUTPUT_VIDEOS_DIR / "report.mp4"
        images_to_video(str(report_video_path), image_cache, fps)
    else:
        print("无有效报告图片可插入视频")

# 释放视频解释器
def release_video_writer(out):
    """
    释放视频写入器资源
    """
    if out.isOpened():
        out.release()  # 释放后，MP4 的 moov atom 才会完整写入
    else:
        print("警告：原始视频写入器未正常打开，可能存在文件损坏风险")

# 检查视频文件的完整性（视频文件输入路径以及文件大小是否存在或合理）
def check_video_integrity(output_path):
    """
    检查视频文件完整性
    """
    if not os.path.exists(output_path):
        print(f"错误：原始视频文件 {output_path} 不存在，无法绘制标注")
        cv2.destroyAllWindows()
        exit()

    file_size = os.path.getsize(output_path)
    if file_size < 1024 * 100:  # 若文件小于100KB，判定为不完整
        print(f"错误：原始视频文件过小（{file_size} 字节），可能生成中断")
        cv2.destroyAllWindows()
        exit()

# 检查srt的文件对应的屋顶是否在数据库中有存在
def is_exist_roof_by_lon_lat(lon_lat_infos):
    roofs = get_all_roof()
    for roof in roofs:
        if roof.get('longitude') is None or roof.get('latitude') is None:
            continue
        if (lon_lat_infos['min_longitude'] < roof['longitude'] < lon_lat_infos['max_longitude']) and (lon_lat_infos['min_latitude'] < roof['latitude'] < lon_lat_infos['max_longitude']):
            return {'result': 'true', 'error': '存在对应的屋顶信息'}
    return {'result': 'false', 'error': '导入的srt文件对应的屋顶不存在数据库中,请添加对应的屋顶信息'}

