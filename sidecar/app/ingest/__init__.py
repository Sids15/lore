"""Ingestion pipeline for the Code Index (Index A).

Turns a repository's source files into embedded, searchable chunks:

    walk files -> tree-sitter AST chunk -> contextual enrichment -> embed -> LanceDB
"""
