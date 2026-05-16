# 与数据库有关的操作均在此 包括数据库的连接 查询等
from functools import wraps

import psycopg2
from psycopg2 import OperationalError

from app.common.get_config import get_config
from app.core.paths import CONFIG_PATH


def with_db_connection(func):
    """定义数据库连接装饰器(切面逻辑: 连接->执行业务->关闭)"""
    @wraps(func)  # 保留原函数的名称和文档字符串
    def wrapper(*args, **kwargs):
        # 切面前置逻辑:建立数据库连接
        conn = None  # 数据库连接对象 数据库是否连接
        cur = None  # 游标 执行sql语句
        db_info = get_config(CONFIG_PATH)  # 读取配置文件中的数据库信息

        try:
            conn = psycopg2.connect(
                dbname=db_info["database"]["dbname"],
                user=db_info["database"]["user"],
                password=db_info["database"]["password"],
                host=db_info["database"]["host"],
                port=db_info["database"]["port"],
            )

            cur = conn.cursor()
            kwargs["cur"] = cur  # 把游标cur作为参数传给业务函数(核心:让业务函数能直接用游标)

            # 核心业务逻辑(切点)
            result = func(*args, **kwargs)

            # 后置逻辑: 提交+关闭
            conn.commit()
            return result

        except OperationalError as e:
            raise OperationalError(f"数据库连接失败{str(e)}") from e
        except Exception as e:
            if conn:
                conn.rollback()
            raise Exception(f"查询过程中发生失败{str(e)}") from e
        finally:
            if cur:
                try:
                    cur.close()
                except Exception as e:
                    print(f"关闭游标失败{str(e)}")
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    print(f"关闭数据库连接失败{str(e)}")

    return wrapper

@with_db_connection
def get_roof_info(latitude, longitude, cur=None):
    """根据输入的纬度和经度获取对应的屋顶信息"""
    roof_info = {
        "station_name": "未知电站",
        "station_address": "未知地址",
        "roof_number": "未知数量",
        "roof_name": "未知屋顶",
        "size": "未知容量",
        "type": "未知类型",
        "person": "未知人员",
        "weather": "未知天气",
        "roof_id": "未知编号",
    }

    try:
        query = """
                SELECT "电站名字", "电站地址",  "屋顶个数", "屋顶名字", "装机容量", "组件类型", "扫描人员", "扫描天气", "屋顶编号"
                FROM "经纬度查名字"
                WHERE %s BETWEEN "最小纬度" AND "最大纬度"
                AND %s BETWEEN "最小经度" AND "最大经度"
        """

        cur.execute(query, (latitude, longitude))
        result = cur.fetchone()

        if result:
            roof_info["station_name"] = result[0]
            roof_info["station_address"] = result[1]
            roof_info["roof_number"] = result[2]
            roof_info["roof_name"] = result[3]
            roof_info["size"] = result[4]
            roof_info["type"] = result[5]
            roof_info["person"] = result[6]
            roof_info["weather"] = result[7]
            roof_info["roof_id"] = result[8]
        else:
            print(f"警告: 未找到纬度{latitude},经度{longitude}的屋顶信息")
    except Exception as e:
        raise Exception(f"查询屋顶信息业务逻辑错误{str(e)}") from e

    return roof_info


# 批量查询数据库
@with_db_connection
def query_roof_info_pg(roof_name, sorted_numbers, cur=None):
    matched_results = []

    # 构建批量查询条件
    condition_templates = []
    params = []

    for major_row, col_num in sorted_numbers:
        condition_templates.append("(major_row = %s AND col_num = %s)")
        params.extend([major_row, col_num])

    # 在指定屋顶名称的表中查询组件信息
    query = f"SELECT * FROM {roof_name} WHERE {' OR '.join(condition_templates)}"
    cur.execute(query, params)
    results = cur.fetchall()

    # 按原始顺序匹配结果
    result_dict = {(row[0], row[1]): row for row in results}

    for num in sorted_numbers:
        if num in result_dict:
            matched_results.append(result_dict[num])

    return matched_results
