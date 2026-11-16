# 基线 v14.13.19（2026-11-16 冻结 · B5 修正）

本版改动：
  · crawler.py：_swallow() 的关键路径日志修正。v14.13.18 里它引用的 `log`
    在模块作用域不存在（NameError 被吞），实际只计数、从不落日志；
    现在由 main() 注入 _ACTIVE_LOG，未注入时退回 print。
  · tests/test_crawler.py：新增 213 用例（计数 / critical 分级 / 日志真实落点）。
  · tests/run_all.py：修 GBK 控制台崩溃（子进程统一 UTF-8，输出 errors=replace）。
  · 克隆可验证：.gitignore 例外指向本目录；verify 默认值同步为 .19。

受管条目仍 80；测试 330 项（216→217）。
上一版：_baseline_v14_13_18（80 条）。
