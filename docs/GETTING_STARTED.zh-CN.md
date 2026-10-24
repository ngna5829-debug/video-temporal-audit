# Mac 首次运行：从一个短片到正式复核版

本指南面向刚开始使用终端的读者。第一次只分析仓库附带的一段短片，确认安装、视频定位和复核保存都通，再换成自己的素材。工具在本机 CPU 上运行，不要求模型账号、API 密钥或模型权重。

## 1. 找到项目目录与 Python 3.12

先将项目解压或克隆到本机。在 Mac 打开“终端”，输入 `cd` 和一个空格，把 Finder 中的 `video-temporal-audit` 文件夹拖进终端，再按回车。下面的命令都在这个项目目录执行；能看到 `README.md`、`pyproject.toml`、`video_temporal_audit/` 才是正确位置。

```bash
pwd
ls
python3.12 --version
```

应看到 `Python 3.12.x`。如果显示 `command not found`，先从 [Python 官方 macOS 安装页面](https://www.python.org/downloads/macos/)选择 Python 3.12 的 macOS 安装包并完成安装，重新打开终端后再检查。此项目需要 Python 3.12 或以上，但本轮保存的实际环境是 **3.12.14**；本指南固定使用 `python3.12`，避免不小心调用另一个版本。

建立这个项目专用的 Python 环境：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip check
.venv/bin/python -m video_temporal_audit --help
```

`venv` 会新建 `.venv/` 文件夹；`pip install -e .` 从当前目录安装项目及固定版本依赖，需要联网下载软件包。之后始终使用 `.venv/bin/python`，无需执行激活命令。`pip check` 应显示 `No broken requirements found.`；帮助中应出现 `analyze`、`serve`、`import-reviews`、`demo-v2`。`imageio-ffmpeg` 提供本项目使用的 FFmpeg，首次流程不要求你单独安装 FFprobe 或 Node。

如果安装失败，先停在这里修好安装，不要把历史示例文件当成此次成功输出。这里给出的是可执行安装流程；本次文档验收复用了已配置的 Python 3.12.14 环境，没有重新下载一套依赖。

## 2. 分析附带的 4 秒闪烁短片

将下面整段命令复制到终端。反斜杠 `\` 表示命令尚未结束；它后面不要加空格或注释。

```bash
.venv/bin/python -m video_temporal_audit analyze \
  --video examples/demo_v2/fixtures/media/test_source_1_flicker.mp4 \
  --config examples/demo_v2/calibration/config.json \
  --motion-compensation on \
  --output runs/first_clip
```

正常返回的 JSON 包含 `frames: 48`、`events: 1`、`source_start_s: 0.0`，并给出时间线的完整路径。源素材是受控几何夹具，不是模型生成视频。这个 `test_source_1_flicker` 的源流确有约 4 秒时长；不要将它与后文源尾帧需要估计的 `offset_flash` 混淆。

`runs/first_clip/` 应包含：

| 路径 | 你需要检查什么 |
|---|---|
| `timeline.html` | 中文时间线和 E001 候选 |
| `preview.mp4` | 可播放的无声 H.264 预览 |
| `evidence/` | 候选的证据帧图像 |
| `report.json` | 48 个源时间戳、1 个候选、媒体及配置绑定 |
| `frames.csv` | 逐帧诊断，可用表格软件查看 |
| `result.json` | `status` 为 `completed`，含输出工件摘要 |

再次运行时改成 `runs/first_clip_02` 等新目录。工具拒绝覆盖非空目录；不要为消除报错直接删除自己需要保留的结果。

可用这段只读命令确认执行产物：

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
r = json.loads(Path('runs/first_clip/result.json').read_text())
print('执行状态:', r['status'])
print('计数:', r['counts'])
print('警告:', r['warnings'])
PY
```

预期为 `completed`，计数包含 `frames: 48, events: 1, reviewed: 0`。它表示程序完成，不是视频质量通过。

## 3. 启动、打开并停止 Range 服务

仍在项目目录运行：

```bash
.venv/bin/python -m video_temporal_audit serve --directory . --port 8765
```

终端显示“本机报告服务”后会持续占用该窗口，这就是正常运行。打开浏览器，粘贴：

[http://127.0.0.1:8765/runs/first_clip/timeline.html](http://127.0.0.1:8765/runs/first_clip/timeline.html)

若要从终端打开，另开一个终端窗口执行：

```bash
open "http://127.0.0.1:8765/runs/first_clip/timeline.html"
```

服务只监听本机 `127.0.0.1`。它提供视频 HTTP Range：播放器可以请求目标时段的数据，而不必整段重新下载。首次操作优先用这个入口，不把双击本地 HTML 当成定位功能已经验收。GitHub 文件页展示 HTML 源码也不等于运行了时间线。

按下面顺序确认：

1. 等预览加载完成，观察页面显示已启用 Range 按需播放。
2. 点击 E001 的“回放此时段”或时间轨上的候选条。
3. 看到“已定位 E001”，播放器从约 **1.5 秒**开始播放；候选本身是 **2.0–2.25 秒**。按钮提前 0.5 秒，是为了观察事件前后的连续变化。
4. 若显示“尚未确认播放器跳转”，本次不能记为定位通过。等待预览加载、点“使用附带预览”再重试，按下一节排错。

可在第二个终端、相同项目目录用 HTTP 检查辅助判断服务是否正常；它不能代替浏览器观察：

```bash
curl -sS -D - -o /dev/null -H "Range: bytes=0-31" \
  "http://127.0.0.1:8765/runs/first_clip/preview.mp4"
```

预期响应含 `206 Partial Content`、`Accept-Ranges: bytes`、`Content-Range: bytes 0-31/...`。普通服务若没有 Range，页面会对不超过 **64 MiB** 的预览下载并核验 SHA-256，随后使用本机 Blob 播放；超过限制需要使用本项目 `serve`。

**停止服务：** 回到正在运行 `serve` 的终端，按 **Control+C**，等待命令提示符重新出现。关闭网页不会停止服务。下次查看报告时重新启动即可。若 8765 已被占用，改为 `--port 8766`，浏览器网址也改为 8766。

## 4. 理解页面上的两种时间与尾帧

| 名称 | 含义 | offset_flash 例子 |
|---|---|---|
| 源 PTS | 源视频中每帧的展示时间戳，可从非零甚至合法负值开始 | 首帧 5.0 秒，事件开始 7.0 秒 |
| 相对播放位置 | `源 PTS − 源首帧 PTS`，预览从 0 开始 | 事件在播放 2.0 秒 |
| 回放定位目标 | 相对事件开始减去 0.5 秒，最低为 0 | 从播放 1.5 秒开始回看 |
| 分析结束 | 末帧 PTS 加该帧显示时长；时长有时需要估计 | 源坐标结束 9.0，相对结束 4.0 秒 |

通过运行中的服务打开 [offset_flash 时间线](http://127.0.0.1:8765/examples/demo_v2/timing/offset_flash/timeline.html)可以查看该例。原始 MP4 的独立 FFprobe 结果为 `start_time=5.0`、**流 `duration=3.916667`**。源末帧没有正的显示时长，分析以相邻 PTS 间隔中位数补出约 0.083333 秒的尾帧显示，所以分析相对结束为 **4.0 秒**。修复后的预览明确编码这段估计尾帧，报告读回 `preview_end_s=4.0000003`，浏览器显示约 4.0 秒。

因此，4.0 秒是包含估计尾帧的分析/预览覆盖，**不是该原始 MP4 实测流时长**。查看 `source_end_is_estimated`、`timing_warnings`、`preview.source_last_duration_source`：此例分别为 `true`、有估计提示、`median_delta_ESTIMATE`。预览自己的末帧显示时长来自正的 `showinfo_duration`；这只证明预览确实实现了约定时间线。

VFR 指可变帧率，相邻帧的时间间隔不一样。程序保留实际 PTS，不能把帧号除以一个固定帧率当成时间。事件采用半开区间 `[start_s, end_s)`；两个仅在端点接触的区间不算时间重叠。0.00003 秒是预览映射验收容差，不是故障定位本身的精度保证。

默认使用附带预览即可。“核验并切换本机原片”会先核对媒体 SHA-256；选错片会保留当前播放器来源，文件不会上传。预览移除了音轨，所以本工具不用于判断口型或音画同步。

## 5. 从草稿到可交付的复核

连续回放后为 E001 选择结论：`confirmed`（确认是问题）、`intentional`（合法变化）或 `uncertain`（证据不足）。写明观察时段和画面依据。例如看到闪光后恢复正常，可以写“播放 2.0 秒处全画面突然变亮，随后恢复；前后运动连续”。这只是写法示例，应以自己实际观察为准。

1. 点击“保存本机草稿”。刷新同一地址，检查结论和依据是否恢复。草稿属于当前浏览器和站点；更换浏览器、端口或 `localhost/127.0.0.1` 地址可能看不到原草稿。
2. 点击“导出已完成复核 JSONL”。已选结论的条目都必须有依据，未选择的继续待办。确认下载文件实际存在；文件名形如 `test_source_1_flicker_<摘要前8位>_reviews.jsonl`。
3. 页面“导回复核 JSONL”只恢复草稿。下面的 CLI 命令才创建可保存、可复制的正式复核版。

在另一个终端回到项目目录，把 `--reviews` 后面的文件名替换成实际下载文件名；也可以将下载的文件拖进终端取得完整路径：

```bash
.venv/bin/python -m video_temporal_audit import-reviews \
  --report runs/first_clip/report.json \
  --reviews "$HOME/Downloads/实际下载的复核文件.jsonl" \
  --output runs/first_clip_reviewed
```

第一次已完成 E001 时，应返回 `imported: 1, reviewed: 1, pending: 0, algorithm_events_preserved: true`。打开 [正式复核时间线](http://127.0.0.1:8765/runs/first_clip_reviewed/timeline.html)，并检查 `report.json` 中的 `human_reviews`。新目录还有 `reviews.jsonl`。原报告不会被覆盖，判为“合法变化”也不会删掉算法报警。

输出必须是新的或空的**独立目录**，不能等于原目录，也不能放在原报告目录内部。追加或改判时，以现有复核版的 `report.json` 为输入、再输出一个新目录；同一事件的新合法复核会替换旧复核，同一导入文件中重复事件则拒绝。

每一行 JSONL 必须恰好包含下面八个字符串字段，不要另加列：

`schema_version, clip_id, event_id, media_sha, config_digest, report_digest, decision, evidence`

协议版本为 `video-temporal-review-v2`。`media_sha` 绑定原片；`config_digest` 绑定有效规则、补偿/切镜开关及版本；`report_digest` 绑定该片及事件数组。导入还会重新计算报告的配置/事件摘要、核对预览哈希，并校验报告中已有的复核。错片、错配置、未知事件、重复事件、数组/数字字段、空依据或超过 4000 字的依据会在复制前拒绝。既有复核也不能含未知事件来制造错误计数。

复核记录标记为 `human_unverified`、身份未验证；它与算法候选分开存放，不自动改变 `dataset.json` 的参考标签，也不自动重算 TP/FP/FN。

## 6. 接自己的合法视频

先在本机准备一段自己拍摄或获准处理的短视频，记录来源、使用许可和截取偏移。可放进已忽略的 `data/private/`；不要把个人原片放进公开 `examples/`。第一次建议 5–20 秒、1080p 或更小：30 fps 下 40 秒已达 1200 帧，60 fps 下 20 秒就达上限。

```bash
.venv/bin/python -m video_temporal_audit analyze \
  --video "/完整路径/我的短片.mp4" \
  --motion-compensation on --output runs/my_video_01
```

输入可以是 FFmpeg 支持的格式，程序取第一路视频流。限制为最多 **1200 帧**、每帧总像素不超过 **8,847,360（4096×2160）**；解码超时默认 120 秒。若超限，先准备并记录一份更短或更小的副本；程序不会把截断结果标成完整分析。源文件不被修改。

省略 `--config` 时使用预设规则，实际值写入 `report.json`。示例冻结配置只说明受控夹具上的校准结果，不能因此声称自己的拍摄或生成视频也经过校准。想比较补偿影响，对同一文件使用相同配置分别运行 `on/off` 并写入不同目录；不要同时改阈值和补偿开关。

如果要计算事件指标，需要另建自己的数据集并提供**源 PTS 坐标**中的故障区间标签，保留无缺陷片的空 `truth: []`，按原始拍摄来源拆分校准与测试，先校准后评价。直接运行 `analyze` 没有人工参考事件，因此不产生自己视频的准确率。具体扩展验收见 [MY_WORK](../MY_WORK.md)。

## 7. 常见报错

CLI 的已处理输入错误打印 `ERROR: ...` 并返回 **2**；成功通常返回 **0**。可在命令结束后立即运行 `echo $?` 查看上一个命令的退出码。不要用目录存在或旧报告存在判断本轮成功，失败时保留日志并检查 `result.json` 是否属于这次运行。

| 提示或现象 | 处理方式 |
|---|---|
| `command not found: python3.12` | 安装 Python 3.12，重新打开终端，先通过版本检查。 |
| `.venv/bin/python: no such file` 或 `No module named video_temporal_audit` | 回到项目目录，检查 `.venv`，执行本指南的创建环境与安装命令。 |
| `Input video does not exist` | 改成实际完整路径，含空格时加双引号；不要照抄占位文件名。 |
| `FFmpeg could not decode the first video stream` | 核对是否损坏、只有音轨或编码无法读取；不要把扩展名改成 MP4 当成修复。 |
| `Analysis output must be new or empty` / `Review output must be new or empty` | 使用另一个新目录；既有文件或非空目录被保护。 |
| `Use a separate new review output directory` | 将复核输出放在原报告目录外，例如并列的 `runs/first_clip_reviewed`。 |
| `Frame limit exceeded` / `Frame pixel limit exceeded` / `Decode timeout` | 使用更短或更小的授权副本，记录截取起点和转换过程，再开新输出目录。 |
| `Non-increasing PTS` / `Source resolution changed` | 重复/倒退时间戳或中途变分辨率不能直接分析；保留原件，对副本明确规范时间或拆段并记录协议。合法负 PTS 本身不属于此错误。 |
| `Single frame has no positive display duration` | 该单帧文件缺少可用显示时长，需在保留原件基础上明确制作协议；不能猜时长后称其为实测。 |
| `Frozen config digest mismatch` / `Report config binding digest mismatch` | 配置或元数据与摘要不一致。使用原始匹配配置，或重新校准/分析；不要手工改摘要蒙混通过。 |
| `Review binding mismatch` / `Report event binding digest mismatch` / `Preview media hash mismatch` | 报告、复核、预览并非同一套或内容已改变。找回对应原件，必要时重新分析和复核。 |
| `Review fields must be strings` / `unknown event` / `Duplicate event review` | 从对应时间线重新导出；不能将事件 ID 写成数组，也不能拼接其他片的 E001。 |
| `Review requires a concrete evidence note` / `no completed decisions` | 至少复核一项并写实际画面依据；空白备注或空文件不能导入。 |
| 网页打不开、404 | 确认服务仍运行、从项目根 `--directory .` 启动、端口及输出路径一致。 |
| `Address already in use` | 换一个端口，例如 8766；同步修改浏览器地址。 |
| 草稿未恢复、文件摘要不可用、定位未确认 | 用本机 HTTP 服务打开；确认同一浏览器和同一地址；必要时恢复附带预览或导入已导出的 JSONL。 |

事件匹配函数还拒绝非数值、布尔、NaN、无穷、零、负数或大于 1 的 tIoU 门槛，合法范围为 `(0,1]`。当前 CLI 没有自定义 `--tiou` 参数；公开评测固定用 `0.3`。错误配置对象（例如 `config: null`）也会明确拒绝，不能当作默认配置继续。

## 8. 完整演示与验收边界

一个短片流程通过后，可以选择运行完整示例；这不是首次查看的前置步骤：

```bash
.venv/bin/python -m video_temporal_audit demo-v2 --output runs/full_demo_01
```

保持服务运行后，打开 [完整演示入口](http://127.0.0.1:8765/runs/full_demo_01/index.html)。它会生成 28 段事件夹具、校准/测试结果以及额外时间边界检查。不同电脑耗时不同，不用历史运行时长当作性能保证。

本次文档命令验收实际使用 1 个已有短片，在新目录完成 48 帧/1 候选分析、合法复核导入、4 类退出码 2 的拒绝检查、HTTP 206 Range 读取及服务停止。验收复核行使用明确标注的 `uncertain` 协议测试数据，**没有真人画面评分**。没有新跑全套测试、完整 demo、全新依赖安装或浏览器；已有完整验证见 [verification_v2.json](../verification_v2.json)。
