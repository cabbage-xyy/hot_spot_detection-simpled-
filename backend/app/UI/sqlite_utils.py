# 对数据库sqlite的操作
import pprint
import sqlite3
import threading  # 新增：导入线程锁模块
from functools import wraps

from app.common.srt_lat_lng_range import *
from app.core.paths import DB_PATH

# ========== 第一步：先定义全局变量 ==========
# 1. 数据库绝对路径（确保任何启动路径都能找到文件）
company_name_database = str(DB_PATH)

# 2. 定义数据库线程锁（核心：解决多线程并发冲突）
db_lock = threading.Lock()
# ========== 第二步：带锁的装饰器 ==========
def with_db_connection(func):
    """
    数据库连接/游标装饰器（带线程安全锁）：
    1. 自动创建/关闭连接、创建/关闭游标
    2. 精准区分连接错误和SQL执行错误
    3. 自动处理事务（提交/回滚）
    4. 线程安全：避免多线程并发操作数据库冲突
    被装饰的函数第一个参数会自动传入 (conn, cursor) 元组
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 核心：加线程锁，同一时间只有一个线程能操作数据库
        with db_lock:
            conn = None
            cursor = None
            try:
                # 第一步：尝试建立数据库连接
                conn = sqlite3.connect(company_name_database)
                conn.row_factory = sqlite3.Row
                print("✅ 数据库连接成功")

                # 第二步：创建游标并传入被装饰函数
                cursor = conn.cursor()
                # 把 (连接, 游标) 作为第一个参数传给业务函数
                result = func((conn, cursor), *args, **kwargs)

                # 执行成功则提交事务
                conn.commit()
                return result

            # 修复：正确捕获 sqlite3.Error（之前的 Error 未定义）
            except sqlite3.Error as e:
                error_msg = str(e).lower()
                if conn:
                    conn.rollback()

                # 精准判断错误类型
                if "unable to open database file" in error_msg or "no such file or directory" in error_msg:
                    print(f"❌ 数据库连接失败：{e}")
                elif "syntax error" in error_msg:
                    print(f"❌ SQL语法错误：{e}")
                elif "no such table" in error_msg:
                    print(f"❌ SQL执行错误：表不存在 - {e}")
                elif "no such column" in error_msg:
                    print(f"❌ SQL执行错误：字段不存在 - {e}")
                elif "database is locked" in error_msg:
                    print(f"❌ 数据库被锁定：多线程并发冲突（已加锁，若仍出现需检查代码） - {e}")
                else:
                    print(f"❌ 数据库操作错误：{e}")

                # 统一返回空列表，保持原有逻辑兼容
                return []

            # 捕获其他未知错误
            except Exception as e:
                if conn:
                    conn.rollback()
                    print("数据库位置错误")
                print(f"❌ 未知错误：{e}")
                return []

            finally:
                # 优先关闭游标，再关闭连接
                if cursor:
                    cursor.close()
                    print("🔚 游标已关闭")
                if conn:
                    conn.close()
                    print("🔚 数据库连接已关闭")

    return wrapper



# 获取到对应的公司名称信息
@with_db_connection
def get_company_name(db_objects,pattern):

    conn,cursor = db_objects
    cursor.execute("""select name 
                      from company_name
                      where name like ? collate nocase""",(pattern,))
    users = [row["name"] for row in cursor.fetchall()]
    return users

# 自动输出所有公司的名称
@with_db_connection
def get_all_company_names(db_objects):
    conn,cursor = db_objects
    try:
        cursor.execute("""select name 
                          from company_name 
                        where is_delete = ?""",(0,))
        company_names = cursor.fetchall()
        return [row["name"] for row in company_names]
        print("查询所有公司名字成功!!!!")
    except Exception as e:
        raise Exception(f"查询所有公司名字失败!!! {str(e)}") from e
    return company_names

def get_all_company_names1(db_objects):
    conn,cursor = db_objects
    try:
        cursor.execute("""select name 
                          from company_name
                          where is_delete = ?  """,(0,))
        company_names = cursor.fetchall()
        print("查询所有公司名字成功!!!!")
    except Exception as e:
        raise Exception(f"查询所有公司名字失败!!! {str(e)}") from e

    return [row[0] for row in company_names]

# 根据公司名字获取到对应的公司id(1)
@with_db_connection
def get_id_by_company_name(db_objects,company_name):
    conn, cursor = db_objects
    cursor.execute(
        """
        select id from company_name
            where name = ? and is_delete = ?
        """,(company_name,0)
    )
    row = cursor.fetchone()
    return row[0] if row else None


# 根据拼接的屋顶信息来获取对应屋顶详细信息里的总组件个数
@with_db_connection
def get_sum_numbers_by_new_roof_name(db_objects,roof_name,roof_id):
    new_table = f"{roof_name}_{roof_id}"
    conn,cursor = db_objects
    cursor.execute(f"""
        select count(*) from "{new_table}"
    """)
    rows = cursor.fetchone()
    if not rows:
        raise Exception("没有导入对应的屋顶信息")
    return rows[0]


# 根据公司名字获取对应的公司id(2)
def get_id_by_company_name1(db_objects,company_name):
    conn, cursor = db_objects
    cursor.execute(
        """
        select id from company_name
            where name = ? and is_delete = ?
        """,(company_name,0)
    )
    id = cursor.fetchone()[0]
    return id

# 根据公司id获取到对应的屋顶信息
@with_db_connection
def get_roof_infos_by_company_id(db_objects,company_id):
    conn, cursor = db_objects
    try:
        sql_get = """select * 
                     from roof_info
                  where company_id = ? and is_delete = ?"""
        cursor.execute(sql_get, (company_id,0))
        roof_infos = cursor.fetchall()
        print("根据公司id获取到对应的屋顶信息成功")
    except Exception as e:
        raise Exception("根据公司id获取到对应的屋顶信息失败",str(e)) from e
    return [dict(row) for row in roof_infos]

@with_db_connection
# 根据公司名字表中的id获取到对应的屋顶名称
def get_roof_name_by_company_id(db_objects,company_id):
    conn, cursor = db_objects
    cursor.execute("""
    select *
    from company_name
    join roof_info
    on company_name.id = roof_info.company_id
    and company_name.id = ? and company_name.is_delete = ? and roof_info.is_delete = ?
    """,(company_id,0,0))
    roof_names = [ row["roof_name"] for row in cursor.fetchall()]
    return roof_names

@with_db_connection
# 根据公司名字表中的id获取到对应的电站名称
def get_station_name_by_company_id(db_objects,company_id):
    conn,cursor = db_objects
    try:
        cursor.execute("""
            select station_name
            from roof_info
            where company_id = ? and is_delete = ?
        """,(company_id,0))
        station_names = cursor.fetchall()

    except Exception as e:
        raise Exception("查询电站名字失败", str(e)) from e
    return [station_name[0] for station_name in station_names] if station_names else []

@with_db_connection
# 根据电站名称获取对应的屋顶名称
def get_roof_name_by_station_name(db_objects,station_name):
    print(type(station_name))
    print("station_name是否为空：", station_name is None or station_name.strip() == "")
    conn, cursor = db_objects
    try:
        cursor.execute("""
        select roof_name
        from roof_info
        where station_name = ? and is_delete = ?
        """,(station_name,0))
        roof_names = cursor.fetchall()
        print("根据电站名查询屋顶名成功")
    except Exception as e:
        raise Exception("根据电站名查询屋顶名失败",str(e)) from e
    return [row["roof_name"] for row in roof_names] if roof_names else []

@with_db_connection
# 根据屋顶名称返回对应的详细信息
def get_roof_info_by_roof_name(db_objects,roof_name):
    conn,cursor = db_objects
    cursor.execute("""
    select *
    from roof_info
    where roof_name = ? and is_delete = ?
    """,(roof_name,0))
    roof_infos = [dict(row) for row in cursor.fetchall()]
    return roof_infos

# # sqlite_utils.py 中修改 get_all_company_names 函数
# @with_db_connection  # 加上装饰器，自动管理连接
# def get_all_company_names(db_object):  # 第一个参数必须是conn（装饰器自动传入）
#     """查询数据库中所有公司名称，返回列表"""
#     conn, cursor = db_object
#     # 替换为你的表名和字段名（示例：company表的name字段）
#     cursor.execute("SELECT name FROM company_name")  # 注意：你的表名是company_name（看界面右侧）
#     results = cursor.fetchall()
#     # 转换为纯字符串列表
#     company_list = [row["name"] for row in results]  # 因为装饰器设置了row_factory=sqlite3.Row，所以用row["name"]
#     return company_list

# 根据屋顶中的经纬度以及srt中读取到的最小最大纬度
# 1:判断该视频是不是属于该屋顶的 2:如果是则返回其他更详细的屋顶信息
@with_db_connection
def get_roof_info_by_lon_lat(db_object,srt_path):
    conn,cursor = db_object
    coordinates=extract_coordinates_from_srt(srt_path)
    lon_lat_info = calculate_min_max_avg_coordinates(coordinates)

    roof_info = {
        "roof_id": "未知id",
        "station_name": "未知电站",
        "station_address": "未知电站地址",
        "roof_number": "未知屋顶数量",
        "roof_name": "未知屋顶名称",
        "size": "未知容量",
        "type": "未知类型",
        "person": "未知人员",
        "weather": "未知天气",
        "longitude": "未知经度",
        "latitude": "未知纬度",
        "company_id": "未知公司id",
        "min_longitude": "未知最小经度",
        "max_longitude": "未知最大经度",
        "min_latitude": "未知最小纬度",
        "max_latitude": "未知最大纬度",
        "status": "运行中"
    }

    try:
        sql_select = """select *
                        from roof_info
                        where longitude  between ? and ?
                        and latitude  between ? and ?
                        and is_delete = ?
                        """

        cursor.execute(sql_select,(lon_lat_info['min_longitude'],lon_lat_info['max_longitude'],lon_lat_info['min_latitude'],lon_lat_info['max_latitude'],0))
        results = cursor.fetchall()
        results_dict = [dict(row) for row in results]
    except sqlite3.OperationalError as e:
        raise Exception(f"【SQL执行失败-操作失误】\n原因: {e}\n建议：检查表名或字段名，或sql语法有误)")  from e
    except sqlite3.ProgrammingError as e:
        raise Exception(f"【SQL执行失败-编译错误】\n原因: {e}\n建议：检查sql语句语法（比如引号，逗号，关键字）") from e
    except sqlite3.Error as e:
        raise Exception(f"【SQL执行失败-SQLite错误】\n具体错误：{e})") from e
    except Exception as e:
        raise Exception (f"【执行失败-系统错误】\n原因：{e}\n建议：检查数据库文件路径或权限") from e

    if results_dict[0]:
        roof_info['roof_id'] = results_dict[0]['id']
        roof_info["station_name"] = results_dict[0]["station_name"]
        roof_info["station_address"] = results_dict[0]["station_address"]
        roof_info["roof_number"] = results_dict[0]["roof_number"]
        roof_info["roof_name"] = results_dict[0]["roof_name"]
        roof_info["size"] = results_dict[0]["size"]
        roof_info["type"] = results_dict[0]["type"]
        roof_info["person"] = results_dict[0]["person"]
        roof_info["weather"] = results_dict[0]["weather"]
        roof_info["longitude"] = results_dict[0]["longitude"]
        roof_info["latitude"] = results_dict[0]["latitude"]
        roof_info["company_id"] = results_dict[0]["company_id"]
        roof_info["min_longitude"] = results_dict[0]["min_longitude"]
        roof_info["max_longitude"] = results_dict[0]["max_longitude"]
        roof_info["min_latitude"] = results_dict[0]["min_latitude"]
        roof_info["max_latitude"] = results_dict[0]["max_latitude"]
        roof_info["status"] = results_dict[0]["status"] if "status" in results_dict[0].keys() else "运行中"

    return roof_info

@with_db_connection
def get_roof_info_by_lon_lat1(db_object,srt_path,company_id,roof_name):
    conn,cursor = db_object
    coordinates=extract_coordinates_from_srt(srt_path)
    if not coordinates:
        print("SRT文件中未提取到经纬度数据")
        return None
    lon_lat_info = calculate_min_max_avg_coordinates(coordinates)

    roof_info = {
        "roof_id": "未知id",
        "station_name": "未知电站",
        "station_address": "未知电站地址",
        "roof_number": "未知屋顶数量",
        "roof_name": "未知屋顶名称",
        "size": "未知容量",
        "type": "未知类型",
        "person": "未知人员",
        "weather": "未知天气",
        "longitude": "未知经度",
        "latitude": "未知纬度",
        "company_id": "未知公司id",
        "min_longitude": "未知最小经度",
        "max_longitude": "未知最大经度",
        "min_latitude": "未知最小纬度",
        "max_latitude": "未知最大纬度",
        "status": "运行中"
    }

    try:
        sql_select = """select *
                        from roof_info
                        where longitude  between ? and ?
                        and latitude  between ? and ?
                        and is_delete = ?
                        and company_id = ?
                        and roof_name = ?"""

        cursor.execute(sql_select,(lon_lat_info['min_longitude'],lon_lat_info['max_longitude'],lon_lat_info['min_latitude'],lon_lat_info['max_latitude'],0,company_id,roof_name))
        print("SQL执行成功，开始获取结果")
        results = cursor.fetchall()
        if not results:
            print(f"未找到匹配的屋顶信息：company_id={company_id}, roof_name={roof_name}")
            return None
        print("查询结果：", results)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        results_dict = [dict(zip(columns, row)) for row in results]
        print("转换为字典成功：", results_dict)
    except sqlite3.OperationalError as e:
        raise Exception(f"【SQL执行失败-操作失误】\n原因: {e}\n建议：检查表名或字段名，或sql语法有误)")  from e
    except sqlite3.ProgrammingError as e:
        raise Exception(f"【SQL执行失败-编译错误】\n原因: {e}\n建议：检查sql语句语法（比如引号，逗号，关键字）") from e
    except sqlite3.Error as e:
        raise Exception(f"【SQL执行失败-SQLite错误】\n具体错误：{e})") from e
    except Exception as e:
        raise Exception (f"【执行失败-系统错误】\n原因：{e}\n建议：检查数据库文件路径或权限") from e

    if results_dict and len(results_dict) > 0:
        roof_info['roof_id'] = results_dict[0]['id']
        roof_info["station_name"] = results_dict[0]["station_name"]
        roof_info["station_address"] = results_dict[0]["station_address"]
        roof_info["roof_number"] = results_dict[0]["roof_number"]
        roof_info["roof_name"] = results_dict[0]["roof_name"]
        roof_info["size"] = results_dict[0]["size"]
        roof_info["type"] = results_dict[0]["type"]
        roof_info["person"] = results_dict[0]["person"]
        roof_info["weather"] = results_dict[0]["weather"]
        roof_info["longitude"] = results_dict[0]["longitude"]
        roof_info["latitude"] = results_dict[0]["latitude"]
        roof_info["company_id"] = results_dict[0]["company_id"]
        roof_info["min_longitude"] = results_dict[0]["min_longitude"]
        roof_info["max_longitude"] = results_dict[0]["max_longitude"]
        roof_info["min_latitude"] = results_dict[0]["min_latitude"]
        roof_info["max_latitude"] = results_dict[0]["max_latitude"]
        roof_info["status"] = results_dict[0]["status"] if "status" in results_dict[0].keys() else "运行中"

    return roof_info

# 匹配热斑位置信息表与具体屋顶中板是否存在
@with_db_connection
def match_hot_spot_with_panel_position(db_object,roof_name,detected_numbers):

    conn, cursor = db_object
    condition_templates = []
    params = []


    for line_number, column_number in detected_numbers:
        condition_templates.append("(line_number = ? and column_number = ?)")
        params.append(line_number)
        params.append(column_number)

    sql_select = f"""select * 
                    from {roof_name} 
                    where {' OR '.join(condition_templates)}"""
    cursor.execute(sql_select, params)
    matched_results = cursor.fetchall()

    return [tuple(row) for row in matched_results]

# 增加电站信息
def add_station_info(db_object,message):
    conn,cursor = db_object

    sql_insert = """insert into roof_info
                    ("station_name","station_address","roof_number","roof_name","size","type","person","weather","longitude","latitude","company_id","min_longitude","max_longitude","min_latitude","max_latitude","status")
                    values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    cursor.execute(sql_insert,message)


