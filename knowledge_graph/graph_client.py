from gqlalchemy import Memgraph

class GraphClient:
    def __init__(self, host="127.0.0.1", port=7687):
        # inizializza la connessione con il database Memgraph
        self.memgraph = Memgraph(host, port)
        print(f"Connesso a Memgraph su {host}:{port}")

    def execute_query(self, query, parameters=None):
        """
        esegue una query Cypher e restituisce i risultati
        """
        try:
            return list(self.memgraph.execute_and_fetch(query, parameters))
        except Exception as e:
            print(f"Errore nell'esecuzione della query: {e}")
            return []

    def close(self):
        # metodo per chiudere la connessione, gestito internamente da gqlalchemy
        pass