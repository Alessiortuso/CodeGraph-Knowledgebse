import os
from gqlalchemy import Memgraph

# serve per gestire la comunicazione tra python e il database memgraph
# questo modulo funge da ponte unico: si occupa di connettersi al db,
# gestire le variabili di configurazione (host/port) e inviare le query cypher
# catturando eventuali errori per non far crashare l'intera applicazione
class GraphClient:
    def __init__(self, host=None, port=None):
        # 1. controllo se esistono variabili d ambiente, impostate per esempio da docker
        # 2. se non esistono uso i valori di default (127.0.0.1 è l'indirizzo del pc locale)
        # questo serve perché se domani sposto il database su un altro server non devi cambiare il codice
        env_host = os.environ.get("MEMGRAPH_HOST", "127.0.0.1")
        env_port = int(os.environ.get("MEMGRAPH_PORT", 7687))

        # se nel codice scrivo GraphClient("mioserver.com") uso quello passato a mano
        # altrimenti prendo quello automatico che arriva dal sistema o dall ambiente
        self.host = host if host else env_host
        self.port = port if port else env_port

        # qui inizializzo la connessione vera e propria usando la libreria gqlalchemy
        # memgraph usa il protocollo bolt sulla porta 7687 di default
        self.memgraph = Memgraph(self.host, self.port)
        print(f"connesso a memgraph su {self.host}:{self.port}")

    def execute_query(self, query, parameters=None):
        """
        esegue una query cypher e restituisce i risultati come una lista pulita
        """
        try:
            # usiamo execute_and_fetch che è il comando per dire a memgraph:
            # "fai questa operazione e portami indietro i risultati"
            # usiamo list() per trasformare il generatore in una lista manipolabile subito
            return list(self.memgraph.execute_and_fetch(query, parameters))
        except Exception as e:
            if not str(e):
                # eccezione senza messaggio: tipico dei DDL (CREATE INDEX, CREATE VECTOR INDEX)
                # che non restituiscono righe. proviamo con execute() che non si aspetta risultati.
                try:
                    self.memgraph.execute(query, parameters)
                    return []
                except Exception as e2:
                    print(f"errore nell esecuzione della query: {e2}")
                    return []
            print(f"errore nell esecuzione della query: {e}")
            return []

    def close(self):
        # metodo per chiudere la connessione se necessario
        # con gqlalchemy di solito non serve farlo a mano perché gestisce tutto lui
        pass