def _normalize_nullable_value(value):
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if text == "" or text == "未填写":
            return None
        return text

    return value


def _build_station_management_tuple(message, company_id):
    return (
        _normalize_nullable_value(message.get("station_name")),
        _normalize_nullable_value(message.get("station_address")),
        _normalize_nullable_value(message.get("roof_number")),
        _normalize_nullable_value(message.get("roof_name")),
        _normalize_nullable_value(message.get("size")),
        _normalize_nullable_value(message.get("type")),
        _normalize_nullable_value(message.get("person")),
        _normalize_nullable_value(message.get("weather")),
        _normalize_nullable_value(message.get("longitude")),
        _normalize_nullable_value(message.get("latitude")),
        company_id,
        _normalize_nullable_value(message.get("min_longitude")),
        _normalize_nullable_value(message.get("max_longitude")),
        _normalize_nullable_value(message.get("min_latitude")),
        _normalize_nullable_value(message.get("max_latitude")),
        _normalize_nullable_value(message.get("status")) or "运行中",
    )


def _get_company_id_or_create(db_object, company_name):
    conn, cursor = db_object

    cursor.execute(
        """
        select id
        from company_name
        where name = ? and is_delete = 0
        """,
        (company_name,),
    )
    row = cursor.fetchone()

    if row:
        return row[0]

    cursor.execute(
        """
        insert into company_name (name, is_delete)
        values (?, 0)
        """,
        (company_name,),
    )
    return cursor.lastrowid

