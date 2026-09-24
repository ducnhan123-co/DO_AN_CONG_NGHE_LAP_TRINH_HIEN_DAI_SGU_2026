"""Retrieval bằng LlamaIndex (giống hướng của đồ án), cùng giao diện với server.retrieve.

Cấu hình (RAG_ENGINE):
  li_e5      VectorStoreIndex + intfloat/multilingual-e5-base (y như src/llama_rag.py đồ án)
  li_qwen    VectorStoreIndex + qwen3-embedding:0.6b qua Ollama
  li_fusion  li_qwen + BM25, trộn bằng QueryFusionRetriever (reciprocal rank fusion)
  li_fusion_e5  li_e5 + BM25 (fusion như trên)
"""
from functools import lru_cache

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.schema import TextNode

Settings.llm = MockLLM()  # chỉ dùng retrieval; LLM sinh câu trả lời vẫn là Ollama trong server.py

QWEN_QUERY = "Instruct: Given a question, retrieve passages that answer it\nQuery: "
TOKEN_PATTERN = r"(?u)\b\w+(?:\.\w+)*\b"  # giữ 'q', '3.1' (mặc định BM25 bỏ)


@lru_cache(maxsize=None)
def _embed(kind: str):
    if kind == "e5":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        return HuggingFaceEmbedding(model_name="intfloat/multilingual-e5-base",
                                    query_instruction="query: ", text_instruction="passage: ")
    from llama_index.embeddings.ollama import OllamaEmbedding
    return OllamaEmbedding(model_name="qwen3-embedding:0.6b", query_instruction=QWEN_QUERY,
                           embed_batch_size=64)


class LIRetriever:
    def __init__(self, chunks: list[dict], engine: str = "li_fusion", top_k: int = 10):
        self.chunks = chunks
        nodes = [TextNode(id_=str(i), text=c["text"], metadata={"page": c["page"]})
                 for i, c in enumerate(chunks)]
        for n in nodes:
            n.excluded_embed_metadata_keys = ["page"]  # chỉ embed nội dung, như đồ án
        index = VectorStoreIndex(nodes, embed_model=_embed("e5" if engine.endswith("e5") else "qwen"))
        self.vec = index.as_retriever(similarity_top_k=top_k)
        self.ret = self.vec
        if engine.startswith("li_fusion"):
            from llama_index.retrievers.bm25 import BM25Retriever
            bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=top_k,
                                               token_pattern=TOKEN_PATTERN)
            self.ret = QueryFusionRetriever([self.vec, bm25], mode="reciprocal_rerank",
                                            similarity_top_k=top_k, num_queries=1,
                                            use_async=False)

    def retrieve(self, question: str, top_k: int) -> list[dict]:
        hits = self.ret.retrieve(question)[:top_k]
        return [{**self.chunks[int(h.node.node_id)], "score": float(h.score or 0.0)}
                for h in hits]
