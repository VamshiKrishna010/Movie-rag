from app.ingest.embedder import embed_texts, embed_query

vecs = embed_texts(["Inception is a movie about dreams", "Toy Story is about toys"])
print(f"Got {len(vecs)} vectors, each {len(vecs[0])} dimensions")

q = embed_query("films about the subconscious")
print(f"Query vector: {len(q)} dimensions")
print(f"First 5 values: {q[:5]}")