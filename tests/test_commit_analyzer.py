from unittest.mock import MagicMock
from analytics.commit_analyzer import CommitAnalyzer

"""
commit analyzer dipende completamente dal database per le query principali,
quindi non testo i risultati (quelli dipendono dai dati in Memgraph).
quello che posso testare è la logica di sanitizzazione del parametro limit:
se qualcuno passa un valore non valido, il codice deve
usare un valore di default sicuro invece di crashare.

faccio un MOCK DEL DATABASE:
uso magicmock per creare un oggetto finto che si comporta
come il vero db_client, ma senza connettersi a nessun database.
posso poi controllare con quali argomenti è stato chiamato.
"""


def _create_analyzer():
    """crea un CommitAnalyzer con un database finto già configurato."""
    # MagicMock crea un oggetto che accetta qualsiasi chiamata di metodo
    # e restituisce una lista vuota di default
    mock_db = MagicMock()
    mock_db.execute_query.return_value = []
    return CommitAnalyzer(mock_db), mock_db


# TEST SU get_hotspots — verifica del parametro limit


def test_hotspots_invalid_string_limit_uses_default():
    # se qualcuno passa una stringa come limit, il codice deve usare 5 come fallback
    analyzer, mock_db = _create_analyzer()
    analyzer.get_hotspots("mio_progetto", limit="non_un_numero")

    # recuperiamo la query cypher che è stata passata a execute_query
    query_usata = mock_db.execute_query.call_args[0][0]
    assert "LIMIT 5" in query_usata


def test_hotspots_none_limit_uses_default():
    # none non è convertibile in int, deve usare il valore di default 5
    analyzer, mock_db = _create_analyzer()
    analyzer.get_hotspots("mio_progetto", limit=None)

    query_usata = mock_db.execute_query.call_args[0][0]
    assert "LIMIT 5" in query_usata


def test_hotspots_valid_limit_is_used():
    # con un limit valido (es. 10), la query deve usare quel valore
    analyzer, mock_db = _create_analyzer()
    analyzer.get_hotspots("mio_progetto", limit=10)

    query_usata = mock_db.execute_query.call_args[0][0]
    assert "LIMIT 10" in query_usata


# TEST SU get_recent_activity


def test_recent_activity_invalid_string_limit_uses_default():
    analyzer, mock_db = _create_analyzer()
    analyzer.get_recent_activity("mio_progetto", limit="xyz")

    query_usata = mock_db.execute_query.call_args[0][0]
    assert "LIMIT 3" in query_usata


def test_recent_activity_valid_limit_is_used():
    analyzer, mock_db = _create_analyzer()
    analyzer.get_recent_activity("mio_progetto", limit=7)

    query_usata = mock_db.execute_query.call_args[0][0]
    assert "LIMIT 7" in query_usata


# TEST CHE IL NOME PROGETTO VENGA PASSATO AL DATABASE
# verifico che i metodi passino correttamente il nome del progetto alla query


def test_hotspots_passes_correct_project_name():
    analyzer, mock_db = _create_analyzer()
    analyzer.get_hotspots("knowledge_base")

    # il secondo argomento di execute_query è il dizionario dei parametri
    parametri = mock_db.execute_query.call_args[0][1]
    assert parametri["p"] == "knowledge_base"


def test_expertise_map_passes_correct_project_name():
    analyzer, mock_db = _create_analyzer()
    analyzer.get_expertise_map("knowledge_base")

    parametri = mock_db.execute_query.call_args[0][1]
    assert parametri["p"] == "knowledge_base"
