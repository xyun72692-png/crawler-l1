# 基线 v14.13.17（2026-11-16 冻结 · A 组：公开一致性）

本版改动：
  · tests/data/qscms74/*.html 与 qscms74_golden.json：16 个真实公司名 → 等长假名
    （9 个 HTML 样本同步改，golden 的 html_bytes/html_md5 已重算）
  · tools/golden/_probe_wzrc.json、_probe_yqwzrc_list.json 同步脱敏
  · tests/data/reports/ 3 份报告改名并去标识（run_id/时间戳/本机路径）
  · README 四处过期数字（行数/基线名/327→329/verify 行）与 --ignore-robots 帮助文案

受管条目仍 80；测试仍 329 项。
上一版：_baseline_v14_13_16（80 条）。
