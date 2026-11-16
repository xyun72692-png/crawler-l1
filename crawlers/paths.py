# -*- coding: utf-8 -*-
"""统一路径来源（v14.13.16 起）。

默认取项目根目录（本文件的上上级），可用环境变量 CRAWLER_HOME 覆盖：

    set CRAWLER_HOME=E:\\other\\agent-work
    python crawlers\\crawler.py --site wzrc_all

这样换台机器、换个盘符都不用改代码；测试里原有的
CRAWLER_OUT_DIR / CRAWLER_LOG_DIR / CRAWLER_STATE_DIR / CRAWLER_REPORT_DIR
仍然优先级更高（它们是按用例隔离用的）。
"""
import os
from pathlib import Path

HOME = Path(os.environ.get("CRAWLER_HOME") or Path(__file__).resolve().parent.parent)

DATA = HOME / "data"
RAW = DATA / "raw"
ATTACHMENTS = DATA / "attachments"
OUT = HOME / "out"
REPORTS = OUT / "reports"
LOGS = HOME / "logs"
STATE = HOME / "manifests"
