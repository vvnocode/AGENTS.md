def greet(name):
    return "Helo, " + name + "!"


def shout(name):
    n = name
    n = n.upper()
    r = ""
    for ch in n:
        r = r + ch
    return r + "!!!"
