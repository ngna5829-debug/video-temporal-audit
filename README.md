# 视频时序复核工具 · video-temporal-audit v2

<!-- publication-status:start -->
**发布与学习入口：** [项目静态首页（本地文件）](index.html) · [在线示例](https://ngna5829-debug.github.io/video-temporal-audit/) · [中文教材专章](docs/TUTORIAL.zh-CN.md) · [统一教材 PDF（v2.0.0）](https://github.com/ngna5829-debug/edit-regression-lab/releases/download/v2.0.0/aigc-evaluation-textbook-v2.pdf) · [CI 运行](https://github.com/ngna5829-debug/video-temporal-audit/actions/workflows/tests.yml)。

Pages 展示已生成的静态示例；分析、模型推理和正式导入仍在本机 Python 中执行。CI 配置安装仓库包、检查依赖并运行离线测试与 CLI；实际运行结果请打开上方 CI 链接，按对应 commit 查看。
<!-- publication-status:end -->

把短视频中的静止、亮度突变和切镜候选整理成可定位回放的中文时间线，再记录画面依据、导出复核 JSONL、生成独立的复核版报告。适合展示一条完整的工程链路：真实解码 → 保留源时间戳 → 检测 → 连续回放 → 复核绑定 → 结果验真。

**当前固定受控测试中，开启运动补偿后 TP / FP / FN 从 8 / 26 / 2 变为 8 / 4 / 2。** 两段平移片的切镜误报从 22 降到 0；切镜附近仍漏匹配 2 个闪光事件。素材是程序生成的受控夹具，参考事件是构造标签，未调用视频生成模型，也没有真人质量评分。

[Mac 首次运行与排错](docs/GETTING_STARTED.zh-CN.md) · [结果与失败案例](docs/CASE_STUDY.zh-CN.md) · [我的个人扩展任务](MY_WORK.md) · [公开示例入口](examples/demo_v2/index.html) · [机器验证记录](verification_v2.json)

## 先运行一个短片

需要 **Python 3.12**，CPU 即可；不需要模型密钥或模型权重。先在终端 `cd` 到含本 README 和 `pyproject.toml` 的项目目录。没有 Python 的读者先按[完整入门](docs/GETTING_STARTED.zh-CN.md)准备环境。

如果已按教材安装 uv，但 `python3.12` 不在 PATH，可用 `uv venv --seed --python 3.12 .venv` 替代下方建环境命令，随后仍用 `.venv/bin/python`；环境创建后可用 `.venv/bin/python --version` 检查版本。这是备用操作路线，不表示作者已实跑 uv 的系统安装过程。

```bash
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip check
.venv/bin/python -m video_temporal_audit analyze \
  --video examples/demo_v2/fixtures/media/test_source_1_flicker.mp4 \
  --config examples/demo_v2/calibration/config.json \
  --motion-compensation on --output runs/first_clip
```

成功时终端应返回 48 帧、1 个候选，并生成 `runs/first_clip/timeline.html`、`preview.mp4`、`report.json`、`frames.csv`、`result.json` 和证据图。每次使用新目录；已有结果不会覆盖。`status=completed` 只说明执行完成。

启动支持视频 Range 跳转的本机服务，保持该终端运行：

```bash
.venv/bin/python -m video_temporal_audit serve --directory . --port 8765
```

在浏览器打开 [首次运行时间线](http://127.0.0.1:8765/runs/first_clip/timeline.html)。点击 E001 的“回放此时段”，确认播放器从约 1.5 秒开始连续播放，事件本身在播放 2.0 秒附近。结束时回到运行服务的终端按 **Control+C**；关闭浏览器标签不会停止服务。

服务只绑定 `127.0.0.1`。它支持 HTTP Range 按需读取；普通服务缺少 Range 时，页面仅对不超过 64 MiB 的预览做 SHA-256 核验后使用本机 Blob。首次运行直接使用上述内置服务。页面没有远端脚本、字体或统计请求。

## 换成自己的视频并保存复核

将命令里的示例路径换成自己拍摄或有权处理的短片路径；含空格或中文的路径用双引号包住。先选约 5–20 秒、1080p 或更小的素材。最大 1200 帧、单帧像素总数不超过 `4096 × 2160`；这是像素总数限制，不是分别限制宽与高。读取第一路视频流，分析缩略图不超过 320×192。超帧数会拒绝，不会静默只分析前半段。

```bash
.venv/bin/python -m video_temporal_audit analyze \
  --video "/完整路径/我的短片.mp4" \
  --motion-compensation on --output runs/my_video
```

省略 `--config` 使用写入报告的预设规则；示例冻结配置只适用于演示受控夹具，不能直接当成自己素材的已校准阈值。用 `--motion-compensation off` 可做同片配对检查，须使用另一个输出目录。

回放连续画面后，选择“确认是问题 / 合法变化 / 证据不足”，填写具体时间与画面依据，点“导出已完成复核 JSONL”。“保存本机草稿”和页面“导回复核 JSONL”只更新当前浏览器草稿；正式复核版需要执行：

```bash
.venv/bin/python -m video_temporal_audit import-reviews \
  --report runs/my_video/report.json \
  --reviews "$HOME/Downloads/实际下载的复核文件.jsonl" \
  --output runs/my_video_reviewed
```

新目录必须与原报告目录分开，也不能是原目录的子目录。成功返回 `imported / reviewed / pending`，原算法候选保留。复核同时绑定媒体 SHA、片段 ID、有效配置摘要、事件摘要；配置或事件篡改、未知事件、重复事件、非字符串字段和空依据均被拒绝。一个人的复核记录为 `human_unverified`，不会自动变成多人真值。完整操作见[入门指南](docs/GETTING_STARTED.zh-CN.md)。

## 时间轴怎样读

源 PTS 是原视频的展示时间戳；播放器相对秒数为 `源 PTS − 源首帧 PTS`。例如 [offset_flash](examples/demo_v2/timing/offset_flash/report.json) 的源首帧为 5.0 秒，事件源 PTS 为 7.0 秒，因此播放位置为 2.0 秒，按钮提前 0.5 秒从 1.5 秒回看。VFR 保留各帧实际时间间隔，不能用帧号除以固定帧率换算。

该例**原始 MP4 的 FFprobe 流时长是 3.916667 秒**。源末帧缺少正显示时长，分析用相邻 PTS 间隔中位数估计尾帧，所以分析相对结束为 4.0 秒，修复后的预览也覆盖这条约 4.0 秒的分析时间线。`source_end_is_estimated=true`、`source_last_duration_source=median_delta_ESTIMATE` 和 `timing_warnings` 明示这一点；不能把 4.0 秒写成源文件实测时长。预览无音轨，不能评估音画同步。

## 实际消融与解释

28 段受控事件素材中，校准 8 段/2 个来源组，测试 20 段/4 个声明来源组；另有时间边界素材，不进入事件分数。两种规则使用同一视频、36 组校准网格选出的同一阈值、同一切镜保护，仅切换运动补偿。测试集合在开发中已查看，结论限于固定回归集合。

| 事件 | 原规则 TP / FP / FN | 运动补偿 TP / FP / FN | 参考事件数 |
|---|---:|---:|---:|
| 静止候选 | 2 / 2 / 0 | 2 / 2 / 0 | 2 |
| 亮度突变 | 2 / 2 / 2 | 2 / 2 / 2 | 4 |
| 切镜候选 | 4 / 22 / 0 | 4 / 0 / 0 | 4 |
| 合计 | **8 / 26 / 2** | **8 / 4 / 2** | **10** |

[metrics.json](examples/demo_v2/test/metrics.json) 保存逐类、逐来源组和逐片结果。运动估计在 940 对相邻帧中失败 103 对，失败时回退原始结构差；冻结检测始终使用原始帧差。因此有意静止仍报警，切镜保护仍可能压制邻近闪光。有关剩余 4 个误报、2 个漏匹配、匹配分母及可展示顺序，见[案例说明](docs/CASE_STUDY.zh-CN.md)。

## 输出与验证范围

| 文件 | 用途 |
|---|---|
| `timeline.html`、`preview.mp4`、`evidence/` | 连续回放、候选定位、复核表单、抽帧证据 |
| `report.json` | 源/相对 PTS、尾帧估计标记、有效配置、候选及独立复核 |
| `frames.csv` | 每帧时间、显示时长、帧差、运动拟合状态和残差 |
| `result.json` | 执行状态、计数、警告和输出工件 SHA-256 |
| `reviews.jsonl` | CLI 导入后保存的复核交换记录 |

[当前验证记录](verification_v2.json)保留角色20时点的 59 项 Python 测试、12 项 JavaScript 协议断言、24 个预览的独立尾帧检查，以及更新预览后的浏览器 Range/Blob 回放验收。完整 demo 的保存运行耗时约 15.75 秒，是该机器的一次测量；后续非法输入修复没有重跑完整 demo，公开指标字节不变。文档本轮仅新跑 1 个短片及复核/HTTP 检查，不将既有验收冒称本轮执行。

可选开发验证：

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_timeline.js
```

Node 仅用于协议测试，不是首次分析视频所需依赖。坏媒体、非法配置/时间、错误复核或拒绝覆盖通常以 `ERROR: ...` 和退出码 **2** 结束；零候选不是质量通过。现有规则不评价身份一致性、物理规律、口型或音轨，多物体运动、视差、遮挡和弱纹理也可能导致全局运动拟合失败。

源码 [MIT](LICENSE)；程序生成的几何夹具 [CC0](FIXTURE_LICENSE.md)。个人媒体与运行目录应保留在 `data/private/`、`runs/` 等已忽略位置；授权说明与来源需要自己记录。



当前来源分支已补至60项Python测试，受控指标及校准文件逐字节保持。自有数据参考仍未独立核验，不自动称真人真值；[来源分支修复记录](docs/PROVENANCE_FIX50.json)保存范围、源码摘要与实跑结果。
