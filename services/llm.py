import os
import hashlib
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA, ConversationalRetrievalChain
import chromadb
from chromadb.config import Settings
from keybert import KeyBERT
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
kw_model = KeyBERT(model="all-MiniLM-L6-v2")
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")

BASE_EMBEDDINGS_DIR = "embeddings"
DATASETS = {
    "signalVerse": "dataSet",
    "bdib": "data2",
    "nchrp": "nchrp_data"
}

def ensure_dir_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def find_all_files(base_dir):
    files_found = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".pdf") or file.endswith(".docx"):
                files_found.append(os.path.join(root, file))
    return files_found

def load_file(file_path):
    if file_path.lower().endswith(".pdf"):
        return PyPDFLoader(file_path).load()
    elif file_path.lower().endswith(".docx"):
        return Docx2txtLoader(file_path).load()
    else:
        raise ValueError(f"Unsupported file type: {file_path}")

def file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def process_dataset(dataset_name, base_dir):
    ensure_dir_exists(base_dir)
    print(f"Processing dataset: {dataset_name}")
    files = find_all_files(base_dir)
    
    embeddings_dir = os.path.join(BASE_EMBEDDINGS_DIR, dataset_name)
    ensure_dir_exists(embeddings_dir)

    chroma_client = chromadb.PersistentClient(path=embeddings_dir, settings=Settings())
    collection_name = f"{dataset_name}_collection"

    try:
        collection = chroma_client.get_collection(collection_name)
        print("[INFO] Found existing collection.")
    except Exception:
        print("[INFO] No existing collection. Creating new one.")
        chroma_client.create_collection(collection_name)
        collection = chroma_client.get_collection(collection_name)

    vectorstore = Chroma(
        client=chroma_client,
        collection_name=collection_name,
        embedding_function=embeddings
    )

    existing = collection.get(include=["metadatas"])
    embedded_hashes = set()
    if "metadatas" in existing and existing["metadatas"]:
        for m in existing["metadatas"]:
            if m and "file_hash" in m:
                embedded_hashes.add(m["file_hash"])

    for file in files:
        fhash = file_hash(file)
        if fhash in embedded_hashes:
            continue
        docs = load_file(file)
        print(f"[INFO] Loaded {len(docs)} pages from {file}")
        
        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        documents = splitter.split_documents(docs)
        
        for d in documents:
            d.metadata.update({"source": file, "file_hash": fhash})
            
        batch_size = 1000
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i+batch_size]
            vectorstore.add_documents(batch)
            print(f"[SUCCESS] Embedded {len(batch)} chunks from {file} (Batch {i//batch_size + 1})")

    return vectorstore

def extract_keywords(text, top_k=5):
    keywords = kw_model.extract_keywords(text, top_n=top_k, stop_words='english')
    return [kw[0].lower() for kw in keywords]

def rerank_docs(question, docs, top_n=4):
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    reranked = []
    for doc in docs:
        score_prompt = f"Question: {question}\nDocument: {doc.page_content}\nOn a scale of 1-10, how relevant is this document to answering the question?\nReply with just a number."
        try:
            score = int(llm.invoke(score_prompt).content.strip())
        except:
            score = 5
        reranked.append((score, doc))
    reranked.sort(key=lambda x: x[0], reverse=True)
    
    # Only return documents that are actually somewhat relevant to the question!
    # Conversational questions (e.g. "hi there") will yield scores of 1, effectively clearing out irrelevant citations.
    return [doc for score, doc in reranked if score >= 4][:top_n]

def answer_question(question, vectorstore, chat_history=None, top_n=4):
    retriever = vectorstore.as_retriever(
        search_type="mmr", 
        search_kwargs={"k": 10, "fetch_k": 20, "lambda_mult": 0.7}
    )
    llm = ChatOpenAI(model="gpt-4o", temperature=0)

    if chat_history is None:
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=retriever,
            return_source_documents=True
        )
        response = qa_chain.invoke({"query": question})
        answer = response.get("result", "")
    else:
        qa_chain = ConversationalRetrievalChain.from_llm(
            llm=llm,
            retriever=retriever,
            return_source_documents=True
        )
        response = qa_chain.invoke({
            "question": question,
            "chat_history": chat_history
        })
        answer = response.get("answer", "")

    sources = response.get("source_documents", [])
    top_sources = rerank_docs(question, sources, top_n=top_n)

    metadata_info = []
    for doc in top_sources:
        src = doc.metadata.get("source", "Unknown file")
        page = doc.metadata.get("page", None)
        if page is not None:
            metadata_info.append(f"{os.path.basename(src)} (page {page+1})")
        else:
            metadata_info.append(os.path.basename(src))
            
    metadata_text = "\nSources:\n" + "\n".join(set(metadata_info)) if metadata_info else ""
    return answer + "\n\n" + metadata_text, top_sources

def init_vectorstores():
    vectorstores = {}
    for dataset_name, base_dir in DATASETS.items():
        vectorstores[dataset_name] = process_dataset(dataset_name, base_dir)
    return vectorstores