# 增加公司名称和电站信息(放在一个事务里避免半操作的情况发生)
@with_db_connection
def add_company_name_and_station_info(db_object,name,message):
    try:
        is_exist = False
        company_names = get_all_company_names1(db_object)
        print("查询到的所有公司的名字",company_names)
        for c_name in company_names:
            if c_name == name:
                is_exist = True
        print(f"是否存在重复的公司名字{is_exist}")
        if is_exist:
            company_id = get_id_by_company_name1(db_object, name)
        else:
            add_company_name(db_object, name)
            company_id = get_id_by_company_name1(db_object, name)
        new_message = list(message)
        new_message[10] = company_id
        message = tuple(new_message)
        print("传入公司id后的message信息",new_message)
        add_station_info(db_object,message)
        print("增加数据库成功")
    except Exception as e:
        raise Exception(f"增加数据库时发生失败 {str(e)}") from e


# 电站管理页面专用：新增公司和屋顶信息，接收 dict，避免旧函数 tuple/list 格式不兼容
@with_db_connection
def add_station_management_info(db_object, company_name, message):
    try:
        company_id = _get_company_id_or_create(db_object, company_name)
        insert_values = _build_station_management_tuple(message, company_id)
        add_station_info(db_object, insert_values)
        print("电站管理页面新增数据库成功")
        return True
    except Exception as e:
        raise Exception(f"电站管理页面新增数据库失败 {str(e)}") from e

