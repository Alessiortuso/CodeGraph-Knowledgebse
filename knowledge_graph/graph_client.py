import os
from gqlalchemy import Memgraph

class GraphClient:
    def __init__(self, host=None, port=None):
        # 1. Controlla se esistono variabili d'ambiente (impostate da Docker)
        # 2. Se non esistono, usa i valori di default (per esecuzione locale)
        env_host = os.environ.get("MEMGRAPH_HOST", "127.0.0.1")
        env_port = int(os.environ.get("MEMGRAPH_PORT", 7687))

        # Se passi host/port manualmente nell'init hanno la precedenza, 
        # altrimenti usa quelli dell'ambiente
        self.host = host if host else env_host
        self.port = port if port else env_port

        # Inizializza la connessione
        self.memgraph = Memgraph(self.host, self.port)
        print(f"Connesso a Memgraph su {self.host}:{self.port}")

    def execute_query(self, query, parameters=None):
        """
        Esegue una query Cypher e restituisce i risultati.
        """
        try:
            # Usiamo execute_and_fetch per ottenere i risultati come lista
            return list(self.memgraph.execute_and_fetch(query, parameters))
        except Exception as e:
            # Stampiamo l'errore specifico così capiamo cosa non va
            print(f"Errore nell'esecuzione della query: {e}")
            return []

    def close(self):
        # Metodo per chiudere la connessione, gestito internamente da gqlalchemy
        pass