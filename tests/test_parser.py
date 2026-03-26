import pytest
from ingestion.parser import CodeNode, CodeGraphParser

"""
per ora testo solo le funzioni che non dipendono da servizi esterni (database, ollama, rete)

"""


# TEST SU CodeNode
# CodeNode è una semplice struttura dati, verifico che si crei correttamente


def test_codenode_basic_creation():
    # creo un nodo con tutti i campi e verifico che i valori siano salvati
    nodo = CodeNode(
        name="calcola_totale",
        type="function",
        content="def calcola_totale(a, b):\n    return a + b",
        start_line=10,
        end_line=11,
    )
    assert nodo.name == "calcola_totale"
    assert nodo.type == "function"
    assert nodo.start_line == 10
    assert nodo.end_line == 11


def test_codenode_calls_defaults_to_empty_list():
    # se non passiamo calls, deve essere una lista vuota, non None
    # questo è importante perché il codice fa nodes[-1].calls.append(...)
    # e se calls fosse None, crasherebbe.
    nodo = CodeNode(
        name="f", type="function", content="def f(): pass", start_line=1, end_line=1
    )
    assert nodo.calls == []


def test_codenode_calls_not_shared_between_instances():
    # bug classico in python: se il default fosse calls=[] nella firma,
    # tutti i nodi condividerebbero la stessa lista
    # il codice usa 'calls if calls is not None else []' proprio per evitarlo
    # verifico che due nodi abbiano liste separate
    nodo1 = CodeNode(name="a", type="function", content="", start_line=1, end_line=1)
    nodo2 = CodeNode(name="b", type="function", content="", start_line=2, end_line=2)
    nodo1.calls.append("qualcosa")
    assert nodo2.calls == []  # nodo2 non deve essere contaminato da nodo1


# TEST SU detect_language
# questa funzione guarda l'estensione del file e restituisce il linguaggio


def test_detect_language_python():
    parser = CodeGraphParser()
    assert parser._detect_language("main.py") == "python"


def test_detect_language_java():
    parser = CodeGraphParser()
    assert parser._detect_language("Main.java") == "java"


def test_detect_language_javascript():
    parser = CodeGraphParser()
    assert parser._detect_language("app.js") == "javascript"


def test_detect_language_unknown_extension_raises_error():
    # se l'estensione non è supportata, mi aspetto un ValueError col mrispettivo messaggio
    # pytest.raises è il modo corretto di testare che un errore venga sollevato
    parser = CodeGraphParser()
    with pytest.raises(ValueError):
        parser._detect_language("documento.pdf")


# TEST SU parse_file
# qui usiamo tmp_path: un fixture built-in di pytest che crea una cartella
# temporanea per i test e la cancella automaticamente alla fine
# così non lasciamo file sporchi sul disco


def test_parse_file_finds_python_function(tmp_path):
    # creiamo un file python temporaneo con una funzione semplice
    codice = "def saluta(nome):\n    return 'ciao ' + nome\n"
    file = tmp_path / "esempio.py"
    file.write_text(codice, encoding="utf8")

    parser = CodeGraphParser()
    nodi = parser.parse_file(str(file))

    # cerchiamo tra i nodi trovati uno che sia una funzione di nome "saluta"
    funzioni = [n for n in nodi if n.type == "function" and n.name == "saluta"]
    assert len(funzioni) == 1, "dovrebbe trovare esattamente la funzione 'saluta'"


def test_parse_file_finds_python_class(tmp_path):
    codice = "class Motore:\n    def avvia(self):\n        pass\n"
    file = tmp_path / "motore.py"
    file.write_text(codice, encoding="utf8")

    parser = CodeGraphParser()
    nodi = parser.parse_file(str(file))

    classi = [n for n in nodi if n.type == "class" and n.name == "Motore"]
    assert len(classi) == 1


def test_parse_file_flat_script_fallback(tmp_path):
    # un file python con solo istruzioni semplici (nessuna funzione o classe)
    # deve essere salvato come nodo di tipo script, altrimenti andrebbe perso
    codice = "x = 1\ny = 2\nprint(x + y)\n"
    file = tmp_path / "script.py"
    file.write_text(codice, encoding="utf8")

    parser = CodeGraphParser()
    nodi = parser.parse_file(str(file))

    script_nodes = [n for n in nodi if n.type == "script"]
    assert len(script_nodes) == 1
    assert script_nodes[0].name == "script.py"


def test_parse_file_records_function_calls(tmp_path):
    # quando una funzione ne chiama un'altra, vogliamo tracciarlo nel grafo
    # verifichiamo che calls contenga il nome della funzione chiamata
    codice = "def principale():\n    helper()\n\ndef helper():\n    pass\n"
    file = tmp_path / "chiamate.py"
    file.write_text(codice, encoding="utf8")

    parser = CodeGraphParser()
    nodi = parser.parse_file(str(file))

    principale = next((n for n in nodi if n.name == "principale"), None)
    assert principale is not None
    assert "helper" in principale.calls