# 更改屋顶信息
@with_db_connection
def update_station_info(db_object,update_message):
    conn,cursor = db_object
    try:
        if not update_message:
            print("错误：没有要更新的字段！")

    except Exception as e:
        raise Exception(f"更改电站信息错误:{str(e)}") from e

# 根据传进来的公司名更改公司表中的公司名称名称
def update_company_name_by_company_name(db_object,company_name,new_company_name):
    conn, cursor = db_object
    try:
        cursor.execute("""update company_name
                            set name = ? 
                            where name = ?""",(new_company_name,company_name))
        effect_rows = cursor.rowcount
        if effect_rows > 0:
            print(f"修改公司名称成功,成功修改{effect_rows}条记录")
        else:
            print("修改公司名称失败")
    except Exception as e:
        raise Exception("修改公司名称失败",str(e)) from e
    return effect_rows

# 根据传进来的屋顶名称修改屋顶信息中的详细表
def update_roof_info_by_roof_name(db_object,roof_name,update_message):
    conn, cursor = db_object
    try:
        valid_fileds = {
            k:v for k,v in update_message.items()
            if v is not None
        }
        if not valid_fileds:
            print("无需更新的字段!!")
            return
        set_clause = ",".join([f"{key} = ?" for key in valid_fileds.keys()])
        sql_set = f"""update roof_info
                      set {set_clause}
                      where roof_name = ?"""
        print("更新语句的sql",sql_set)
        params = list(valid_fileds.values()) +[roof_name]
        cursor.execute(sql_set,params)
        effect_rows = cursor.rowcount
        if effect_rows > 0:
            print("数据库信息修改成功!!!")
        else:
            print("数据库信息修改失败!!!")

    except Exception as e:
        raise Exception("更新屋顶信息发生错误")
    return effect_rows

