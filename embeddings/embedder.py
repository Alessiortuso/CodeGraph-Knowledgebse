# lo scopo è trasformare il testo (codice o domande dell utente) in vettori numerici
# utilizza ollama e il modello nomic-embed-text per creare rappresentazioni matematiche
# del significato del codice, permettendo la ricerca semantica nel database memgraph 
# uesto modulo abilita la ricerca semantica
# a differenza di una ricerca classica, l'embedding cattura il concetto
# il modello nomic-embed-text trasforma il testo in un vettore 
# in uno spazio multidimensionale: pezzi di codice con scopi simili 
# finiranno "vicini" in questo spazio

import logging
import ollama

logger = logging.getLogger(__name__)

class CodeEmbedder:
    """
    questa classe trasforma i pezzi di codice in embeddings
    """
    def __init__(self):
        # usiamo nomic perche è un modello leggero e molto bravo a gestire i contesti di ricerca
        self.model = "nomic-embed-text"
        # usiamo 5500 per avere un margine di sicurezza
        self.max_chars = 5500
        logger.info(f"embedder locale pronto (modello: {self.model})")

    def get_embedding(self, text, is_query=False):
        # se il testo è vuoto non facciamo nulla e restituiamo none
        if not text or text.strip() == "":
            return None
            
        try:
            # 1. pulizia aggressiva degli spazi cosi riduco drasticamente il numero di token
            # trasformo tutti i whitespace (tab, multiple newline) in spazi singoli
            # questo serve perché ai modelli di embedding non interessa la formattazione ma il contenuto
            clean_text = " ".join(text.split())
            
            # 2. applicazione del prefisso richiesto da nomic
            # questo modello vuole sapere se stiamo salvando un documento o facendo una domanda
            # search_query si usa per la domanda dell utente, search_document per il codice nel db
            prefix = "search_query: " if is_query else "search_document: "
            
            # 3. assembliamo il testo col prefisso e lo tagliamo se è troppo lungo
            safe_text = (prefix + clean_text)[:self.max_chars]

            # chiamiamo ollama per ottenere l embedding
            response = ollama.embeddings(
                model=self.model,
                prompt=safe_text
            )
            return response['embedding']
            
        except (ConnectionError, TimeoutError, KeyError, RuntimeError) as e:
            # se ollama è spento o c è un errore, lo scriviamo ma non facciamo crashare il programma
            logger.error(f"errore ollama (lunghezza testo: {len(text)}): {e}")
            return None