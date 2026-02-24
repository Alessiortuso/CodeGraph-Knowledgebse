import ollama

class CodeEmbedder:
    """
    questa classe si occupa di trasformare i pezzi di codice in embeddings
    """
    def __init__(self):
        self.model = "nomic-embed-text"
        # 5.000 caratteri è una soglia sicura per non far crashare ollama
        self.max_chars = 5000 
        print(f"Embedder locale pronto (Modello: {self.model})")

    def get_embedding(self, text):
        if not text or text.strip() == "":
            return None
            
        try:
            # taglio il testo in modo deciso per evitare l'errore di context length
            safe_text = text[:self.max_chars]

            # chiamata a ollama per generare il vettore
            response = ollama.embeddings(
                model=self.model,
                prompt=safe_text
            )
            return response['embedding']
            
        except Exception as e:
            print(f"Errore nella generazione dell'embedding con Ollama: {e}")
            return None