@with_db_connection
def update_station_management_info_by_id(db_object, roof_id, company_name, update_message):
    conn, cursor = db_object
    try:
        company_id = _get_company_id_or_create(db_object, company_name)

        valid_fields = {
            key: _normalize_nullable_value(value)
            for key, value in update_message.items()
            if key in {
                "station_name",
                "station_address",
                "roof_number",
                "roof_name",
                "size",
                "type",
                "person",
                "weather",
                "longitude",
                "latitude",
                "min_longitude",
                "max_longitude",
                "min_latitude",
                "max_latitude",
                "status",
            }
        }
        valid_fields["company_id"] = company_id

        set_clause = ", ".join([f"{key} = ?" for key in valid_fields.keys()])
        sql_set = f"""
            update roof_info
            set {set_clause}
            where id = ? and is_delete = 0
        """
        params = list(valid_fields.values()) + [roof_id]
        cursor.execute(sql_set, params)
        effect_rows = cursor.rowcount

        if effect_rows > 0:
            print(f"电站管理页面更新成功，更新{effect_rows}条")
        else:
            print("电站管理页面更新失败：未找到对应记录")

        return effect_rows
    except Exception as e:
        raise Exception(f"电站管理页面更新失败 {str(e)}") from e

# 总的更新操作
@with_db_connection
def update_all_info(db_object,company_names:tuple,roof_name:str,update_message:dict):
    row_company = 0
    row_info = 0
    try:
        if company_names[1]:
            row_company = update_company_name_by_company_name(db_object,company_names[0],company_names[1])
        if update_message:
            row_info = update_roof_info_by_roof_name(db_object,roof_name,update_message)
        print("总更新操作更新成功")
    except Exception as e:
        raise Exception("总更新失败",str(e)) from e
    return f"公司表修改成功了{row_company}条,屋顶表修改成功了{row_info}"


