# 字形归并项目上下文

## 职责与入口

处理已经切好的单字图片：递归发现 → PP-OCRv6 recognition → 按字归档 → 人工复核 → JSON / Excel。输入可以来自相邻字符检测项目，但运行时不导入该项目源码。

- `app.py`：桌面启动入口。
- `ui/window.py`：PySide6 界面、表格筛选、改字、删除/撤销、登录与更新接入。
- `group_by_character.py`：CLI 启动入口。
- `grouping/service.py`：`GroupRecord`、图片扫描、归并导出与 CLI 参数处理。
- `grouping/recognition.py`：单字 ONNX 模型加载、预处理、CTC 解码。
- `ui/task_worker.py`：Qt 协调器，用 `spawn` 创建独立进程、收取管道结果、发布输出。
- `grouping/process_tasks.py`：子进程任务入口，负责扫描、模型加载、识别和生成临时结果。
- `config.py`：模型路径、识别和输入格式默认值；兼容源码与 PyInstaller `_MEIPASS`。
- `app.spec`、`packaging/`、平台构建脚本：打包、自检和发布。

默认模型及配套字典为 `models/ppocrv6_rec/small/inference.onnx`、`inference.yml`，均需准备，下载说明见 README。这里只做单字识别，检测和切字属于上游。

## 行为约束

- `auto` 输入模式发现 `*_crop_数字` 或 `char_数字` 时优先只收切片；`crops` 严格筛选，`images` 处理所有支持图片。排除隐藏路径及位于输入内部的输出目录。
- 原始切片保持不变；改字、删除、撤销只修改本次归并记录。人工改字标记 `manual` 并保留原模型分数，保存时同时更新按字目录、清单和 Excel。
- 空结果、低置信度、多字符、非法字符及模型异常进入待复核。不要把不确定结果强行归入确定单字。
- 重任务使用独立进程，取消可以终止正在推理或导出的进程；子进程只写本次临时目录。父进程仅在成功完成后替换正式输出，失败回滚，取消不破坏已保存结果。
- GUI 拒绝覆盖非空普通目录，已有归并结果需按界面确认；CLI 会整体替换目标输出目录，测试和试跑必须用专用临时目录。
- 登录守卫锁定时停止任务，并保留保存已有复核结果的入口。`closeEvent` 负责未保存工作与更新重启之间的协调；用户取消关闭时清除 `restart_requested`。
- 多进程打包入口保留启动保护和 `freeze_support` 逻辑，避免冻结应用递归启动窗口。

## 开发与验证

在本目录、Python 3.11 环境执行：

