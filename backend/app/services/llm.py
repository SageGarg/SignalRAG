import os
import hashlib
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

import chromadb
from chromadb.config import Settings
from keybert import KeyBERT
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
kw_model = KeyBERT(model="all-MiniLM-L6-v2")
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))

BASE_EMBEDDINGS_DIR = os.path.join(_BACKEND_DIR, "embeddings")

DATASETS = {
    "signalVerse": os.path.join(_PROJECT_ROOT, "dataSet"),
    "bdib": os.path.join(_PROJECT_ROOT, "data2"),
    "nchrp": os.path.join(_PROJECT_ROOT, "nchrp_data"),
}

_RAG_SYSTEM_PROMPT = """You are a transportation engineering expert with deep knowledge of DOT standards, road construction, traffic devices, and infrastructure specifications.
You are answering from official DOT and NCHRP documents provided below.
Use the context to give a detailed, accurate answer. Cite the source document names when helpful.
Do NOT say you lack information if the answer is present in the context below.
Only say "I don't have sufficient information in the available documents" if the context genuinely does not address the question at all.

Context:
__CONTEXT__"""


def ensure_dir_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)


def find_all_files(base_dir):
    files_found = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith(".pdf") or file.lower().endswith(".docx"):
                files_found.append(os.path.join(root, file))
    return files_found


def load_file(file_path):
    if file_path.lower().endswith(".pdf"):
        return PyPDFLoader(file_path).load()
    elif file_path.lower().endswith(".docx"):
        return Docx2txtLoader(file_path).load()
    raise ValueError(f"Unsupported file type: {file_path}")


def file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def process_dataset(dataset_name, base_dir):
    ensure_dir_exists(base_dir)
    files = find_all_files(base_dir)

    embeddings_dir = os.path.join(BASE_EMBEDDINGS_DIR, dataset_name)
    ensure_dir_exists(embeddings_dir)

    chroma_client = chromadb.PersistentClient(path=embeddings_dir, settings=Settings())
    collection_name = f"{dataset_name}_collection"

    try:
        collection = chroma_client.get_collection(collection_name)
    except Exception:
        chroma_client.create_collection(collection_name)
        collection = chroma_client.get_collection(collection_name)

    vectorstore = Chroma(
        client=chroma_client,
        collection_name=collection_name,
        embedding_function=embeddings,
    )

    embedded_hashes = set()
    offset, batch_size = 0, 500
    while True:
        batch = collection.get(include=["metadatas"], limit=batch_size, offset=offset)
        metas = batch.get("metadatas") or []
        for m in metas:
            if m and "file_hash" in m:
                embedded_hashes.add(m["file_hash"])
        if len(metas) < batch_size:
            break
        offset += batch_size

    for file in files:
        fhash = file_hash(file)
        if fhash in embedded_hashes:
            continue
        try:
            docs = load_file(file)
        except Exception as e:
            print(f"[WARN] Skipping {os.path.basename(file)}: {e}")
            continue
        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        documents = splitter.split_documents(docs)
        for d in documents:
            d.metadata.update({"source": file, "file_hash": fhash})
        for i in range(0, len(documents), 1000):
            vectorstore.add_documents(documents[i : i + 1000])

    return vectorstore


def extract_keywords(text, top_k=5):
    keywords = kw_model.extract_keywords(text, top_n=top_k, stop_words="english")
    return [kw[0].lower() for kw in keywords]


def rerank_docs(question, docs, top_n=4):
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    reranked = []
    for doc in docs:
        score_prompt = (
            f"Question: {question}\n"
            f"Document: {doc.page_content}\n"
            "On a scale of 1-10, how relevant is this document to answering the question?\n"
            "Reply with just a number."
        )
        try:
            score = int(llm.invoke(score_prompt).content.strip())
        except Exception:
            score = 5
        reranked.append((score, doc))
    reranked.sort(key=lambda x: x[0], reverse=True)
    return [doc for score, doc in reranked if score >= 3][:top_n]


def check_relevance(question: str, vectorstore=None, threshold: float = None) -> tuple:
    """
    Returns (is_off_topic: bool, score: float).
    Uses gpt-4o-mini to classify intent — reliable, ~$0.00015 per call.
    Fails open: if the call errors, we allow the question through.
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            temperature=0,
            max_tokens=1,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict topic classifier. "
                        "Answer only YES or NO.\n"
                        "Is this question related to any of: traffic signals, "
                        "sensor testing, detection technology, DOT specifications, "
                        "road infrastructure, transportation engineering, or NCHRP research?"
                    ),
                },
                {"role": "user", "content": question},
            ],
        )
        answer = resp.choices[0].message.content.strip().upper()
        is_off_topic = answer != "YES"
        print(f"[guardrail] question={repr(question[:60])} verdict={answer} off_topic={is_off_topic}")
        return is_off_topic, 0.0
    except Exception as e:
        print(f"[guardrail] classifier failed: {e}")
        return False, 1.0


def answer_question(question, vectorstore, chat_history=None, top_n=4):
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 10, "fetch_k": 20, "lambda_mult": 0.7},
    )

    # Condense follow-up questions into standalone queries using history
    if chat_history:
        history_text = "\n".join(
            f"Human: {t['question']}\nAssistant: {t['answer']}"
            for t in chat_history
        )
        condense_prompt = (
            f"Given this conversation:\n{history_text}\n\n"
            f"Rephrase this follow-up as a standalone question: {question}"
        )
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        search_query = llm.invoke(condense_prompt).content.strip()
    else:
        search_query = question

    # Retrieve and rerank
    docs = retriever.invoke(search_query)
    top_docs = rerank_docs(question, docs, top_n=top_n)

    if not top_docs:
        return "I don't have sufficient information in the available documents to answer this.", []

    # Build context string with source labels
    context_parts = []
    for d in top_docs:
        src = os.path.basename(d.metadata.get("source", "Unknown"))
        page = d.metadata.get("page")
        label = f"[{src}, page {page + 1}]" if page is not None else f"[{src}]"
        context_parts.append(f"{label}\n{d.page_content}")
    context = "\n\n".join(context_parts)

    # Call OpenAI directly — no deprecated chain abstractions
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {"role": "system", "content": _RAG_SYSTEM_PROMPT.replace("__CONTEXT__", context)},
            {"role": "user", "content": question},
        ],
    )
    answer = response.choices[0].message.content.strip()

    # Deduplicated source list
    seen = {}
    for d in top_docs:
        src = os.path.basename(d.metadata.get("source", "Unknown"))
        page = d.metadata.get("page")
        key = f"{src} (page {page + 1})" if page is not None else src
        seen[key] = True

    metadata_text = "\n\nSources:\n" + "\n".join(seen.keys()) if seen else ""
    return answer + metadata_text, top_docs


def init_vectorstores():
    vectorstores = {}
    for dataset_name, base_dir in DATASETS.items():
        vectorstores[dataset_name] = process_dataset(dataset_name, base_dir)
    return vectorstores
