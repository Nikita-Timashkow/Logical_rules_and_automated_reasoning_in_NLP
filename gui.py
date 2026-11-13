import re
import tkinter as tk
from collections import defaultdict
from tkinter import messagebox, ttk

from engine import HIDDEN, _match, prove
from logic import is_var, parse_query, show
from main import RULES, consistent, entity_facts, readings
from morphology import sentence_to_facts
from thesaurus import PROBLEM

EXAMPLES = [
    "Черная кошка съела свежую рыбу",
    "Рыбу съела кошка",
    "Мама мыла раму",
    "Мать любит дочь",
    "Кошка спят",
    "Камень ест рыбу",
    "Стул ест суп",
    "Маленький мальчик читает интересную книгу",
    "Тигр ест мясо",
    "Врач читает газету",
]

# Готовые вопросы: текст → (запрос, {переменная: заголовок столбца})
QUESTIONS = {
    "Кто что делает?": ("действие(E, L) & агент(E, X)", {"X": "Кто", "E": "Действие"}),
    "Над кем или чем совершается действие?": ("действие(E, L) & пациенс(E, Y)",
                                              {"E": "Действие", "Y": "Над кем / чем"}),
    "Где подлежащее и сказуемое?": ("подлежащее(V, N)", {"N": "Подлежащее", "V": "Сказуемое"}),
    "Какие глаголы в предложении?": ("глаг(X, L, _, _, _)", {"X": "Слово", "L": "Начальная форма"}),
    "Кто или что здесь одушевлённое?": ("это(X, одушевленный)", {"X": "Объект"}),
    "Какие животные есть в тексте?": ("это(X, животное)", {"X": "Животное"}),
    "Есть ли в тексте люди?": ("это(X, человек)", {"X": "Человек"}),
    "Что здесь является едой?": ("это(X, еда)", {"X": "Еда"}),
    "Какие признаки у объектов?": ("свойство(X, P)", {"X": "Объект", "P": "Признак"}),
    "Кто сыт?": ("свойство(X, сытый)", {"X": "Кто"}),
}
CUSTOM = "Свой запрос…"
ALL = "все"

