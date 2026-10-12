#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that a comment/documentation translation did not change code.

    tools/check-translation-safety.py ORIGINAL_ROOT CURRENT_ROOT [PATH...]

For every file present in both trees (or only the given relative PATHs):

- Python: the syntax trees must be identical once docstrings are removed and
  every string constant is replaced by a placeholder. Changed string
  constants are listed so that a person can confirm they are developer
  messages (logs, errors) and not data (paths, keys, patterns, user text).
- Everything else (shell, Lua, QML, CSS, JavaScript, configuration): every
  changed line that is not a comment on both sides is listed for review.

Exit code 1 if a Python syntax tree differs or a file no longer parses.
"""
import ast
import difflib
import os
import sys

COMMENT_PREFIXES = ("#", "--", "//", "/*", "*", "<!--", ";")


class _Strip(ast.NodeTransformer):
    def _drop_docstring(self, node):
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
        return node

    def visit_Module(self, node):
        self.generic_visit(node)
        return self._drop_docstring(node)

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_Module

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<str>"), node)
        return node

    def visit_JoinedStr(self, node):
        return ast.copy_location(ast.Constant(value="<str>"), node)


def _strings(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def is_python(path, text):
    return path.endswith(".py") or text.startswith("#!/usr/bin/python") or \
        text.startswith("#!/usr/bin/env python")


def check_python(rel, old, new, report):
    try:
        t_old, t_new = ast.parse(old), ast.parse(new)
    except SyntaxError as e:
        report.append("FAIL %s: does not parse (%s)" % (rel, e))
        return False
    d_old = ast.dump(_Strip().visit(ast.parse(old)))
    d_new = ast.dump(_Strip().visit(ast.parse(new)))
    if d_old != d_new:
        report.append("FAIL %s: code changed (not only comments, docstrings and strings)" % rel)
        return False
    s_old, s_new = _strings(t_old), _strings(t_new)
    docs_old = {d for d in s_old if "\n" in d}
    for a, b in zip(s_old, s_new):
        if a != b and a not in docs_old:
            report.append("STR  %s: %r -> %r" % (rel, a[:90], b[:90]))
    return True


def _is_comment(line):
    s = line.strip()
    return not s or s.startswith(COMMENT_PREFIXES)


def check_text(rel, old, new, report):
    sm = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    a_lines, b_lines = old.splitlines(), new.splitlines()
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        changed_old = [line for line in a_lines[i1:i2] if not _is_comment(line)]
        changed_new = [line for line in b_lines[j1:j2] if not _is_comment(line)]
        for line in changed_old:
            report.append("LINE %s: - %s" % (rel, line.strip()[:140]))
        for line in changed_new:
            report.append("LINE %s: + %s" % (rel, line.strip()[:140]))
    return True


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    root_old, root_new, only = argv[1], argv[2], argv[3:]
    rels = only
    if not rels:
        rels = []
        for d, _dirs, files in os.walk(root_old):
            for f in files:
                rels.append(os.path.relpath(os.path.join(d, f), root_old))
    report, ok = [], True
    for rel in sorted(rels):
        po, pn = os.path.join(root_old, rel), os.path.join(root_new, rel)
        if not os.path.isfile(pn) or not os.path.isfile(po):
            continue
        try:
            old = open(po, encoding="utf-8").read()
            new = open(pn, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        if old == new:
            continue
        if is_python(rel, old):
            ok = check_python(rel, old, new, report) and ok
        else:
            check_text(rel, old, new, report)
    print("\n".join(report) if report else "no code changes")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
