# MinerU 4.2.3 部署与使用

## 1. 安装与下载模型

在独立的 MinerU 目录使用 `uv` 创建 Python 3.12 环境。
~~~powershell
uv venv --python 3.12 .venv
uv pip install --python .\.venv\Scripts\python.exe --torch-backend=auto "mineru[torch]==4.2.3"
~~~

下载并校验 **Standard** 所需的两套权重。命令会一起准备 `MinerU-4_models_torch` 和 `MinerU2.5-Pro-2605-1.2B-GGUF`。

~~~powershell
.\.venv\Scripts\mineru-kit.exe models download --tier standard --small-backend torch --vlm-engine llama-cpp --source auto
.\.venv\Scripts\mineru-kit.exe models verify --tier standard --small-backend torch --vlm-engine llama-cpp
~~~

如果自动下载源访问失败，可将 `--source auto` 改为 `--source modelscope` 后重试。

## 2. 选择解析档位

| 档位 | 处理方式 | 适用场景 |
| --- | --- | --- |
| 极速解析（`flash`） | 以原生提取为主，优先使用 PDF 文字层 | 快速预览、结构简单且可选中文字的 PDF |
| 基础解析（`basic`） | 用传统小模型做版面、OCR、公式和表格解析 | 资源有限、版面较简单的 PDF 或扫描件 |
| 标准解析（`standard`） | 小模型做版面检测，视觉语言模型处理需要识别的文字、公式和表格 | 日常 PDF、扫描件以及含公式和表格的资料 |
| 高级解析（`advanced`） | 让视觉语言模型参与更多步骤，包括版面分析 | Standard 处理困难的页面，需要时再对比试跑 |


## 3. 使用命令行转换

在执行解析或启动服务的 PowerShell 中设置后端。新开终端时，重新执行这两行。

~~~powershell
$env:MINERU_MODEL_SMALL_BACKEND = "torch"
$env:MINERU_MODEL_VLM_ENGINE = "llama-cpp"
~~~

将下面的输入文件名换成实际路径。
~~~powershell
# 转换全文，打包 Markdown、结构化 JSON 和图片
.\.venv\Scripts\mineru-kit.exe parse ".\test.pdf" --tier standard --format zip -o ".\test.zip"
~~~

## 4. 启动 MinerU 服务

在已设置第 3 节后端变量的 PowerShell 终端运行：

```powershell
.\.venv\Scripts\mineru-kit.exe api-server --host 127.0.0.1 --port 8001 --tier standard
```

这条命令启动 MinerU HTTP 服务，支持 `flash`、`basic` 和 `standard`。需要开放 `advanced` 时，将 `--tier standard` 改为 `--tier advanced`。
