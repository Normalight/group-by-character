# group-by-character

递归扫描图片，并使用 PP-OCRv6 recognition 模型将单字图片按识别结果归档。

这个项目只处理“已经切好的单字图片”，不会再次运行 DBNet 检测或切字，也不启用 MegaHan。

## 环境

在项目约定的 conda 环境中安装依赖：

```bash
conda activate chardet
python -m pip install -r requirements.txt
```
默认使用本项目目录下的模型，运行时无需安装同级项目。**模型不上传 GitHub，首次运行前请单独下载：**

```text
models/ppocrv6_rec/small/inference.onnx
models/ppocrv6_rec/small/inference.yml
```

官方来源：[PaddlePaddle / PP-OCRv6 small rec](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx/tree/main)。

- [下载 inference.onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx/resolve/main/inference.onnx)
- [下载 inference.yml 字符字典](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx/resolve/main/inference.yml)

两个文件都放入 `models/ppocrv6_rec/small/`，保持原文件名。也可以用下载工具：

```bash
python -m pip install huggingface_hub
python -c "from huggingface_hub import hf_hub_download; [hf_hub_download('PaddlePaddle/PP-OCRv6_small_rec_onnx', filename=f, local_dir='models/ppocrv6_rec/small') for f in ('inference.onnx', 'inference.yml')]"
```

也可以通过 `--model` 和 `--yaml` 显式指定模型。

## 运行

先只统计输入目录中的图片，不加载模型、不写输出：

```bash
python group_by_character.py \
  --input /path/to/crops \
  --dry-run
```

正式归档：

```bash
python group_by_character.py \
  --input /path/to/crops \
  --output /path/to/crops-grouped \
  --model models/ppocrv6_rec/small/inference.onnx
```

程序会递归扫描输入目录下的 PNG/JPG/JPEG/BMP/TIF/TIFF，忽略隐藏文件和隐藏目录；如果
输出目录位于输入目录内，也会自动排除输出目录。

输出结构：

```text
输出目录/
  按字/
    甲/
    待复核/
  归并清单.json
  字形归并.xlsx
```

“待复核”包括空结果、低置信度、多字符、非法字符和模型异常。
Excel 的“字形归并”工作表按字一行、下一行记录每张图片的相对出处，“清单”工作表保存
逐图字段，便于筛选和复核。

## 测试

```bash
conda run -n chardet python -m pytest -q
```

## Qt 交互界面

双击 `start_gui.bat`，或在项目目录执行：

```bash
conda run --no-capture-output -n chardet python app.py
```

