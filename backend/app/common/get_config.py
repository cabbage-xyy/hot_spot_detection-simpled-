# 读取 config.yaml 文件中信息
from pathlib import Path

import yaml


def get_config(config_path: str | Path):
    """仅首次加载文件，整个程序中只会产生一个 _config 对象。"""
    if not hasattr(get_config, "_config"):
        config_file = Path(config_path)

        try:
            with config_file.open("r", encoding="utf-8") as f:
                get_config._config = yaml.safe_load(f)
        except FileNotFoundError:
            raise Exception(f"配置文件不存在:{config_file}")
        except yaml.YAMLError as e:
            raise Exception(f"配置文件解析错误:{e}") from e

    return get_config._config
