"""
tests/test_kb_search.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — Tests
Purpose
-------
Unit tests for the KB search layer (src/kb/kb_search.py).
Constraints
-----------
- This test file imports stdlib ONLY: unittest, tempfile, shutil
- Project modules imported dynamically (kb_connect/kb_ingest/kb_search)
- Creates a temp persistent ChromaDB instance under /tmp/test_kb in setUp
- Cleans up the temp KB directory after each test (tearDown)
Notes on embeddings
-------------------
Chroma collections often require an embedding function. To keep tests fully
offline and deterministic, we attach a tiny keyword-count embedding function
to every collection returned by the Chroma client during the test run.
"""
import unittest
import tempfile
import shutil


def _import_first(module_names):
    """Import and return the first importable module from a list of names."""
    for name in module_names:
        try:
            return __import__(name, fromlist=["*"])
        except Exception:
            continue
    return None


class _KeywordEmbeddingFn:
    """Tiny deterministic embedding function (keyword-count vectors).

    This is intentionally simple:
    - No external models
    - No downloads
    - Stable across runs
    """

    def __init__(self):
        # Keep vocab small and tailored to the test corpus.
        self._vocab = [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "apple",
            "banana",
            "cherry",
            "filter",
            "across",
            "similar",
        ]

    def _tokenize(self, text):
        """Lowercase alnum tokenizer without importing re."""
        t = str(text or "").lower()
        tokens = []
        buf = ""
        for ch in t:
            if ch.isalnum():
                buf += ch
            else:
                if buf:
                    tokens.append(buf)
                    buf = ""
        if buf:
            tokens.append(buf)
        return tokens

    def __call__(self, texts):
        vectors = []
        for txt in (texts or []):
            toks = self._tokenize(txt)
            vec = [float(toks.count(w)) for w in self._vocab]
            vectors.append(vec)
        return vectors


