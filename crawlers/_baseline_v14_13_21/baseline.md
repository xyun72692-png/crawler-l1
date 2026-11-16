# 基线 v14.13.21（2026-11-17 冻结 · CI 红点收口）

本版改动：
  · tests/mock_site.py 顶部加 CI 编码护栏（stdout/stderr 都 reconfigure 到 utf-8）
    + 请求日志路径改成 ascii 安全写法（backslashreplace）
  · .github/workflows/test.yml 注解收紧：只认行首「  FAIL」，并附该日志末 25 行
    → 以后 CI 红，一条 API 调用就能看到是哪条用例、异常是什么

受管条目 81；测试仍 330 项。
上一版：_baseline_v14_13_20（81 条）。
