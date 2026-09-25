"""Bước 13 notebook (optional): Qwen2.5-3B local trả lời RAG. Bỏ qua nếu thiếu VRAM.

MỚI: dùng LlamaIndex retriever (src/llama_rag.py) thay cho FAISS thủ công cũ,
nên context giờ có source/page đi kèm và không còn bị cắt đôi công thức.
"""
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

from .llama_rag import retrieve


def load_llm(llm_name: str):
    tok = AutoTokenizer.from_pretrained(llm_name)
    model = AutoModelForCausalLM.from_pretrained(
        llm_name, torch_dtype="auto", device_map="auto")
    return tok, model


def ask_rag(question: str, tokenizer, model, index,
            top_k: int = 4, max_new_tokens: int = 512):
    retrieved = retrieve(index, question, top_k=top_k)
    context = "\n\n".join(
        f"[Source {i+1} | {r['source']} | trang {r['page']}]\n{r['text']}"
        for i, r in enumerate(retrieved))
    user_prompt = f"""Bạn là trợ lý hỏi đáp tài liệu toán.

Chỉ sử dụng thông tin trong CONTEXT.
Nếu CONTEXT không đủ để trả lời, hãy nói rõ rằng tài liệu không cung cấp đủ thông tin.
Không tự bịa công thức.
Giữ nguyên LaTeX khi trích dẫn công thức.

CONTEXT:
{context}

QUESTION:
{question}
"""
    messages = [
        {"role": "system",
         "content": "Trả lời chính xác dựa trên tài liệu được truy xuất."},
        {"role": "user", "content": user_prompt},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([prompt], return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens,
                             do_sample=False)
    gen = out[0][inputs["input_ids"].shape[1]:]
    answer = tokenizer.decode(gen, skip_special_tokens=True)
    return answer, retrieved