```sh
python -m pip install -r requirements-dev.txt
python app.py
python group_by_character.py --input /path/to/crops --dry-run
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

测试重点：`test_group_by_character.py` 覆盖识别/清单/导出，`test_task_worker.py` 覆盖进程和输出安全，`test_app.py` 与 `test_desktop_lifecycle.py` 覆盖复核和窗口生命周期。打包改动检查 protection、release、public publish 相关测试及构建自检。

Windows：`build_windows.bat`；macOS：`bash build_mac.sh`（默认 arm64）。Windows 输出 `dist/group_by_character/` 必须整体分发；各平台在原生环境构建。

Mac arm64 的 `packaging/mac.spec` 通过 `slimming.py` 裁剪已验证版本的 Qt/ONNX 依赖。变更需验证图片解码、冻结子进程推理及 JSON/Excel 导出；对照开关和裁剪清单说明见 README。

## 共享依赖与维护

认证与更新通过 `vendor/` wheel 接入；更新实现位于独立的 `hanzi-update`，通过 `attach_updates` 接入每个窗口。公共打包脚本的源头是相邻 `hanzi-auth/tools/desktop_packaging/`，改动后用该项目的 `tools/sync_desktop.py` 同步；升级 wheel 还需更新普通及平台依赖文件。Cython 保护、模型收集及 `build_info.json` 必须覆盖实际使用模块。

仅提交源码、测试、打包配置及必要分发依赖。模型、用户输入输出、生成的 Excel、缓存、build/dist 不作为源码提交。修改扫描规则、记录结构、任务取消或导出行为时同步本文件与 README。

## 提交说明

每次提交必须根据本次实际 diff 编写明确的 commit message。标题使用 `类型(范围): 中文改动摘要`，类型按实际选择 `feat`、`fix`、`refactor`、`docs`、`test`、`build` 或 `chore`；范围填写实际模块。避免只有“更新”“修复问题”或文件列表的标题。

涉及行为变化、多个模块或共享依赖时，正文说明改了什么、为什么改、用户或调用方受到什么影响，以及执行过的验证和结果；未执行的验证及原因如实注明。仅记录该提交包含的内容，不把已有但未纳入提交的工作或计划写成已完成。跨仓库改动分别编写对应提交说明。

## 客户端更新记录

每次客户端发版前，必须在本仓库编写 `RELEASE_NOTES_v<版本号>.md`，随该版代码提交；按需包含新增功能、体验改进、问题修复，以及兼容性、升级步骤或已知限制。使用面向用户的中文描述实际变化，不以 commit 列表或笼统的“优化体验”代替。

更新记录的版本必须与安装包 `build_info.json`、客户端版本和发布标签中的产品版本一致。只记录本版已完成的变化；共享认证、更新包或打包变化若影响用户，也应在本客户端记录。

发布 GitHub / GitCode Release 时使用该版本更新记录作为正文；公开分发仓库的产品前缀标签沿用相同产品版本和说明。发版前核对实际 Release 正文及客户端可见更新说明，确保分发/镜像过程保留记录；工作流自动生成的 notes 不能代替人工编写的版本说明。

## 结构维护

Python 文件使用 `snake_case.py`，按职责命名；外部入口、软件标识、模型目录和导出格式保持稳定。开发测试依赖放在 `requirements-dev.txt`，平台共同构建依赖放在 `packaging/requirements-build.txt`，平台文件只写包含与差异。`packaging/` 中的公共脚本从认证项目 `tools/desktop_packaging/` 同步，不在副本上独立修改。在认证项目运行 `python tools/sync_desktop.py --check` 检查漂移。源码地图见 README。

源码按职责收敛到包，根目录仅保留启动入口和配置。公共工具位于 `utils/`（如适用），业务包不使用模型历史名称。打包保护自动发现根目录下含 `__init__.py` 的源码包，并要求实际 `ui/window.py` 进入保护清单。测试和打包自检直接引用对应包。

## 保存性能

- 保存复核结果通过 `grouping/save_cache.py` 校验输入、归档文件和缩略图状态；未变资源从旧输出硬链接到本次临时目录，不支持硬链接时回退复制。不得硬链接原始输入，也不得原地改写复用文件。
- `.thumbnails/` 和 `.save-cache.json` 为可重建缓存；复核内容与文件状态不变时 GUI 跳过重复保存。改字仍重新生成 Excel，复用缩略图并在内存中打包。
- Excel 打包启用 ZIP64，支持超出普通 ZIP 大小限制的批量导出；回归通过缩小 ZIP 阈值验证真实打包和读取。
- 保留临时目录构建、父进程发布和取消回滚流程；新增回归见 `tests/test_incremental_save.py`。

## 历史 ZIP 更新暂存

以下暂存行为适用于保留的旧更新协议。

自动更新的下载包、解压内容、脚本、日志及旧程序备份全部位于软件内部 `.hanzi-update-*`；更新保留安装根目录，只替换新版程序项并保留用户文件。新版完成登录后清理匹配的已完成更新。无法定位可写安装目录时提示处理。原生生命周期测试以安装目录作为助手工作目录，验证原位替换。

## 原生更新

认证、会话与更新前置检查默认连接 `https://platform.myhanzi.cn`，保留 `/api/secure` 加密协议。旧公网 IP 的显式配置由认证包转换为 HTTPS 域名；公开 feed 与安装包仍在 GitCode。

`hanzi-update` 的 attach_updates 使用 WinSparkle / Sparkle；保留现有按钮和 closeEvent 保存契约。登录后由认证守卫先检查公开 feed 与安装包是否就绪，随后才打开原生界面；GitCode 地址不在界面展示。Windows 当前用户安装器和 Mac 外层 app 的签名/公证辅助源在 hanzi-auth/tools/desktop_packaging/native_*，通过 sync_desktop.py 同步。工作流从 packaging/native_update_public.json 的 `gitcode_feed_base` 生成 HANZI_UPDATE_FEED，并配合 HANZI_UPDATE_PUBLIC_KEY 生成原生更新产物。PACKAGE_VERSION 派生原生版本信息，配置与已构建产物必须一致。原生 CI 用 `GITCODE_TOKEN` 直接上传并校验 GitCode 安装包与 feed，认证服务镜像器可补同步；`feed_base`（GitHub）供旧版客户端回退。Mac Bridge 隐藏历史按钮，两端内嵌中文说明。详细流程与尚未完成的真机验收见 ../hanzi-update/docs/update/release.md 和 test_report.md。

Mac 原生更新构建支持 HANZI_MAC_SIGNING=adhoc，无 Apple 签名标识时默认采用此模式；使用本地 ad-hoc 签名并保留更新包 Ed25519 校验。developer-id 模式另需证书及公证 profile。

原生发布使用 `.github/workflows/native-build.yml`，传入已提交更新说明的版本。公开更新配置位于 packaging/native_update_public.json；SDK 从官方固定版本下载并校验 SHA-256，Mac bridge 源从 hanzi-update 同步。仓库变量 NATIVE_UPDATES=true 时旧 build.yml 停用。安装包资产统一为 `<软件>-vX.Y.Z-<平台>`（Windows 原生安装器 `.exe`、Mac `.zip`），与公开仓历史 Release 命名一致；`dist/` 每个平台只留一个安装包，`build_mac.sh` 在设置 HANZI_UPDATE_FEED 后不再另打包，避免同名 ZIP 覆盖签名更新包。默认运行时只构建/验收并上传 Artifact，更新包由本机钥匙串签名后发布；勾选 `publish` 输入后改用仓库 Secrets 的 `HANZI_UPDATE_PRIVATE_KEY` 签名，`packaging/native_publish.py` 发布 `<软件>-vX.Y.Z` 与 `<软件>-stable`，不勾选时私钥不进入 CI。
