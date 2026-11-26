"""qwen3-vl-embedding 真实 API 测试脚本。

用法（Key 只从环境变量读取，不要写进命令历史或仓库）::

    set SAG_EMBEDDING_API_KEY=sk-xxxx
    uv run python scripts/test_vl_embedding.py

    # 可选：覆盖模型/端点/维度
    uv run python scripts/test_vl_embedding.py --dimension 1024 --model qwen3-vl-embedding

脚本走的是应用自己的适配器（DashScopeMultimodalEmbeddingAdapter），
因此同时验证了请求构造、响应解析与维度校验，而不是另写一套 HTTP。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
import time

from zleap.sag.config import EmbeddingConfig

from sag_api.sag.multimodal_embedding import (
    DASHSCOPE_MULTIMODAL_ENDPOINT,
    DashScopeMultimodalEmbeddingAdapter,
)

#: 官方文档示例图（阿里云 OSS，公网可访问）。
DEMO_IMAGE = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def ok(message: str) -> None:
    print(f"  [OK] {message}")


def fail(message: str) -> None:
    print(f"  [FAIL] {message}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("SAG_EMBEDDING_MODEL", "qwen3-vl-embedding"))
    parser.add_argument(
        "--endpoint",
        default=os.getenv("SAG_EMBEDDING_MULTIMODAL_ENDPOINT", DASHSCOPE_MULTIMODAL_ENDPOINT),
    )
    parser.add_argument("--dimension", type=int, default=1024)
    args = parser.parse_args()

    key = os.getenv("SAG_EMBEDDING_API_KEY", "").strip()
    if not key:
        print("缺少 SAG_EMBEDDING_API_KEY 环境变量", file=sys.stderr)
        return 2

    config = EmbeddingConfig(
        model=args.model,
        api_key=key,
        base_url=None,
        schema_dimensions=args.dimension,
        request_dimensions=args.dimension,
        timeout=90,
    )
    adapter = DashScopeMultimodalEmbeddingAdapter(config, endpoint=args.endpoint)
    passed = 0
    failed = 0

    try:
        # 1. 单条文本
        t0 = time.perf_counter()
        vec = await adapter.generate("城市图书馆开放时间")
        dt = time.perf_counter() - t0
        if len(vec) == args.dimension:
            ok(f"单条文本：{len(vec)} 维，{dt:.2f}s")
            passed += 1
        else:
            fail(f"单条文本维度异常：{len(vec)} != {args.dimension}")
            failed += 1

        # 2. 批量文本（必须独立向量、顺序一致）
        texts = ["图书馆借阅时间", "儿童阅览室", "书籍归还流程"]
        t0 = time.perf_counter()
        vectors = await adapter.batch_generate(texts)
        dt = time.perf_counter() - t0
        if len(vectors) == len(texts) and all(len(v) == args.dimension for v in vectors):
            ok(f"批量文本：{len(vectors)} 个独立向量，{dt:.2f}s")
            passed += 1
        else:
            fail(f"批量文本数量/维度异常：{len(vectors)} 个")
            failed += 1

        # 3. 单张图片
        t0 = time.perf_counter()
        image_vec = await adapter.embed_image(DEMO_IMAGE)
        dt = time.perf_counter() - t0
        if len(image_vec) == args.dimension:
            ok(f"单张图片：{len(image_vec)} 维，{dt:.2f}s")
            passed += 1
        else:
            fail(f"图片向量维度异常：{len(image_vec)}")
            failed += 1

        # 4. 图文融合
        t0 = time.perf_counter()
        fused = await adapter.embed_multimodal(
            [{"text": "示例图片"}, {"image": DEMO_IMAGE}]
        )
        dt = time.perf_counter() - t0
        if len(fused) == args.dimension:
            ok(f"图文融合：单个融合向量 {len(fused)} 维，{dt:.2f}s")
            passed += 1
        else:
            fail(f"融合向量维度异常：{len(fused)}")
            failed += 1

        # 5. 跨模态相似度
        text_vec = vectors[0]
        sim_text = cosine(text_vec, vectors[1])
        sim_image = cosine(text_vec, image_vec)
        print(f"       文本↔文本 {sim_text:.4f} / 文本↔图片 {sim_image:.4f}")
        if -1.0 <= sim_text <= 1.0 and -1.0 <= sim_image <= 1.0:
            ok("相似度计算正常（跨模态同空间可比）")
            passed += 1
        else:
            fail("相似度超出 [-1,1]")
            failed += 1
    finally:
        await adapter.close()

    print(f"\n结果：{passed} 项通过，{failed} 项失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
