"""SAG 集成测试：用 qwen3-vl-embedding 走通「建信源 → 入库 → 检索」。

运行前需要已启动一个使用多模态 embedding 配置的后端实例，例如::

    SAG_EMBEDDING_MODEL=qwen3-vl-embedding \
    SAG_EMBEDDING_SCHEMA_DIMENSIONS=1024 \
    SAG_EMBEDDING_REQUEST_DIMENSIONS=1024 \
    ... uvicorn sag_api.main:app --port 8001

用法::

    uv run python scripts/test_vl_integration.py --base http://127.0.0.1:8001

脚本会自动创建临时信源、灌入一段文本、等待切片完成后检索，并打印命中结果。
不会改动已有信源。
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

SAMPLE_TITLE = "城市图书馆服务指南"
SAMPLE_TEXT = """城市图书馆的儿童阅览室在二楼。读者可以在一楼服务台办理借书证。
城市图书馆每周三下午举办儿童阅读活动，由馆员李明主持，地点在二楼儿童阅览室。"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--user", default="vl-test")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    base = f"{args.base.rstrip('/')}/api/v1"
    client = httpx.Client(timeout=120)

    print(f"1) 登录 {base}")
    response = client.post(f"{base}/auth/login", json={"name": args.user})
    response.raise_for_status()
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    print("2) 读取能力")
    caps = client.get(f"{base}/system/capabilities", headers=headers).json()
    print(f"   embedding_model={caps.get('embedding_model')}")
    print(f"   llm_model={caps.get('llm_model')}")

    print("3) 创建临时信源")
    if caps.get("embedding_model") != "qwen3-vl-embedding":
        raise RuntimeError("Expected an isolated Qwen3-VL test instance")
    source = client.post(
        f"{base}/sources", headers=headers, json={"name": SAMPLE_TITLE}
    ).json()
    source_id = source["id"]
    print(f"   source_id={source_id}")

    print("4) 灌入样张文本")
    ingest = client.post(
        f"{base}/sources/{source_id}/documents/ingest",
        headers=headers,
        json={"title": SAMPLE_TITLE, "text": SAMPLE_TEXT},
    )
    print(f"   ingest: {ingest.status_code}")
    if ingest.status_code >= 400:
        print("   ", ingest.text[:400])
        return 1

    print("5) 等待切片与向量化完成")
    deadline = time.time() + args.timeout
    status = ""
    while time.time() < deadline:
        docs = client.get(f"{base}/sources/{source_id}/documents", headers=headers).json()
        items = docs if isinstance(docs, list) else docs.get("items", [])
        if items:
            status = str(items[0].get("status"))
            if status.upper() in {"READY", "FAILED"}:
                break
        time.sleep(3)
    print(f"   document status={status}")
    if status.upper() != "READY":
        print("   切片未就绪，后续检索可能为空")
        return 1

    print("6) 检索验证")
    for strategy in ("vector", "multi", "multi_es_fast"):
        query = "儿童阅读活动在哪里举办？"
        response = client.post(
            f"{base}/sources/{source_id}/search",
            headers=headers,
            json={"query": query, "strategy": strategy, "top_k": 3},
        )
        response.raise_for_status()
        body = response.json()
        sections = body.get("sections", [])
        if not sections:
            raise RuntimeError(f"{strategy} returned no sections")
        print(f"   {strategy} 查询「{query}」→ {response.status_code}，命中 {len(sections)} 段")
        for index, section in enumerate(sections[:2], 1):
            heading = (section.get("heading") or "")[:40]
            content = (section.get("content") or "")[:90].replace("\n", " ")
            print(f"     {index}. {heading} | {content}")

    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