# 显示公司名称,以及屋顶的所有详细信息
@with_db_connection
def select_all_infos(db_object):
    conn, cursor = db_object
    try:
        sql_select = """select company_name.name, roof_info.*,
                               coalesce(roof_info.status, '运行中') as status
                        from company_name join roof_info
                        on company_name.id = roof_info.company_id
                        and company_name.is_delete = ? and roof_info.is_delete = ?"""
        results = cursor.execute(sql_select,(0,0))
    except Exception as e:
        raise Exception("查询所有信息失败",str(e)) from e
    results = [dict(row) for row in results]
    pprint.pprint(results)
    return results


# ========== 热斑管理页面：正式检测记录表 hotspot_detection_record ==========
@with_db_connection
def select_hotspot_detection_records(db_object):
    conn, cursor = db_object
    try:
        cursor.execute(
            """
            select *
            from hotspot_detection_record
            where is_delete = 0
            order by detect_time desc, id desc
            """
        )
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        raise Exception(f"查询热斑检测记录失败 {str(e)}") from e


@with_db_connection
def add_hotspot_detection_record(db_object, message):
    conn, cursor = db_object
    try:
        cursor.execute(
            """
            insert into hotspot_detection_record
            (
                detect_code,
                company_id,
                company_name,
                station_name,
                roof_id,
                roof_name,
                video_path,
                report_path,
                detect_time,
                detect_duration,
                hotspot_component_count,
                defect_summary,
                process_status,
                report_status,
                is_delete
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                message.get("detect_code"),
                message.get("company_id"),
                message.get("company_name"),
                message.get("station_name"),
                message.get("roof_id"),
                message.get("roof_name"),
                message.get("video_path"),
                message.get("report_path"),
                message.get("detect_time"),
                message.get("detect_duration", 0),
                message.get("hotspot_component_count", 0),
                message.get("defect_summary") or "热斑",
                message.get("process_status") or "未处理",
                message.get("report_status") or "已生成",
            ),
        )
        print("热斑管理正式检测记录新增成功")
        return cursor.lastrowid
    except Exception as e:
        raise Exception(f"热斑管理正式检测记录新增失败 {str(e)}") from e


@with_db_connection
def update_hotspot_detection_record(db_object, record_id, update_message):
    conn, cursor = db_object
    try:
        valid_fields = {
            key: value
            for key, value in update_message.items()
            if key in {
                "process_status",
                "report_status",
                "report_path",
                "defect_summary",
                "hotspot_component_count",
            }
            and value is not None
        }

        if not valid_fields:
            print("热斑管理记录无需更新")
            return 0

        valid_fields["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause_parts = []
        params = []

        for key, value in valid_fields.items():
            if key == "updated_at":
                set_clause_parts.append("updated_at = CURRENT_TIMESTAMP")
            else:
                set_clause_parts.append(f"{key} = ?")
                params.append(value)

        sql_update = f"""
            update hotspot_detection_record
            set {', '.join(set_clause_parts)}
            where id = ? and is_delete = 0
        """
        params.append(record_id)
        cursor.execute(sql_update, params)
        effect_rows = cursor.rowcount
        print(f"热斑管理记录更新成功，影响{effect_rows}条")
        return effect_rows
    except Exception as e:
        raise Exception(f"热斑管理记录更新失败 {str(e)}") from e



@with_db_connection
def delete_hotspot_detection_record_by_id(db_object, record_id):
    conn, cursor = db_object
    try:
        cursor.execute(
            """
            update hotspot_detection_record
            set is_delete = 1,
                updated_at = CURRENT_TIMESTAMP
            where id = ? and is_delete = 0
            """,
            (record_id,),
        )
        effect_rows = cursor.rowcount
        print(f"热斑管理记录软删除成功，影响{effect_rows}条")
        return effect_rows
    except Exception as e:
        raise Exception(f"热斑管理记录软删除失败 {str(e)}") from e


# ========== 热斑检测页面右下角：检测任务记录表 detection_task_record ==========
@with_db_connection
def add_detection_task_record(db_object, message):
    conn, cursor = db_object
    try:
        cursor.execute(
            """
            insert into detection_task_record
            (
                company_id,
                company_name,
                station_name,
                roof_id,
                roof_name,
                started_at,
                finished_at,
                hotspot_component_count,
                is_saved_to_hotspot_management,
                hotspot_record_id,
                task_status,
                is_delete
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                message.get("company_id"),
                message.get("company_name"),
                message.get("station_name"),
                message.get("roof_id"),
                message.get("roof_name"),
                message.get("started_at"),
                message.get("finished_at"),
                message.get("hotspot_component_count", 0),
                message.get("is_saved_to_hotspot_management", 0),
                message.get("hotspot_record_id"),
                message.get("task_status") or "检测中",
            ),
        )
        record_id = cursor.lastrowid
        print(f"检测任务记录新增成功 record_id={record_id}")
        return record_id
    except Exception as e:
        raise Exception(f"检测任务记录新增失败 {str(e)}") from e


