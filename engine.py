from collections import defaultdict
from logic import is_var, show, subst, unify

# Прямой вывод

def _match(body, index, s, premises):
    """Все способы сопоставить посылки правила с известными фактами."""
    if not body:
        yield s, premises
        return
    first = body[0]
    for fact in index[first[0]]:
        s2 = unify(first, fact, s)
        if s2 is not None:
            yield from _match(body[1:], index, s2, premises + [fact])


def forward_chain(rules, facts):
    """Возвращает (все факты, обоснования, противоречия)."""
    known = list(dict.fromkeys(facts))
    why = {}                       # факт → (правило, посылки)
    contradictions = []            # (правило-запрет, посылки)
    while True:
        index = defaultdict(list)
        for f in known:
            index[f[0]].append(f)
        new = []
        for rule in rules:
            for s, premises in _match(rule.body, index, {}, []):
                if rule.head is None:
                    if (rule, premises) not in contradictions:
                        contradictions.append((rule, premises))
                    continue
                fact = subst(rule.head, s)
                if fact not in why and fact not in known and fact not in new:
                    why[fact] = (rule, premises)
                    new.append(fact)
        if not new:
            return known, why, contradictions
        known += new


HIDDEN = ("разные", "перед", "клауза", "общее_подлежащее")      # служебные факты о порядке слов — не печатаем


def explain(fact, why, indent="", shown=None):
    """Дерево объяснения: каким правилом и из чего получен факт.
    Уже объяснённые факты повторно не раскрываются."""
    shown = set() if shown is None else shown
    if fact not in why:
        return f"{indent}{show(fact)}   [дано]"
    if fact in shown:
        return f"{indent}{show(fact)}   [см. выше]"
    shown.add(fact)
    rule, premises = why[fact]
    lines = [f"{indent}{show(fact)}   [правило: {rule.text}]"]
    lines += [explain(p, why, indent + "    ", shown) for p in premises if p[0] not in HIDDEN]
    return "\n".join(lines)


# Метод резолюций

def lit_str(lit):
    sign, atom = lit
    return ("" if sign else "¬") + show(atom)


def clause_str(clause):
    return " ∨ ".join(lit_str(l) for l in clause) if clause else "□"


def rule_to_clause(rule):
    clause = tuple((False, a) for a in rule.body)
    return clause + (((True, rule.head),) if rule.head is not None else ())


def _rename(clause, k):
    """Переименование переменных дизъюнкта (чтобы не совпали с чужими)."""
    def r(t):
        if is_var(t):
            return f"{t.split('_')[0] or '_' + t.split('_')[1]}_{k}"
        if isinstance(t, tuple):
            return (t[0],) + tuple(r(a) for a in t[1:])
        return t
    return tuple((sign, r(atom)) for sign, atom in clause)


def _normalize(clause):
    """Ключ для отсева повторов: переменные → V0, V1, ... по порядку."""
    names = {}

    def r(t):
        if is_var(t):
            return names.setdefault(t, f"V{len(names)}")
        if isinstance(t, tuple):
            return (t[0],) + tuple(r(a) for a in t[1:])
        return t
    return tuple(sorted(set((sign, r(atom)) for sign, atom in clause), key=str))


def prove(rules, facts, query, max_steps=200000):
    """Доказать ∃(query) из правил и фактов. Возвращает (ответ, протокол)
    или (None, None), если вывести пустой дизъюнкт нельзя."""
    base = [(rule_to_clause(r), r.text) for r in rules]
    base += [(((True, f),), "факт: " + show(f)) for f in facts]

    answer_vars = sorted({a for atom in query for a in atom[1:] if is_var(a)})
    goal = tuple((False, a) for a in query) + ((True, ("Ans", *answer_vars)),)

    # каждая запись: (дизъюнкт, родитель, использованный дизъюнкт базы)
    derived = [(goal, None, "отрицание запроса + Ans")]
    queue, seen = [0], {_normalize(goal)}
    steps = 0
    while queue and steps < max_steps:
        i = queue.pop(0)                                  # поиск в ширину
        clause = derived[i][0]
        # резольвируем самый левый литерал запроса (не Ans) с базой
        pos = next((k for k, l in enumerate(clause) if l[1][0] != "Ans"), None)
        if pos is None:
            continue
        sign, atom = clause[pos]
        for b_clause, b_name in base:
            steps += 1
            b_clause = _rename(b_clause, len(derived))
            for j, (b_sign, b_atom) in enumerate(b_clause):
                if b_sign == sign or b_atom[0] != atom[0]:
                    continue
                s = unify(atom, b_atom)
                if s is None:
                    continue
                rest = clause[:pos] + clause[pos + 1:]
                resolvent = tuple((sg, subst(a, s)) for sg, a in
                                  b_clause[:j] + b_clause[j + 1:] + rest)
                key = _normalize(resolvent)
                if key in seen:
                    continue
                seen.add(key)
                derived.append((resolvent, i, b_name))
                if all(a[0] == "Ans" for _, a in resolvent):
                    return _answer(resolvent, answer_vars), _protocol(derived, len(derived) - 1)
                queue.append(len(derived) - 1)
    return None, None


def _answer(clause, answer_vars):
    ans_atom = clause[0][1]
    return dict(zip(answer_vars, ans_atom[1:]))


def _protocol(derived, last):
    chain = []
    while last is not None:
        chain.append(derived[last])
        last = derived[last][1]
    chain.reverse()
    lines = []
    for n, (clause, parent, used) in enumerate(chain, 1):
        how = used if parent is None else f"резольвента ({n - 1}) и [{used}]"
        lines.append(f"{n:>2}. {clause_str(clause)}\n      ← {how}")
    lines.append("    Остался только Ans(…) — это пустой дизъюнкт □ с ответом.")
    return "\n".join(lines)
