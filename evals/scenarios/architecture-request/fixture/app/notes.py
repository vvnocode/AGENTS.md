from app import store


def add_note(path, text):
    notes = store.load(path)
    notes.append({"id": len(notes) + 1, "text": text})
    store.save(path, notes)
    return notes[-1]


def list_notes(path):
    return store.load(path)