# Группы выведенных фактов для вкладки «Что выведено»
GROUPS = [
    ("Подлежащее", "подлежащее", lambda f: f"{f[2]}  →  сказуемое {f[1]}"),
    ("Прямое дополнение", "дополнение", lambda f: f"{f[2]}  ←  {f[1]}"),
    ("Определения", "определение", lambda f: f"{f[2]}  →  {f[1]}"),
    ("Действия", "действие", lambda f: f"{f[1]}  =  «{f[2]}»"),
    ("Агент (кто действует)", "агент", lambda f: f"{f[2]}  в действии {f[1]}"),
    ("Пациенс (над чем действие)", "пациенс", lambda f: f"{f[2]}  в действии {f[1]}"),
    ("Кем / чем является", "это", lambda f: f"{f[1]}  —  {f[2]}"),
    ("Место действия", "место", lambda f: f"{f[1]}  →  {f[2]}"),
    ("Где находится", "находится", lambda f: f"{f[1]}  —  {f[2]}"),
    ("Свойства", "свойство", lambda f: f"{f[1]}  —  {f[2]}"),
]
POS = {"сущ": "существительное", "прил": "прилагательное", "глаг": "глагол"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Логический вывод в NLP")
        self.geometry("1200x760")
        self.minsize(900, 600)
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 11))
        style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"))
        style.configure("TButton", font=("Segoe UI", 11))
        style.configure("TNotebook.Tab", font=("Segoe UI", 11), padding=(14, 6))
        self.facts, self.known, self.why, self.contradictions = [], [], {}, []
        self._build_top()
        self._build_tabs()
        self.sentence.set(EXAMPLES[0])
        self.analyze()

    # верхняя панель
    def _build_top(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Предложение:", font=("Segoe UI", 12)).pack(side="left")
        self.sentence = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.sentence, font=("Segoe UI", 13))
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda e: self.analyze())
        ttk.Button(top, text="Разобрать", command=self.analyze).pack(side="left")
        examples = ttk.Combobox(top, values=EXAMPLES, state="readonly", width=34,
                                font=("Segoe UI", 11))
        examples.set("Примеры…")
        examples.pack(side="left", padx=(8, 0))
        examples.bind("<<ComboboxSelected>>",
                      lambda e: (self.sentence.set(examples.get()), self.analyze()))
        row = ttk.Frame(self, padding=(12, 0, 10, 6))
        row.pack(fill="x")
        self.status = ttk.Label(row, font=("Segoe UI", 12, "bold"))
        self.status.pack(side="left")
        # выбор прочтения — виден, только когда непротиворечивых прочтений несколько
        self.reading_box = ttk.Combobox(row, state="readonly", width=34, font=("Segoe UI", 11))
        self.reading_box.bind("<<ComboboxSelected>>",
                              lambda e: self.select_reading(self.reading_box.current()))
        self.reading_label = ttk.Label(row, text="Прочтение:", font=("Segoe UI", 11))

    def _tree(self, parent, columns, widths, tree_col=None):
        frame = ttk.Frame(parent)
        show_mode = "tree headings" if tree_col else "headings"
        tree = ttk.Treeview(frame, columns=columns, show=show_mode)
        if tree_col:
            tree.heading("#0", text=tree_col[0])
            tree.column("#0", width=tree_col[1])
        for c, w in zip(columns, widths):
            tree.heading(c, text=c, anchor="w")
            tree.column(c, width=w, minwidth=w, stretch=True)
        ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        return frame, tree

    # вкладки
    def _build_tabs(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 1. Слова
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="1. Слова")
        ttk.Label(tab, text="Все варианты разбора от pymorphy3 и знания из словарей. "
                            "Какой разбор верный, решает вывод.",
                  font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 6))
        frame, self.words = self._tree(
            tab, ("Часть речи", "Начальная форма", "Род", "Число", "Падеж / переходность",
                  "Знания о слове"),
            (160, 170, 80, 80, 190, 300), tree_col=("Слово", 180))
        frame.pack(fill="both", expand=True)

        # 2. Что выведено
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="2. Что выведено")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="Нажмите на факт — справа появится цепочка правил, из которой он получен.",
                  font=("Segoe UI", 11)).pack(side="left")
        # фильтр: показать только факты одной сущности (Вася отдельно от Артема)
        self.entity_box = ttk.Combobox(row, state="readonly", width=22, font=("Segoe UI", 11))
        self.entity_box.pack(side="right")
        self.entity_box.bind("<<ComboboxSelected>>", lambda e: self.fill_derived())
        ttk.Label(row, text="Сущность:", font=("Segoe UI", 11)).pack(side="right", padx=6)
        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        frame, self.derived = self._tree(panes, (), (), tree_col=("Выведенный факт", 370))
        panes.add(frame, weight=1)
        frame, self.reason = self._tree(panes, ("Как получен",), (520,),
                                        tree_col=("Почему так?", 410))
        panes.add(frame, weight=1)
        self.derived_panes = panes
        # ширина левой панели задаётся, когда вкладку впервые показывают
        nb.bind("<<NotebookTabChanged>>", lambda e: self.after(30, self._fix_sash))
        self.derived.bind("<<TreeviewSelect>>", self.on_select_fact)

        # 3. Смысловые ошибки
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="3. Смысловые ошибки")
        ttk.Label(tab, text="Запрет («… -> ложь») нарушен, если вывод доказал все его посылки.",
                  font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 6))
        frame, self.errors = self._tree(tab, ("Как получен",), (760,),
                                        tree_col=("Противоречие", 520))
        frame.pack(fill="both", expand=True)

        # 4. Вопросы
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="4. Вопросы")
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="Вопрос:", font=("Segoe UI", 12)).pack(side="left")
        self.question = ttk.Combobox(row, values=list(QUESTIONS) + [CUSTOM], state="readonly",
                                     width=40, font=("Segoe UI", 11))
        self.question.set(list(QUESTIONS)[0])
        self.question.pack(side="left", padx=8)
        self.question.bind("<<ComboboxSelected>>", self.on_question_change)
        ttk.Button(row, text="Ответить", command=self.answer).pack(side="left")
        ttk.Button(row, text="Доказать методом резолюций",
                   command=self.show_proof).pack(side="left", padx=8)

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Запрос:", font=("Segoe UI", 12)).pack(side="left")
        self.query = tk.StringVar()
        self.query_entry = ttk.Entry(row, textvariable=self.query, font=("Consolas", 12))
        self.query_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.query_entry.bind("<Return>", lambda e: self.answer())
        self.on_question_change()

        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill="both", expand=True)
        self.answers_frame = ttk.Frame(panes)
        panes.add(self.answers_frame, weight=1)
        self.answers = None
        proof_frame = ttk.Frame(panes)
        panes.add(proof_frame, weight=1)
        self.proof = tk.Text(proof_frame, font=("Consolas", 11), wrap="word", height=10)
        sb = ttk.Scrollbar(proof_frame, orient="vertical", command=self.proof.yview)
        self.proof.configure(yscrollcommand=sb.set)
        self.proof.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _fix_sash(self):
        if self.derived_panes.winfo_width() > 600 and self.derived_panes.sashpos(0) < 400:
            self.derived_panes.sashpos(0, 470)

    #  анализ
    def analyze(self):
        text = self.sentence.get().strip()
        if not text:
            return
        self.ids, self.facts = sentence_to_facts(text)
        # слова как в предложении (с заглавными) — чтобы показывать «Никита», а не никита_1
        self.surface = re.findall(r"[А-Яа-яЁё]+", text)
        # прочтения: каждый вариант «кто подлежащее» разбирается отдельно
        all_readings = readings(self.facts)
        good = consistent(all_readings)
        if all(r.contradictions for r in good):
            good = good[:1]                     # ошибка в любом прочтении — показываем одно
        self.good = good
        self.rejected = [r for r in all_readings
                         if r.contradictions and all(r is not g for g in good)]
        labels = [f"{i}) " + (", ".join(f"подлежащее {s}" for s in r.subjects.values())
                              or "без подлежащего") for i, r in enumerate(good, 1)]
        self.reading_box.configure(values=labels)
        self.reading_box.current(0)
        self.reading_box.pack_forget()
        self.reading_label.pack_forget()
        if len(good) > 1:
            self.reading_box.pack(side="right")
            self.reading_label.pack(side="right", padx=6)
        self.fill_words()
        self.select_reading(0)

    def select_reading(self, i):
        self.r = self.good[i]
        self.known, self.why, self.contradictions = self.r.known, self.r.why, self.r.contradictions
        entities = sorted({f[1] for f in self.known if f[0] == "участник"},
                          key=lambda w: int(w.rsplit("_", 1)[1]))
        self.entity_box.configure(values=[ALL] + entities)
        self.entity_box.set(ALL)
        self.fill_derived()
        self.fill_errors()
        self.update_status()
        self.answer()

    def update_status(self):
        subjects = [f for f in self.known if f[0] == "подлежащее"]
        if not subjects:
            text, color = "✗ Нет подлежащего, согласованного со сказуемым — предложение неправильное", "#B3261E"
        elif self.contradictions:
            text, color = "✗ Смысловая ошибка — см. вкладку «Смысловые ошибки»", "#B3261E"
        elif len(self.good) > 1:
            text, color = f"⚠ Неоднозначность: {len(self.good)} прочтения — выберите справа", "#8A5A00"
        else:
            text, color = "✓ Предложение разобрано, противоречий со знаниями нет", "#1E6B35"
        if self.rejected and not self.contradictions:
            text += f"  (отброшено прочтений: {len(self.rejected)})"
        if PROBLEM:
            text += f"\n⚠ {PROBLEM}"
        self.status.configure(text=text, foreground=color)

    def fill_words(self):
        self.words.delete(*self.words.get_children())
        for wid in self.ids:
            parses = [f for f in self.facts if f[0] in POS and f[1] == wid]
            knowledge = [("одушевлённое" if f[2] == "одуш" else "неодушевлённое")
                         if f[0] == "одушевленность" else f"{f[2]} (RuWordNet)"
                         for f in self.facts if f[0] in ("одушевленность", "тезаурус") and f[1] == wid]
            node = self.words.insert("", "end", text=wid, open=True,
                                     values=("—" if not parses else "", "", "", "", "",
                                             ", ".join(knowledge)))
            seen = set()
            for f in parses:
                row = (POS[f[0]], f[2], f[3], f[4], f[5])
                if row not in seen:
                    seen.add(row)
                    self.words.insert(node, "end", text="", values=row)

    def fill_derived(self):
        self.derived.delete(*self.derived.get_children())
        self.reason.delete(*self.reason.get_children())
        self.fact_by_item = {}
        entity = self.entity_box.get()
        shown = self.known if entity in ("", ALL) else entity_facts(self.known, entity)
        for title, name, fmt in GROUPS:
            items = [f for f in shown if f[0] == name]
            if not items:
                continue
            group = self.derived.insert("", "end", text=f"{title}  ({len(items)})", open=True)
            for f in items:
                item = self.derived.insert(group, "end", text=fmt(f))
                self.fact_by_item[item] = f

    def fill_errors(self):
        self.errors.delete(*self.errors.get_children())
        if not self.contradictions:
            self.errors.insert("", "end", text="Противоречий нет")
        for rule, premises in self.contradictions:
            node = self.errors.insert("", "end", text="ЛОЖЬ", values=(f"запрет: {rule.text}",),
                                      open=True)
            seen = set()
            for p in premises:
                self.insert_reason(self.errors, node, p, seen)
        # прочтения, которые вывод отбросил из-за противоречия
        for r in self.rejected:
            who = ", ".join(f"подлежащее {s}" for s in r.subjects.values())
            top = self.errors.insert("", "end", text="Отброшенное прочтение",
                                     values=(who,), open=True)
            rule, premises = r.contradictions[0]
            node = self.errors.insert(top, "end", text="ЛОЖЬ", values=(f"запрет: {rule.text}",),
                                      open=True)
            seen = set()
            for p in premises:
                self.insert_reason(self.errors, node, p, seen, r.why)

    def insert_reason(self, tree, parent, fact, seen, why=None):
        """Дерево объяснения: факт → правило → посылки (рекурсивно)."""
        why = self.why if why is None else why
        if fact not in why:
            source = "дано (из RuWordNet)" if fact[0] == "тезаурус" else "дано (от pymorphy3)"
            tree.insert(parent, "end", text=show(fact), values=(source,))
            return
        rule, premises = why[fact]
        if fact in seen:
            tree.insert(parent, "end", text=show(fact), values=("см. выше",))
            return
        seen.add(fact)
        node = tree.insert(parent, "end", text=show(fact), values=(f"правило: {rule.text}",),
                           open=True)
        for p in premises:
            if p[0] not in HIDDEN:
                self.insert_reason(tree, node, p, seen, why)

    def on_select_fact(self, _event):
        sel = self.derived.selection()
        if not sel or sel[0] not in self.fact_by_item:
            return
        self.reason.delete(*self.reason.get_children())
        self.insert_reason(self.reason, "", self.fact_by_item[sel[0]], set())

    # вопросы
    def on_question_change(self, _event=None):
        q = self.question.get()
        if q in QUESTIONS:
            self.query.set(QUESTIONS[q][0])
            self.query_entry.configure(state="readonly")
        else:
            self.query_entry.configure(state="normal")
            self.query_entry.focus()
        if _event is not None:
            self.answer()

    def _parsed_query(self):
        try:
            return parse_query(self.query.get())
        except Exception:
            messagebox.showerror("Ошибка в запросе",
                                 "Запрос не удалось прочитать.\nПример: это(X, животное) & агент(E, X)")
            return None

    def answer(self):
        query = self._parsed_query()
        if query is None:
            return
        names = QUESTIONS.get(self.question.get(), (None, {}))[1]
        variables = sorted({a for atom in query for a in atom[1:] if is_var(a) and a[0] != "_"})
        # столбцы — в порядке, заданном в QUESTIONS («Кто», потом «Действие»)
        shown = [v for v in names if v in variables] if names else variables
        # все ответы: подстановки, при которых каждое условие есть среди выведенных фактов
        index = defaultdict(list)
        for f in self.known:
            index[f[0]].append(f)
        rows = []
        for s, _ in _match(query, index, {}, []):
            row = tuple(self.pretty(s.get(v, v)) for v in shown)
            if row not in rows:
                rows.append(row)
        # таблица ответов
        if self.answers is not None:
            self.answers.master.destroy()
        headers = [names.get(v, v) for v in shown] or ["Ответ"]
        frame, self.answers = self._tree(self.answers_frame, headers, [260] * len(headers))
        frame.pack(fill="both", expand=True)
        if not shown:
            rows = [("Да",)] if rows else []
        for row in rows:
            self.answers.insert("", "end", values=row)
        if not rows:
            self.answers.insert("", "end", values=("Не выводится из текста и правил",))
        self.proof.delete("1.0", "end")
        self.proof.insert("end", f"Найдено ответов: {len(rows)}.\n"
                                 "Нажмите «Доказать методом резолюций», чтобы увидеть доказательство.")

    def pretty(self, value):
        """никита_1 → «Никита», помог_2 → «помог»: слово так, как оно написано в
        предложении. Если одно и то же слово встречается дважды — с номером."""
        text = show(value)
        m = re.fullmatch(r"(.+)_(\d+)", text)
        if not m or not (1 <= int(m.group(2)) <= len(self.surface)):
            return text
        word = self.surface[int(m.group(2)) - 1]
        repeats = sum(1 for i in self.ids if i.rsplit("_", 1)[0] == m.group(1))  # разные сущности
        return f"{word} ({m.group(2)})" if repeats > 1 else word

    def show_proof(self):
        query = self._parsed_query()
        if query is None:
            return
        answer, protocol = prove(RULES, self.r.facts, query)
        self.proof.delete("1.0", "end")
        if answer is None:
            self.proof.insert("end", "Не доказывается: пустой дизъюнкт не выводится.")
            return
        visible = {k: v for k, v in answer.items() if not k.startswith("_")}
        self.proof.insert("end", "Доказано. Первый найденный ответ: "
                          + ", ".join(f"{k} = {show(v)}" for k, v in visible.items()) + "\n\n")
        self.proof.insert("end", protocol)


if __name__ == "__main__":
    App().mainloop()
