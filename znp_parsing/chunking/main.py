from pdf_chunker_general import pdf_chunker
from chunk_codex import chunk_codex
from pdf_chunker_87 import chunk_eighty_seven
import time
import os
from concurrent.futures import ProcessPoolExecutor

chunk =pdf_chunker("chunked_pdf")
chunk_codex = chunk_codex("chunked_pdf")
chunk_87 = chunk_eighty_seven("chunked_pdf")

def process_doc(doc):
    try:
        print(f"Processing {doc}", flush=True)
        input_path = f"Docs/{doc}"
        output_name = f"{doc.split('.pdf')[0]}.json"
        if "Кодекс_от_29_12_2004_N_190_ФЗ_Градостроительный_кодекс_Российской.pdf" in input_path:
            chunk_codex.preprocess_doc(input_path, out_name=output_name)
        elif "Постановление_Правительства_РФ_от_16_02_2008_N_87_О_составе_разделов.pdf" in input_path:
            chunk_87.preprocess_doc(input_path, out_name=output_name)
        else:
            chunk.preprocess_doc(input_path, out_name=output_name)
    except Exception as e:
        print(f"Error with {doc}: {str(e)}", flush=True)


if __name__ == "__main__":
    start = time.time()
    print("start",flush= True)
    docs = [f for f in os.listdir("Docs") if f.endswith(".pdf")]
    with ProcessPoolExecutor(max_workers=1) as executor:
        executor.map(process_doc, docs)
    print(time.time()-start)
    process_doc(docs[0])