@with_db_connection
def update_detection_task_record(db_object, record_id, update_message):
    conn, cursor = db_object
    try:
        valid_fields = {
            key: value
            for key, value in update_message.items()
            if key in {
                "company_id",
                "company_name",
                "station_name",
                "roof_id",
                "roof_name",
                "started_at",
                "finished_at",
                "hotspot_component_count",
                "is_saved_to_hotspot_management",
                "hotspot_record_id",
                "task_status",
            }
            and value is not None
        }

        if not valid_fields:
            print("检测任务记录无需更新")
            return 0

        set_clause_parts = []
        params = []

        for key, value in valid_fields.items():
            set_clause_parts.append(f"{key} = ?")
            params.append(value)

        set_clause_parts.append("updated_at = CURRENT_TIMESTAMP")

        sql_update = f"""
            update detection_task_record
            set {', '.join(set_clause_parts)}
            where id = ? and is_delete = 0
        """
        params.append(record_id)
        cursor.execute(sql_update, params)
        effect_rows = cursor.rowcount
        print(f"检测任务记录更新成功，影响{effect_rows}条")
        return effect_rows
    except Exception as e:
        raise Exception(f"检测任务记录更新失败 {str(e)}") from e


@with_db_connection
def select_detection_task_records(db_object, limit=20):
    conn, cursor = db_object
    try:
        cursor.execute(
            """
            select *
            from detection_task_record
            where is_delete = 0
            order by finished_at desc, started_at desc, id desc
            limit ?
            """,
            (limit,),
        )
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        raise Exception(f"查询检测任务记录失败 {str(e)}") from e


