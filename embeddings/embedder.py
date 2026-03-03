import ollama

class CodeEmbedder:
    """
    questa classe trasforma i pezzi di codice in embeddings
    """
    def __init__(self):
        self.model = "nomic-embed-text"
        # metto max chars a 3000 per garantire che, inclusi i token speciali, 
        # non si superi mai il limite hardware/software di Ollama
        self.max_chars = 3000 
        print(f"Embedder locale pronto (Modello: {self.model})")

    def get_embedding(self, text, is_query=False):
        if not text or text.strip() == "":
            return None
            
        try:
            # 1. pulizia aggressiva degli spazi cosi riduco drasticamente il numero di token
            # trasformo tutti i whitespace (tab, multiple newline) in spazi singoli
            clean_text = " ".join(text.split())
            
            # 2. applicazione del prefisso richiesto da Nomic
            prefix = "search_query: " if is_query else "search_document: "
            
            # 3. taglio di sicurezza a 3000 caratteri
            safe_text = (prefix + clean_text)[:self.max_chars]

            response = ollama.embeddings(
                model=self.model,
                prompt=safe_text
            )
            return response['embedding']
            
        except Exception as e:
            print(f"Errore Ollama (Lunghezza testo: {len(text)}): {e}")
            return None