class TestKBSearch(unittest.TestCase):
    """Unit tests for KB semantic search helpers."""

    def setUp(self):
        # Requirement: temp KB under this fixed path.
        self.kb_path = "/tmp/test_kb"
        # Ensure clean slate for each test.
        shutil.rmtree(self.kb_path, ignore_errors=True)

        # Dynamically import project modules (keeps test imports stdlib-only).
        self.kb_connect = _import_first(
            [
                "src.kb.kb_connect",
                "kb.kb_connect",
                "kb_connect",
            ]
        )
        self.kb_ingest = _import_first(
            [
                "src.kb.kb_ingest",
                "kb.kb_ingest",
                "kb_ingest",
            ]
        )
        self.kb_search = _import_first(
            [
                "src.kb.kb_search",
                "kb.kb_search",
                "kb_search",
            ]
        )

        if self.kb_connect is None or self.kb_ingest is None or self.kb_search is None:
            raise RuntimeError(
                "KB modules not importable. Expected src.kb.{kb_connect,kb_ingest,kb_search}."
            )

        KBConnection = getattr(self.kb_connect, "KBConnection", None)
        if KBConnection is None:
            raise RuntimeError("KBConnection not found in kb_connect module.")

        # Create and connect KB (ChromaDB persistent client).
        self.conn = KBConnection(path=self.kb_path)
        self.conn.connect()

        # Patch the underlying client to always attach a test embedder.
        self._embedder = _KeywordEmbeddingFn()
        self._patch_chroma_client(self.conn.client)

        # Reset kb_search in-memory stats between tests (best-effort).
        if hasattr(self.kb_search, "_SEARCH_STATS") and isinstance(self.kb_search._SEARCH_STATS, dict):
            self.kb_search._SEARCH_STATS.clear()

    def tearDown(self):
        # Best-effort disconnect + cleanup.
        try:
            if hasattr(self, "conn") and self.conn is not None:
                try:
                    self.conn.disconnect()
                except Exception:
                    pass
        finally:
            shutil.rmtree(getattr(self, "kb_path", "/tmp/test_kb"), ignore_errors=True)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _attach_embedder(self, col):
        """Attach the test embedder to a Chroma collection object."""
        for attr in ("_embedding_function", "embedding_function"):
            try:
                setattr(col, attr, self._embedder)
            except Exception:
                pass
        return col

    def _patch_chroma_client(self, client):
        """Monkeypatch client collection factories to attach our embedder.

        Why: kb_ingest/kb_search call client.get_collection(name=...) without passing an
        embedding_function, so we enforce a deterministic embedder at the client boundary.
        """
        if client is None:
            return

        # Patch get_collection
        if hasattr(client, "get_collection") and callable(getattr(client, "get_collection")):
            orig = client.get_collection

            def _get_collection(*args, **kwargs):
                col = orig(*args, **kwargs)
                return self._attach_embedder(col)

            try:
                client.get_collection = _get_collection
            except Exception:
                pass

        # Patch create_collection
        if hasattr(client, "create_collection") and callable(getattr(client, "create_collection")):
            orig = client.create_collection

            def _create_collection(*args, **kwargs):
                col = orig(*args, **kwargs)
                return self._attach_embedder(col)

            try:
                client.create_collection = _create_collection
            except Exception:
                pass

        # Patch get_or_create_collection
        if hasattr(client, "get_or_create_collection") and callable(
            getattr(client, "get_or_create_collection")
        ):
            orig = client.get_or_create_collection

            def _get_or_create_collection(*args, **kwargs):
                col = orig(*args, **kwargs)
                return self._attach_embedder(col)

            try:
                client.get_or_create_collection = _get_or_create_collection
            except Exception:
                pass

    def _ensure_collection(self, name):
        """Create (or fetch) a collection and ensure embedder is attached."""
        client = self.conn.client

        # Prefer idempotent API when available.
        if hasattr(client, "get_or_create_collection"):
            try:
                col = client.get_or_create_collection(name=name, metadata={"created_by": "test"})
                return self._attach_embedder(col)
            except TypeError:
                col = client.get_or_create_collection(name)
                return self._attach_embedder(col)

        # Fallback: create then get.
        try:
            col = client.create_collection(name=name, metadata={"created_by": "test"})
        except TypeError:
            col = client.create_collection(name)
        return self._attach_embedder(col)

    def _collection_records(self, col):
        """Return list of (id, document, metadata) for all records in a collection."""
        try:
            res = col.get(include=["documents", "metadatas"])  # type: ignore[arg-type]
        except TypeError:
            res = col.get()

        if not isinstance(res, dict):
            return []

        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []

        # Some Chroma versions return nested lists; flatten 1 level if needed.
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        if docs and isinstance(docs[0], list):
            docs = docs[0]
        if metas and isinstance(metas[0], list):
            metas = metas[0]

        out = []
        for i in range(max(len(ids), len(docs), len(metas))):
            _id = str(ids[i]) if i < len(ids) else ""
            doc = str(docs[i]) if i < len(docs) else ""
            md = metas[i] if i < len(metas) else {}
            md = dict(md) if isinstance(md, dict) else {"value": md}
            out.append((_id, doc, md))
        return out

    def _first_doc_id_for_group(self, col, group_id):
        """Best-effort: find a doc_id whose metadata.group_id matches."""
        group_id = str(group_id or "")
        for _id, _doc, md in self._collection_records(col):
            if str(md.get("group_id") or "") == group_id:
                return _id
        # Fallback: first record id.
        recs = self._collection_records(col)
        return recs[0][0] if recs else ""

    # ---------------------------------------------------------------------
    # Required test cases
    # ---------------------------------------------------------------------

    def test_search_returns_results(self):
        col_name = "t_search"
        self._ensure_collection(col_name)
        self.kb_ingest.ingest_text(self.conn, col_name, "alpha beta gamma", {"tag": "t1"})
        hits = self.kb_search.search(self.conn, col_name, "alpha", n_results=5)
        self.assertIsInstance(hits, list)
        self.assertGreater(len(hits), 0)
        first = hits[0]
        self.assertIn("doc_id", first)
        self.assertIn("text", first)
        self.assertIn("score", first)
        self.assertIn("metadata", first)
        self.assertIn("alpha", str(first.get("text", "")).lower())
        self.assertEqual(first.get("metadata", {}).get("tag"), "t1")
        score = first.get("score")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_search_empty_collection_returns_empty(self):
        col_name = "t_empty"
        self._ensure_collection(col_name)
        hits = self.kb_search.search(self.conn, col_name, "alpha", n_results=5)
        self.assertEqual(hits, [])

    def test_search_with_filter(self):
        col_name = "t_filter"
        self._ensure_collection(col_name)
        self.kb_ingest.ingest_text(self.conn, col_name, "alpha filter", {"topic": "keep"})
        self.kb_ingest.ingest_text(self.conn, col_name, "alpha filter", {"topic": "drop"})
        hits = self.kb_search.search_with_filter(
            self.conn, col_name, "alpha", {"topic": "keep"}, n_results=10
        )
        self.assertGreater(len(hits), 0)
        self.assertTrue(all(h.get("metadata", {}).get("topic") == "keep" for h in hits))

    def test_search_across_collections(self):
        a = "t_across_a"
        b = "t_across_b"
        self._ensure_collection(a)
        self._ensure_collection(b)
        self.kb_ingest.ingest_text(self.conn, a, "alpha alpha alpha", {"src": "a"})
        self.kb_ingest.ingest_text(self.conn, b, "delta delta delta", {"src": "b"})
        hits = self.kb_search.search_across_collections(self.conn, "alpha delta", [a, b], n_results=10)
        self.assertGreaterEqual(len(hits), 2)
        cols = {h.get("metadata", {}).get("collection") for h in hits}
        self.assertIn(a, cols)
        self.assertIn(b, cols)

    def test_similar_documents(self):
        col_name = "t_similar"
        col = self._ensure_collection(col_name)
        gid1 = self.kb_ingest.ingest_text(self.conn, col_name, "apple banana", {"label": "base"})
        _ = self.kb_ingest.ingest_text(self.conn, col_name, "apple banana cherry", {"label": "plus"})
        doc_id = self._first_doc_id_for_group(col, gid1)
        self.assertTrue(doc_id)
        sims = self.kb_search.get_similar_documents(self.conn, col_name, doc_id, n_results=5)
        self.assertGreaterEqual(len(sims), 1)
        self.assertTrue(any("cherry" in str(h.get("text", "")).lower() for h in sims))

    # ---------------------------------------------------------------------
    # Additional tests (to reach >= 8 total)
    # ---------------------------------------------------------------------

    def test_search_empty_query_returns_empty(self):
        col_name = "t_blank_query"
        self._ensure_collection(col_name)
        self.kb_ingest.ingest_text(self.conn, col_name, "alpha beta", {"tag": "x"})
        hits = self.kb_search.search(self.conn, col_name, "   ", n_results=5)
        self.assertEqual(hits, [])

    def test_search_stats_updates_after_query(self):
        col_name = "t_stats"
        self._ensure_collection(col_name)
        self.kb_ingest.ingest_text(self.conn, col_name, "alpha beta", {"tag": "x"})
        before = self.kb_search.get_search_stats(self.conn, col_name)
        self.assertIn("last_query_at", before)
        _ = self.kb_search.search(self.conn, col_name, "alpha", n_results=3)
        after = self.kb_search.get_search_stats(self.conn, col_name)
        self.assertGreaterEqual(int(after.get("total_searchable_docs") or 0), 1)
        self.assertTrue(after.get("last_query_at"))  # should be non-empty after at least one query

    def test_search_across_collections_dedupe_by_group_id(self):
        a = "t_dedupe_a"
        b = "t_dedupe_b"
        col_a = self._ensure_collection(a)
        col_b = self._ensure_collection(b)
        # Same group_id across collections should dedupe to a single result.
        group_id = "KBG-DEDUP"
        col_a.add(ids=["dup_a"], documents=["alpha beta"], metadatas=[{"group_id": group_id}])
        col_b.add(ids=["dup_b"], documents=["alpha beta"], metadatas=[{"group_id": group_id}])
        hits = self.kb_search.search_across_collections(self.conn, "alpha beta", [a, b], n_results=10)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].get("metadata", {}).get("group_id"), group_id)

    def test_search_with_filter_rejects_non_dict_filter(self):
        col_name = "t_bad_filter"
        self._ensure_collection(col_name)
        self.kb_ingest.ingest_text(self.conn, col_name, "alpha", {"tag": "x"})
        with self.assertRaises(TypeError):
            self.kb_search.search_with_filter(
                self.conn,
                col_name,
                "alpha",
                "not-a-dict",  # type: ignore[arg-type]
                n_results=5,
            )

    def test_search_after_ingest_file(self):
        """Integration sanity check: ingest_file() + search()."""
        col_name = "t_file"
        self._ensure_collection(col_name)
        # Create a small txt file inside the KB path so tearDown cleans it up.
        with tempfile.NamedTemporaryFile(mode="w", dir=self.kb_path, suffix=".txt", delete=False) as f:
            f.write("alpha beta\n\n")
            f.write("gamma delta\n")
            file_path = f.name
        group_ids = self.kb_ingest.ingest_file(self.conn, col_name, file_path)
        self.assertGreaterEqual(len(group_ids), 1)
        hits = self.kb_search.search(self.conn, col_name, "delta", n_results=5)
        self.assertGreaterEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