@with_db_connection
def delete_detection_task_record_by_id(db_object, record_id):
    conn, cursor = db_object
    try:
        cursor.execute(
            """
            update detection_task_record
            set is_delete = 1,
                updated_at = CURRENT_TIMESTAMP
            where id = ? and is_delete = 0
            """,
            (record_id,),
        )
        effect_rows = cursor.rowcount
        print(f"检测任务记录软删除成功，影响{effect_rows}条")
        return effect_rows
    except Exception as e:
        raise Exception(f"检测任务记录软删除失败 {str(e)}") from e

# 删除公司名字
def delete_by_company_name(db_object,company_name):
    conn, cursor = db_object
    try:
        sql_del = """update company_name 
                     set is_delete = 1
                     where name = ?"""
        cursor.execute(sql_del,(company_name,))
        print("删除公司名字成功")
    except Exception as e:
        raise Exception("删除公司名字失败",str(e)) from e
# 根据公司id获取到还有几个公司下的屋顶信息
def get_roof_number_by_company_id(db_objects,company_id):
    conn, cursor = db_objects
    try:
         sql_get = """select count(*)
                      from roof_info
                      where company_id = ? and is_delete = 0"""
         cursor.execute(sql_get,(company_id,))
         roof_number = cursor.fetchone()[0]
         print("获取公司下屋顶数量成功")
    except Exception as e:
        raise Exception("获取公司下屋顶数量失败",str(e)) from e
    return roof_number
# 删除公司对应的屋顶(根据电站名字,屋顶名字,还有对应的country_id)
def delete_roof_by_station_roof_countryId(db_objects,station_name,roof_name,country_id):
    conn, cursor = db_objects
    try:
        sql_del = """update roof_info 
                     set is_delete = 1
                     where station_name = ? and roof_name = ? and company_id = ?"""
        cursor.execute(sql_del,(station_name,roof_name,country_id))
        print("删除对应公司屋顶成功")
    except Exception as e:
        raise Exception("删除公司对应的屋顶失败",str(e)) from e

# 最终的删除逻辑
@with_db_connection
def delete_company_info(db_objects,company_name,station_name,roof_name,company_id):
    try:
        roof_number = get_roof_number_by_company_id(db_objects,company_id)
        if roof_number == 1:
            delete_by_company_name(db_objects,company_name)
        delete_roof_by_station_roof_countryId(db_objects,station_name,roof_name,company_id)
        print("总的删除是成功的")
    except Exception as e:
        raise Exception("总的删除是失败的",str(e)) from e


# 电站管理页面专用：按 roof_info.id 软删除，避免同名屋顶误删
@with_db_connection
def delete_station_management_info_by_id(db_objects, roof_id):
    conn, cursor = db_objects
    try:
        cursor.execute(
            """
            select company_id
            from roof_info
            where id = ? and is_delete = 0
            """,
            (roof_id,),
        )
        row = cursor.fetchone()

        if not row:
            print("电站管理页面删除失败：未找到对应屋顶记录")
            return 0

        company_id = row[0]

        cursor.execute(
            """
            update roof_info
            set is_delete = 1
            where id = ? and is_delete = 0
            """,
            (roof_id,),
        )
        effect_rows = cursor.rowcount

        cursor.execute(
            """
            select count(*)
            from roof_info
            where company_id = ? and is_delete = 0
            """,
            (company_id,),
        )
        remaining_roof_count = cursor.fetchone()[0]

        if remaining_roof_count == 0:
            cursor.execute(
                """
                update company_name
                set is_delete = 1
                where id = ?
                """,
                (company_id,),
            )

        print(f"电站管理页面软删除成功，影响{effect_rows}条")
        return effect_rows
    except Exception as e:
        raise Exception(f"电站管理页面软删除失败 {str(e)}") from e

# 根据选择输入输出视频那里的srt（最大小经纬度）判断是否有对应的屋顶
@with_db_connection
def get_all_roof(db_objects):
    conn, cursor = db_objects
    try:
        sql_select = """select * 
                        from roof_info
                        where is_delete = 0"""
        cursor.execute(sql_select)
        results = cursor.fetchall()
    except Exception as e:
        raise Exception("查询所有屋顶信息",str(e)) from e
    return [dict(row) for row in results]

if __name__ == "__main__":
    numbers = get_sum_numbers_by_new_roof_name("芯能屋顶A", "1")
    print(numbers)