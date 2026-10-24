# Linux MPEG-TS 解码兼容处理

Ubuntu 24.04.5 的实际 CI 暴露一个依赖运行时问题：`imageio-ffmpeg==0.6.0` 捆绑的 Linux `FFmpeg 7.0.2-static`（johnvansickle 构建）读取测试生成的负时间戳 MPEG-TS 时，PNG 输出与 null 输出都返回 `-11`（SIGSEGV），且 stderr 为空。其余 59 项测试通过。见[初次诊断运行](https://github.com/ngna5829-debug/video-temporal-audit/actions/runs/40085257610)。

[单变量对照运行](https://github.com/ngna5829-debug/video-temporal-audit/actions/runs/40085747227)保留相同 4324 字节输入、相同命令，仅为 FFmpeg 子进程设置 `GCONV_PATH=/dev/null`。PNG 与 null 两路均返回 0，实际得到 8 张 PNG；两路 showinfo 的原始 PTS 都是 `[-2, -1.916667, -1.833333, -1.75, -1.666667, -1.583333, -1.5, -1.416667]`。输入在诊断前后的 SHA-256 均为 `7b53286f709c1dee5b4812a6b22f6e811f279e70842955042cf9344e67a2a5fb`。该运行仍报告测试失败，因为诊断分支没有把失败转换成通过。

运行时代码只在以下条件全部满足时设置该子进程环境：Linux、可执行文件位于当前 `imageio_ffmpeg` 包的 `binaries` 目录、版本首行为 `7.0.2-static` 且含 johnvansickle 来源标识。源视频解码与预览编码都使用此处理；进程全局环境、输入字节、源 PTS、检测与匹配规则均不修改。生效时，`report.json` 及其 `preview` 中的 `ffmpeg_compatibility` 字段记录该配置和限制。系统 FFmpeg、其它版本以及 macOS/Windows 不自动使用它。

这是一项有同输入实验支持的兼容处理，尚未通过原生调用栈或模块跟踪确认崩溃内部机制，也不保证覆盖所有容器、编解码器或 Linux 发行版。`GCONV_PATH` 会改变字符转换配置的查找方式，服务名等文字元数据的字符转换可能不同；本工具只对视频画面与时间轴作分析。GNU/Linux 文档说明，设置此变量会绕过 gconv 配置缓存，但仍可能搜索系统默认配置，因此不能把它描述为“禁止所有 gconv 模块加载”。见 [iconv 环境变量说明](https://man7.org/linux/man-pages/man1/iconv.1.html)。

外部[同类症状讨论](https://github.com/honey720/chzzk-vod-downloader-v2/issues/94#issuecomment-5090752830)提供了实验线索；其中的机器人诊断不是本项目独立确认原生根因的证据。修复后的完整测试与 CLI 是否通过，应按对应新 commit 查看 [CI](https://github.com/ngna5829-debug/video-temporal-audit/actions/workflows/tests.yml)。


修复程序在提交`56dca8ca9cc2c48d8eba48763faafe08501c5770`的[Ubuntu实际CI](https://github.com/ngna5829-debug/video-temporal-audit/actions/runs/40086047531)通过：61项Python测试、12项JavaScript断言、包安装与CLI短片检查均成功；原负PTS用例完整执行。该源码的本机61项也通过，公开config/calibration/metrics逐字节保持。可读摘要见[UBUNTU_CI_FIX50.json](UBUNTU_CI_FIX50.json)。后续只补教材和证据的提交仍须看它自己对应的CI。
