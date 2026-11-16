# 基线 v14.13.20（2026-11-16 冻结 · CI 可诊断性）

本版改动（全在测试与 CI，引擎未动）：
  · tests/test_crawler.py / test_discover.py / test_rule0.py / test_render_batch.py
    顶部加「CI 编码护栏」：PYTHONIOENCODING=utf-8 + PYTHONUTF8=1（写在 os.environ，
    子进程继承）——GitHub 的 windows runner 默认 locale 是 cp1252
  · .github/workflows/test.yml 重写：每套输出 tee 到 logs/*.log；
    failure() 时把 FAIL 行 + 各套末尾 15 行写进 Job Summary，并上传 artifacts
    → 以后 CI 红了，打开 Actions 页面就能看到「哪一条用例挂了」，不用下载日志

受管条目仍 80；测试仍 330 项。
上一版：_baseline_v14_13_19（80 条）。
