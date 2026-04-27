"""
researchers 토픽 벡터 → UMAP 2D 좌표 계산 후 DB 저장.

전략:
  1. 전체 연구자 topic 벡터 로드 (sparse binary matrix)
  2. TruncatedSVD로 50차원 압축
  3. UMAP fit: 300K 샘플
  4. UMAP transform: 전체 3.2M 투영
  5. DB 배치 업데이트

Usage:
    cd backend
    .venv/bin/python -m scripts.compute_umap [--sample 300000] [--batch 50000]
"""
import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import lil_matrix, csr_matrix
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
import umap

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from app.db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler("/tmp/compute_umap.log")])
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "umap_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def load_topics():
    cache_ids = CACHE_DIR / "researcher_ids.npy"
    cache_top = CACHE_DIR / "topics_list.json"

    if cache_ids.exists() and cache_top.exists():
        logger.info("캐시에서 로드...")
        ids = np.load(cache_ids, allow_pickle=True).tolist()
        topics_list = json.loads(cache_top.read_text())
        logger.info(f"캐시 로드 완료: {len(ids):,}명")
        return ids, topics_list

    logger.info("DB에서 topics 로드 중 (배치 스트리밍)...")
    ids, topics_list = [], []
    offset, batch = 0, 50_000
    t0 = time.time()

    async with AsyncSessionLocal() as db:
        while True:
            r = await db.execute(text("""
                SELECT id, topics FROM researchers
                WHERE topics IS NOT NULL
                  AND topics::text != 'null'
                  AND topics::text != '[]'
                ORDER BY id
                LIMIT :lim OFFSET :off
            """), {"lim": batch, "off": offset})
            rows = r.fetchall()
            if not rows:
                break
            for rid, tlist in rows:
                if tlist:
                    ids.append(rid)
                    topics_list.append(tlist if isinstance(tlist, list) else json.loads(tlist))
            offset += batch
            if offset % 500_000 == 0:
                logger.info(f"  {offset:,}행 로드... ({time.time()-t0:.0f}s)")

    logger.info(f"DB 로드 완료: {len(ids):,}명 ({time.time()-t0:.0f}s)")
    np.save(cache_ids, np.array(ids, dtype=object))
    cache_top.write_text(json.dumps(topics_list))
    return ids, topics_list


def build_sparse(ids, topics_list):
    cache_path = CACHE_DIR / "sparse_matrix.npz"
    if cache_path.exists():
        logger.info("sparse 행렬 캐시 로드...")
        from scipy.sparse import load_npz
        return load_npz(cache_path)

    logger.info("unique topic 목록 추출...")
    all_topics = sorted({t for ts in topics_list for t in ts})
    topic_idx  = {t: i for i, t in enumerate(all_topics)}
    logger.info(f"unique topics: {len(all_topics):,}")
    (CACHE_DIR / "topic_idx.json").write_text(json.dumps(topic_idx))

    logger.info(f"sparse 행렬 생성 ({len(ids):,} × {len(all_topics):,})...")
    t0 = time.time()
    rows_i, cols_i = [], []
    for i, ts in enumerate(topics_list):
        for t in ts:
            if t in topic_idx:
                rows_i.append(i)
                cols_i.append(topic_idx[t])
        if i % 500_000 == 0 and i > 0:
            logger.info(f"  {i:,}행 처리...")

    mat = csr_matrix(
        (np.ones(len(rows_i), dtype=np.float32), (rows_i, cols_i)),
        shape=(len(ids), len(all_topics))
    )
    logger.info(f"sparse 완성: {mat.shape}  ({time.time()-t0:.0f}s)")
    from scipy.sparse import save_npz
    save_npz(cache_path, mat)
    return mat


def run_svd(mat, n_components=50):
    cache_path = CACHE_DIR / f"svd_{n_components}.npy"
    if cache_path.exists():
        logger.info("SVD 캐시 로드...")
        return np.load(cache_path)

    logger.info(f"TruncatedSVD {n_components}차원 압축 중...")
    t0 = time.time()
    svd = TruncatedSVD(n_components=n_components, random_state=42, n_iter=5)
    reduced = svd.fit_transform(mat)
    reduced = normalize(reduced).astype(np.float32)
    logger.info(f"SVD 완료: {reduced.shape}  ({time.time()-t0:.0f}s)  분산설명: {svd.explained_variance_ratio_.sum():.3f}")
    np.save(cache_path, reduced)
    return reduced


def run_umap(reduced, sample_size):
    cache_path = CACHE_DIR / f"umap_coords_{len(reduced)}.npy"
    if cache_path.exists():
        logger.info("UMAP 캐시 로드...")
        return np.load(cache_path)

    n = len(reduced)
    logger.info(f"UMAP fit ({min(sample_size,n):,}명 샘플) + transform ({n:,}명 전체)...")
    t0 = time.time()

    rng = np.random.default_rng(42)
    idx = rng.choice(n, size=min(sample_size, n), replace=False)
    idx.sort()

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=15,
        min_dist=0.05,
        metric="cosine",
        random_state=42,
        low_memory=True,
        verbose=True,
    )
    reducer.fit(reduced[idx])
    logger.info(f"UMAP fit 완료 ({time.time()-t0:.0f}s)")

    coords = np.zeros((n, 2), dtype=np.float32)
    batch = 100_000
    for start in range(0, n, batch):
        end = min(start + batch, n)
        coords[start:end] = reducer.transform(reduced[start:end])
        logger.info(f"  transform {end:,}/{n:,}  ({time.time()-t0:.0f}s)")

    np.save(cache_path, coords)
    logger.info(f"UMAP 완료 ({time.time()-t0:.0f}s)")
    return coords


async def update_db(ids, coords, batch_size):
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            ALTER TABLE researchers
            ADD COLUMN IF NOT EXISTS umap_x REAL,
            ADD COLUMN IF NOT EXISTS umap_y REAL
        """))
        await db.commit()

    n = len(ids)
    updated = 0
    t0 = time.time()
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch = [
            {"id": ids[i], "x": float(coords[i, 0]), "y": float(coords[i, 1])}
            for i in range(start, end)
        ]
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE researchers SET umap_x = :x, umap_y = :y WHERE id = :id"),
                batch
            )
            await db.commit()
        updated += len(batch)
        if updated % 500_000 == 0 or end == n:
            logger.info(f"DB 업데이트 {updated:,}/{n:,}  ({time.time()-t0:.0f}s)")


async def main(args):
    t_start = time.time()
    ids, topics_list = await load_topics()
    mat     = build_sparse(ids, topics_list)
    reduced = run_svd(mat, n_components=50)
    coords  = run_umap(reduced, sample_size=args.sample)
    await update_db(ids, coords, batch_size=args.batch)
    logger.info(f"\n=== 완료: {(time.time()-t_start)/60:.1f}분 ===")
    logger.info(f"umap_x: [{coords[:,0].min():.2f}, {coords[:,0].max():.2f}]")
    logger.info(f"umap_y: [{coords[:,1].min():.2f}, {coords[:,1].max():.2f}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=300_000)
    parser.add_argument("--batch",  type=int, default=50_000)
    args = parser.parse_args()
    asyncio.run(main(args))
