"""Git History Index (Index B).

Walks a repository's commits, summarises each with the LLM (the *summary* is what
gets embedded, not the raw diff), and records commit/file/authorship/blame data,
so Lore can answer questions about how the code evolved and who changed what.
"""
