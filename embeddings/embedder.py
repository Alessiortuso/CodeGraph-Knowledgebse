# lo scopo è trasformare il testo (codice o domande dell utente) in vettori numerici
# utilizza ollama e il modello nomic-embed-text per creare rappresentazioni matematiche
# del significato del codice, permettendo la ricerca semantica nel database memgraph
# a differenza di una ricerca classica, l'embedding cattura il concetto
# il modello nomic-embed-text trasforma il testo in un vettore
# in uno spazio multidimensionale: pezzi di codice con scopi simili
# finiranno "vicini" in questo spazio

import logging
import requests

logger = logging.getLogger(__name__)

# indirizzo del server ollama: prima proviamo l'host docker (dentro container),
# poi il localhost (fuori docker). viene letto da variabile d'ambiente se disponibile
import os
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


class CodeEmbedder:
    """
    questa classe trasforma i pezzi di codice in embeddings.
    supporta sia la modalità singola che la modalità batch:
    la modalità batch è molto più veloce perché manda tutti i testi
    in una sola chiamata HTTP invece di una per nodo
    """
    def __init__(self):
        self.model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
        # usiamo 5500 per avere un margine di sicurezza rispetto al limite del modello
        self.max_chars = 5500
        self.embed_url = f"{OLLAMA_HOST}/api/embed"
        logger.info(f"embedder locale pronto (modello: {self.model}, host: {OLLAMA_HOST})")

    def _prepare(self, text: str, is_query: bool) -> str:
        """
        pulisce il testo e aggiunge il prefisso richiesto da nomic-embed-text.
        il prefisso dice al modello se stiamo indicizzando un documento o facendo una ricerca.
        la pulizia degli spazi riduce i token e velocizza la chiamata
        """
        clean = " ".join(text.split())
        prefix = "search_query: " if is_query else "search_document: "
        return (prefix + clean)[:self.max_chars]

    def get_embedding(self, text: str, is_query: bool = False):
        """
        embedding singolo. usato per le query dell'utente (is_query=True)
        e per i commit (testi singoli durante il salvataggio).
        per l'ingestion del codice usare get_embeddings_batch() che è molto più veloce
        """
        if not text or not text.strip():
            return None
        try:
            resp = requests.post(
                self.embed_url,
                json={"model": self.model, "input": self._prepare(text, is_query)},
                timeout=30,
            )
            resp.raise_for_status()
            # l'endpoint /api/embed restituisce sempre una lista anche per un singolo testo
            return resp.json()["embeddings"][0]
        except Exception as e:
            logger.error(f"errore embedding singolo (len={len(text)}): {e}")
            return None

    def get_embeddings_batch(self, texts: list, is_query: bool = False) -> list:
        """
        NUOVO: embedding di più testi in una sola chiamata HTTP.
        questo è il metodo principale da usare durante l'ingestion:
        invece di N chiamate (una per funzione), mandiamo tutti gli N testi insieme
        e otteniamo tutti gli N vettori in risposta.
        l'endpoint /api/embed di ollama accetta un array come 'input'.

        restituisce una lista della stessa lunghezza di 'texts':
        - se un testo è vuoto → None in quella posizione
        - se c'è un errore → None in quella posizione, il resto continua
        """
        if not texts:
            return []

        # separamo i testi validi da quelli vuoti, tenendo traccia degli indici originali
        # così il risultato finale ha la stessa lunghezza della lista di input
        valid_indices = []
        valid_texts = []
        for i, text in enumerate(texts):
            if text and text.strip():
                valid_indices.append(i)
                valid_texts.append(self._prepare(text, is_query))

        result = [None] * len(texts)

        if not valid_texts:
            return result

        try:
            resp = requests.post(
                self.embed_url,
                json={"model": self.model, "input": valid_texts},
                timeout=120,  # timeout più alto per batch grandi
            )
            resp.raise_for_status()
            embeddings = resp.json()["embeddings"]

            # riassemblare il risultato nelle posizioni originali
            for idx, emb in zip(valid_indices, embeddings):
                result[idx] = emb

        except Exception as e:
            logger.error(f"errore batch embedding ({len(valid_texts)} testi): {e}")
            # in caso di errore del batch, proviamo uno per uno come fallback
            logger.warning("fallback: ricalcolo embedding uno per uno")
            for i, text in zip(valid_indices, valid_texts):
                result[i] = self.get_embedding(texts[i], is_query)

        return result
