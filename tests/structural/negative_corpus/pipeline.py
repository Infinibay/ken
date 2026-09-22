def strip(text): return text.strip()
def lower(text): return text.lower()
def normalize(text):
    for step in (strip, lower):
        text = step(text)
    return text