1. 选择 [char-detection-main](https://github.com/Normalight/char-detection-main) 实际保存结果的目录（例如 `interactive_output`、`output_v6small`），也可选择单页或 PDF 的结果目录。
2. 点击“扫描数量”，确认切片数量；选择输出目录，点击“开始识别归档”。
3. 完成后选择表格行预览图片，可搜索字符、待复核或来源路径。输入正确单字并点击“应用改字”。
4. 点击“保存复核结果”，重新生成按字目录、JSON 和 Excel；人工确认的记录标为 `manual`，保留原始模型分数。

模型加载、识别及导出在独立进程中运行。点击取消会立即终止工作进程，不等待当前推理或 Excel 写入结束；取消任务的临时文件在后台清理，已保存结果保留。只有成功完成的任务才发布到输出目录。

### 上游结果兼容

默认 `--input-format auto`：递归扫描时，只要发现 `*_crop_数字` 或 `char_数字` 切片，就只处理这些切片，排除 `*_overview.png` 等整页图。支持图片结果目录、PDF 的 `page_001` 多层目录，以及旧版切片命名。

- `--input-format crops`：严格只处理上述命名的切片。
- `--input-format images`：处理所有图片，适合自行命名的单字切片。

自动模式没有发现切片命名时会处理全部图片；严格切片筛选可由开发者在 `config.py` 中将 `DEFAULT_INPUT_FORMAT` 改为 `crops`。上游 JSON 保存的是标注框而非可靠的逐字识别结果，本工具对最终切片重新识别，通过相对路径保留页面出处，不会修改上游文件。

界面拒绝覆盖非空的普通文件夹；已有归并结果会在替换前询问。命令行沿用原有整体替换输出目录行为，请指定专用输出目录。


## 模型准备与 Windows 打包

识别模型、字典配置、输入格式均由 `config.py` 管理，界面无需设置。
默认模型及配套字典位于 `models/ppocrv6_rec/small/`，请按前文链接下载到本地；打包时会复制到应用资源中。
源码运行按项目目录定位，打包运行按 PyInstaller 的 `_MEIPASS` 定位，不依赖工作目录或上游路径。

在 `chardet` 环境安装 PyInstaller 后，双击 `build_windows.bat`，或执行：

```bash
conda run --no-capture-output -n chardet python -m PyInstaller --noconfirm app.spec
```

发布时复制整个 `dist/group_by_character/` 文件夹，运行其中的 `group_by_character.exe`。
打包配置强制包含 ONNX 和 YAML；缺少任一文件时立即停止打包。

### 删除错误切片

复核表格支持 Ctrl / Shift 多选。点击“删除选中项”或在表格内按 Delete，即可从本次归并结果移除所选项；“撤销删除”可逐次恢复。筛选隐藏的行不会被删除。

点击“保存复核结果”后，按字目录、JSON 和 Excel 同步更新；全部删除也可以保存为空结果。删除不会修改输入目录中的原始切片。保存成功后清空删除撤销记录，重新运行识别会再次扫描原始切片。


## macOS 通用应用（Intel / M 系列）

执行 `bash build_mac.sh` 构建一个适配两种芯片的 `.app` 与发布 ZIP；无需开发者证书。使用者无需安装 Python。详见 [Mac 安装、使用与打包说明](MAC使用说明.txt)。源码启动脚本为 `start_gui.sh`。


## macOS

激活 Python 3.10 / 3.11 环境后执行 `bash start_gui.sh`。
构建可使用 `bash build_mac.sh arm64`（Apple Silicon）或 `bash build_mac.sh x86_64`（Intel）；
不带参数构建双架构包。详细说明见 [macOS 使用说明](MAC使用说明.txt)。

## 仓库范围

保留应用源码、打包脚本、自动化测试及必要固定样例。
运行输出、临时试图、缓存和本机环境不纳入版本管理。


## GitHub 自动打包

在 GitHub 发布 Release（正式版或预发布版）时，自动运行 **Build desktop apps**，分别构建：

- Windows x64：解压后运行 exe，保留整个文件夹。
- macOS Intel（x86_64）：使用 Intel 原生 runner 构建。
- macOS Apple Silicon（arm64 / M 系列）：使用 ARM 原生 runner 构建。

Mac 需要 macOS 14 或更新版本。每个 Mac ZIP 内都有 `MAC使用说明.txt`，
只说明首次允许打开未使用 Developer ID 签名及公证的应用，以及软件使用方式。
构建脚本保留本地完整性签名，不需要 Apple 开发者账号。

在 Actions 的成功运行页面下载 Artifacts（保留 14 天）；下载到的就是应用 ZIP，解压一次即可使用。
三种构建全部通过后，自动将 应用 ZIP 上传到触发本次构建的 Release。
保存草稿、推送代码或单独推送标签均不触发打包；不会由流水线自动创建另一个 Release。
标签需使用 `v主版本.次版本.修订号`，如 `v1.0.0` 或 `v1.0.0-rc.1`。
请从包含当前工作流的提交创建版本标签；每次构建使用该 Release 标签对应的源码。
也可在 Actions 手动运行验证构建，文件名使用 `dev-提交SHA`，仅上传 Artifacts。
私有仓库的构建产物与 Release 仍需相应仓库访问权限。

CI 使用 Python 3.11 和固定版本依赖；模型由 `packaging/download_models.py`
从官方 Hugging Face 固定提交下载，包含在应用中，不提交到源码仓库。
每个构建会运行应用测试和真实打包程序的 `--smoke-test`；任一步失败都不会向已发布的 Release 上传安装包。

本地构建仍可运行 `bash build_mac.sh arm64`、`bash build_mac.sh x86_64`；
双架构通用包可在具备两种 Python 3.11 与 Rosetta 的 M 系列 Mac 上运行 `bash build_mac.sh universal`。

安装包命名统一为 `归并-版本标签-平台-架构.zip`，不额外生成校验文件或嵌套压缩包。
例如本仓库的 `v1.0.0`：

- `归并-v1.0.0-windows-x64.zip`
- `归并-v1.0.0-macos-x86_64.zip`（Intel）
- `归并-v1.0.0-macos-arm64.zip`（M 系列）

文件名以标签为准，与可自由填写的 Release 标题无关；应用内名称保持中文。

Mac ZIP 根目录只有 `字形归并工具.app` 与 `MAC使用说明.txt`，解压后直接打开应用；不包含外层目录、启动脚本或依赖清单。
本地构建通过 `PACKAGE_VERSION=v1.0.0` 指定包名版本，未指定时为 `v0.0.0-dev`。


## 账号登录与保护打包

启动时需要登录统一账号服务，默认 `http://127.0.0.1:8765`，也可在登录窗口填写服务器 IP + 端口。管理员可在该地址的网页后台分配软件权限、停用账号、设置有效期或重置密码。客户端每 60 秒检查授权，断网缓冲 5 分钟；锁定后保留保存当前成果的入口。

在本项目根目录安装 `requirements.txt` 即可安装 `vendor/` 中的共用认证包。认证包与服务端源码位于工作区相邻的 `hanzi-auth/`，完整本机部署说明见该目录的 README.md；此软件仓库的构建本身不依赖相邻目录。

平台打包使用免费开源的 Cython，将主体 Python 模块及账号模块编译成原生扩展（Windows `.pyd`、Mac `.so`），由 PyInstaller 打包。无需付费混淆许可证。构建默认开启保护，生成 `build/code-protection/manifest.json`；编译失败会中止。Windows 构建需安装 Visual Studio C++ Build Tools（MSVC 与 Windows SDK），Mac 需 Xcode Command Line Tools。各架构分别编译。仅开发调试可显式设置 `HANZI_PROTECT=0`。交付包不包含主体 Python 源码或其字节码；保留最小多进程启动入口。编译保护提高逆向成本，不包含 ONNX 模型加密；生成的 C 文件和源码暂存仅保留在 build 中，不应随发布包分发。


## 登录日志和 GitCode 更新

账号后台提供登录日志，记录时间、账号、软件、来源 IP、结果和客户端版本，支持筛选与翻页。密码和会话令牌不会进入日志。

软件登录后自动检查一次更新，也可选择“帮助 → 检查更新”。管理员在账号后台按软件、平台填写公开 GitCode 发行版附件链接、版本、大小和 SHA-256。客户端完成下载校验后将新版本安装到独立目录，保留旧版本和当前工作，再由用户打开新版本。

发布时必须设置 `PACKAGE_VERSION`，构建会生成 `build_info.json`。可用 `python packaging/release_info.py <安装包.zip> --product group-by-character --target windows-x64 --version v1.0.0` 计算大小和校验值；Mac 的 target 为 `macos-arm64` 或 `macos-x86_64`。GitCode 仓库创建、标签及附件发布步骤见工作区 `hanzi-auth/README.md` 的“GitCode 发布与软件更新”。

### GitCode 发行版同步

发布 GitHub `vMAJOR.MINOR.PATCH` Release 后，Actions 构建三个平台安装包，上传 GitHub，再复用同一批 Artifact 上传 GitCode。需要仓库变量 `GITCODE_OWNER`、`GITCODE_REPO` 和 Secret `GITCODE_TOKEN`。同步可重跑，已存在的同名附件保留；替换已发布内容应使用新版本号。

同步结果 `gitcode-release-metadata` Artifact 包含三个附件的公开下载链接、文件大小和 SHA-256，可填写到认证后台。GitCode 仓库需允许用户公开下载；凭据仅用于 CI 发布，不放入客户端。
