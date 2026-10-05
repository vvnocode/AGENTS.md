def shorten(text, width):
    if len(text) <= width:
        return text
    return text[:width]
