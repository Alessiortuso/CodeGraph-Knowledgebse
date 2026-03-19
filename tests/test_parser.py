"""Test per ingestion/parser.py"""

import pytest
from ingestion.parser import CodeNode


# --- CodeNode ---

def test_codenode_creazione_base():
    nodo = CodeNode(
        name="calcola_totale",
        type="function",
        content="def calcola_totale(a, b):\n    return a + b",
        start_line=10,
        end_line=11
    )
    assert nodo.name == "calcola_totale"
    assert nodo.type == "function"
    assert nodo.start_line == 10
    assert nodo.end_line == 11


