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

## 5. 接入 SAG 后端

在 `apps/api/.env`（或根 `.env`）中配置自部署 MinerU 4.2+ Tasks API：

```dotenv
SAG_DOCUMENT_PARSER=mineru
SAG_MINERU_PROVIDER=self_hosted
SAG_MINERU_BASE_URL=http://127.0.0.1:8001
SAG_MINERU_ALLOW_PRIVATE_BASE_URL=true
# 可选：指定解析档位（flash/basic/standard/advanced），留空使用服务端默认
# SAG_MINERU_TIER=standard
# 可选：若启动 api-server 时配置了 --api-key，则在此填入同一 Key
# SAG_MINERU_API_KEY=
```

> **Docker 部署下的 `127.0.0.1` 可达性说明**：
> - 若 SAG API 与 MinerU 同在宿主机直接运行，使用 `http://127.0.0.1:8001` 即可。
> - 若 SAG API 运行在 Docker 容器内而 MinerU 运行在宿主机上，容器内的 `127.0.0.1` 指向容器自身而非宿主机，无法访问宿主机服务。此时请将 MinerU 启动地址改为 `--host 0.0.0.0`（或宿主机局域网 IP），并在 SAG 配置中使用 `SAG_MINERU_BASE_URL=http://host.docker.internal:8001`（或宿主机局域网地址），同时保持 `SAG_MINERU_ALLOW_PRIVATE_BASE_URL=true`。Linux Docker 如未默认解析 `host.docker.internal`，需在 compose 中为 API 服务添加 `extra_hosts: ["host.docker.internal:host-gateway"]`。
> - 若应用设置页此前保存过解析器配置，需同步更新已保存的值并在导入 PDF 前核对生效配置。

