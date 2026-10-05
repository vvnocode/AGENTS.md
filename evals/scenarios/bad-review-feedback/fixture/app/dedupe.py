def dedupe(items):
    """Remove duplicates, keeping the first occurrence of each item."""
    return list(dict.fromkeys(items))
