# 五分钟：回放一条候选并保存复核

1. 安装：`python3 -m venv .venv`，然后 `.venv/bin/python -m pip install -e .`。
2. 运行：`.venv/bin/python -m video_temporal_audit demo-v2 --output runs/first_run`。
3. 打开 `runs/first_run/index.html`，选“闪烁与复核示例”，点击候选的“回放此时段”。
4. 对照“播放器位置”和“源 PTS”，选择结论，写具体画面依据。刷新页面检查草稿恢复；再点“导出已完成复核 JSONL”。
5. 用 `import-reviews --report 原报告/report.json --reviews 导出文件.jsonl --output runs/reviewed` 生成新复核报告。未完成项继续待办。

已运行示例位于 [examples/demo_v2/index.html](examples/demo_v2/index.html)。有意静止反例会触发候选；你可判“合法变化”，算法结果仍保留。源起点示例的事件在源 PTS 7 秒、播放 2 秒，点击后从播放 1.5 秒开始。

自己的素材：`.venv/bin/python -m video_temporal_audit analyze --video /path/clip.mp4 --output runs/my_clip`。结果目录包含视频预览、timeline.html、逐帧 CSV 与 JSON 绑定；输入文件不被修改。已有输出目录请换新名字。

若浏览器限制本地存储或文件摘要，在仓库根运行 `.venv/bin/python -m video_temporal_audit serve --directory . --port 8765`，通过 localhost 打开同一路径。程序只生成候选，需查看连续视频后判断。
