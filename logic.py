import re
from dataclasses import dataclass


def is_var(t):
    return isinstance(t, str) and (t[0] == "_" or "A" <= t[0] <= "Z")


def show(t):
    """Атом в привычной записи: это(X, кошка)."""
    if isinstance(t, tuple):
        return f"{t[0]}({', '.join(show(a) for a in t[1:])})"
    if is_var(t) and t[0] == "_":
        return "_"  # анонимная переменная
    return t


def subst(t, s):
    """Применить подстановку s (словарь переменная → терм) к терму t."""
    if is_var(t):
        return s.get(t, t)
    if isinstance(t, tuple):
        return (t[0],) + tuple(subst(a, s) for a in t[1:])
    return t


# Унификация

def occurs(x, t):
    return t == x or (isinstance(t, tuple) and any(occurs(x, a) for a in t[1:]))


def disagreement(a, b):
    """Первая слева пара различающихся подвыражений."""
    if (isinstance(a, tuple) and isinstance(b, tuple)
            and a[0] == b[0] and len(a) == len(b)):
        for x, y in zip(a[1:], b[1:]):
            if x != y:
                return disagreement(x, y)
    return a, b


def unify(e1, e2, s=None, log=None):
    """Наиболее общий унификатор e1 и e2 (продолжающий s) или None.
    Если передан список log, в него пишется протокол шагов."""
    s = dict(s or {})
    while True:
        a, b = subst(e1, s), subst(e2, s)
        if a == b:
            if log is not None:
                log.append(f"выражения совпали: {show(a)}  ⇒  НОУ найден")
            return s
        u, v = disagreement(a, b)
        if not is_var(u):
            u, v = v, u
        if log is not None:
            log.append(f"множество рассогласования D = {{{show(u)}, {show(v)}}}")
        if not is_var(u):
            if log is not None:
                log.append("в D нет переменной ⇒ не унифицируемы")
            return None
        if occurs(u, v):
            if log is not None:
                log.append(f"{u} входит в {show(v)} ⇒ не унифицируемы")
            return None
        s = {x: subst(t, {u: v}) for x, t in s.items()}
        s[u] = v
        if log is not None:
            log.append("σ = {" + ", ".join(f"{show(t)}/{x}" for x, t in s.items()) + "}")


# Разбор текстовой записи атомов и правил

_TOKEN = re.compile(r"[\w']+|[(),]")
_anon = [0]


def parse_atom(text):
    tokens = _TOKEN.findall(text)
    pos = 0

    def term():
        nonlocal pos
        name = tokens[pos]
        pos += 1
        if name == "_":                      # анонимная переменная
            _anon[0] += 1
            return f"_{_anon[0]}"
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
            args = [term()]
            while tokens[pos] == ",":
                pos += 1
                args.append(term())
            pos += 1                          # ")"
            return (name, *args)
        return name

    return term()


@dataclass(frozen=True)
class Rule:
    body: tuple          # посылки (атомы)
    head: object         # заключение (атом) или None для «ложь»
    text: str            # исходная запись — для объяснений


def parse_rules(text):
    rules = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        left, right = line.split("->")
        body = tuple(parse_atom(p) for p in left.split("&"))
        right = right.strip()
        head = None if right == "ложь" else parse_atom(right)
        rules.append(Rule(body, head, line))
    return rules


def parse_query(text):
    """Запрос — конъюнкция атомов: это(X, животное) & агент(E, X)"""
    return [parse_atom(p) for p in text.split("&")]
