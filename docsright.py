"""Spell checker for comments in Python code.

It supports two types of file:

*   `.md`: markdown files
*   `.py`: python files
*   `.ipynb`: jupyter notebook files

In markdown files, it treats all lines,
in python files only the lines in docstrings,
in notebook files only the markdown contained in markdown cells.

All strings that belong to code or math are replaces by `CODE` and `MATH`, resp.

Also other strings that may lead to false positives are removed, such as
hyperlinks and path names.

The resulting material is separated into words, and these are fed to a
spell checker.

The wrong words are listed in 2 files, from which it is easy to correct mistakes
in the original and to add words to the allowed words.

The program works on the basis of a specific project, a directory under
`projects` in this repo.

That directory should contain a file `tasks.txt` that specifies a number of
input directories to check.

The output will end up in the same project directory, in the files

*   `summary.txt`

    Contains the mistakes in the form

    ```
    [wrong]=>[correction]
    ```

    !!! hint "Vim macros"
        If you open this file and next to it the file `allowed.txt`,
        you can record a Vim macro that adds a wrong word to the file with
        allowed words, then deletes the wrong word from `summary.txt` and moves the
        cursor to the next word. If you assing this macro to the letter `g`,
        you can press `@g` repeatedly to change the status of wrong words to
        allowed.

*   `locations.txt`

    Contains the mistakes in the form

    ```
    [wrong]=>[correction] [path] [section]
    ```

    !!! hint "Vim macros"
        If you open this file and next to it an arbitrary file
        you can record a vim macro that stores the wrong, correction, path and section
        parts into registers (say `w`, `c`, `f`, `p` respectively),
        and then moves to the other window, opens the file
        indicated with `path` and searches for `wrong`.

        If you want to replace the word by the suggestion, you can type
        `cw<Ctrl r>c<Esc> to do that. Moreover,
        You can type `/<Ctr r>p` to search for the specific section if needed.
"""
import sys
import ast
import re
from nbformat import read as nbRead, NO_CONVERT
from symspellpy import SymSpell, Verbosity

from tf.core.files import (
    fileExists,
    initTree,
    isFile,
    isDir,
    dirAllFiles,
    expanduser as ex,
    unexpanduser as ux,
    abspath,
)
from tf.core.helpers import console


HELP = """
USAGE

./docsright.sh project

where

project is a directory under projects in this repo.
"""


TTTICK_RE = re.compile(
    r"""
        ```
        .*?
        ```
    """,
    re.S | re.X,
)
TTICK_RE = re.compile(r"""``[^`\n]*``""")
TICK_RE = re.compile(r"""`[^`]*`""")

MATH_RE = re.compile(r"""\$[^$\n]+\$""", re.S)
MATHD_RE = re.compile(r"""\$\$.+?\$\$""", re.S)
MATHA_RE = re.compile(r"""\\\(.+?\\\)""", re.S)
BRACES_RE = re.compile(r"""\{\{.+?\}\}""", re.S)

OLD_TTICK_RE = re.compile(
    r"""
        (?:^|\n)
        \s*
        ```
        (?:\s*[a-z]+\s*)?
        \s*\n
        .*?
        \n
        \s*
        ```
        \s*
        (?:\n|$)
    """,
    re.S | re.X,
)
ELEM_DEL1_RE = re.compile(r"""<(td|th|pre|code)\b[^>]*>.*?</\1>""", re.S | re.I)
ELEM_DEL2_RE = re.compile(r"""<(style|script|span)\b[^>]*>.*?</\1>""", re.S | re.I)
ELEM_UNWRAP_RE = re.compile(r"""</?(?:[a-z]+[0-9]*)\b[^>]*>""", re.S | re.I)
CMT_RE = re.compile(r"""<!--.*?-->""", re.S)


INITIALS_RE = re.compile(r"""^[A-Z][a-z]?$""")
HEX_RE = re.compile(r"""^[a-f0-9]+$""", re.I)
NUM_PL = re.compile(r"""^[0-9]+s$""", re.I)
SIZES_RE = re.compile(r"""^[0-9][0-9.]*(?:th|st|nd|rd|x|pt|(?:[KMGTP]B?))$""", re.I)

SYM_RE = re.compile(r"""«[a-zA-Z0-9_]*»""")


PARAM_RE = re.compile(
    r"""
        ^
        [a-zA-Z0-9_]+
        (?:
            ,
            \s*
            [a-zA-Z0-9]+
        )*
        :
        \s+
        (?:
            string|
            boolean|
            integer|
            float|
            tuple|
            list|
            dict|
            function|
            set|
            frozenset|
            iterable|
            object|
            mixed |
            void |
            AttrDict |
            np\ array |
            image\ as\ np\ array
        )
    """,
    re.M | re.X,
)

RETURN_RE = re.compile(
    r"""
        ^
        \s*
        (?:
            string|
            boolean|
            integer|
            tuple|
            list|
            dict|
            function|
            set|
            frozenset|
            iterable|
            object|
            mixed |
            AttrDict
        )
        \s*
        $
    """,
    re.M | re.X,
)

DOTNAME_RE = re.compile(
    r"""
        \b
        [a-zA-Z0-9_-]+
        (?:
            [./]
            [a-zA-Z0-9_-]+
        )+
        \b
    """,
    re.X,
)


ALINK_RE = re.compile(r"""\[[^]]+\]\[[^]]+\]""")
ILINK_RE = re.compile(r"""!\[[^]]+\]\([^)]+\)""")
LINK_RE = re.compile(r"""\[([^]]+)\]\([^)]+\)""")
NLINK_RE = re.compile(r"""https?://[a-z0-9_./-]*""")
HEADING_RE = re.compile(r"""(?:^|")#+\s+(.*?)\s*(?:$|\\n)""", re.M)
HEAD_COLON_RE = re.compile(r"""^[ #]*:::\s*.*$""", re.M)

PNAME_RE = re.compile(r"""^[a-zA-Z0-9~_.()-]+$""")


def linkRepl(match):
    body = match.group(1)
    result = " LINK " if PNAME_RE.match(body) else body
    return result


def headRepl(match):
    title = match.group(1)
    result = " HEAD " if PNAME_RE.match(title) else title
    return result


WORD_RE = re.compile(r"""\w+""")

SUMMARY_FILE = "summary.txt"
LOCATIONS_FILE = "locations.txt"


class Spell:
    def __init__(self, project, task=None):
        console("Warming up")
        self.project = project
        self.task = task

        projectDir = f"projects/{project}"
        initTree(projectDir, fresh=False)
        self.projectDir = projectDir

        symspell = SymSpell(2, 7)
        dictionaryPath = "frequency_dictionary_en_82_765.txt"
        bigramPath = "frequency_bigramdictionary_en_243_342.txt"
        symspell.load_dictionary(dictionaryPath, 0, 1)
        symspell.load_bigram_dictionary(bigramPath, 0, 2)
        self.symspell = symspell

        with open(f"{projectDir}/allowed.txt") as fh:
            self.allowed = {x for line in fh if (x := line.strip())}
        with open(f"{projectDir}/allowed.txt", "w") as fh:
            text = "\n".join(sorted(self.allowed, key=lambda x: x.lower()))
            fh.write(f"{text}\n")

        ignoreDirs = []
        ignoreFiles = []

        with open(f"{projectDir}/xxxDir.txt") as fh:
            ignoreDirs = [x for line in fh if (x := line.strip())]

        with open(f"{projectDir}/xxxFile.txt") as fh:
            ignoreFiles = [re.compile(x) for line in fh if (x := line.strip())]

        self.ignoreDirs = ignoreDirs
        self.ignoreFiles = ignoreFiles

        self.words = {}
        self.wrong = {}
        self.stats = {}
        self.messages = {}

    def checkAll(self):
        ignoreDirs = self.ignoreDirs
        ignoreFiles = self.ignoreFiles
        project = self.project
        givenTask = self.task
        projectDir = self.projectDir
        taskFile = f"{projectDir}/tasks.txt"
        stats = self.stats
        words = self.words
        wrong = self.wrong
        messages = self.messages

        incomingTotal = 0
        filteredTotal = 0
        filesTotal = 0

        if not fileExists(taskFile):
            console(f"No task.txt file in project {project}. Nothing to do!")
            return

        console("Reading all tasks", newline=False)

        with open(taskFile) as fh:
            tasks = [x for t in fh if not (x := t.strip()).startswith("#")]
            self.tasks = []

        for t, task in enumerate(tasks):
            if givenTask is not None and t + 1 != givenTask:
                continue

            src = abspath(ex(task)).removesuffix("/")
            srcx = ux(src)
            srcIsFile = isFile(src)
            srcIsDir = isDir(src)
            theseStats = {}
            stats[task] = theseStats

            if not (srcIsFile or srcIsDir):
                messages.setdefault(task, []).append(
                    "not an existing file or directory"
                )
                continue

            srcFiles = [
                x.removeprefix(src).removeprefix("/")
                for x in dirAllFiles(src, ignore=ignoreDirs)
                if (x.endswith(".py") or x.endswith(".ipynb") or x.endswith(".md"))
                and not any(pat.search(x) for pat in ignoreFiles)
            ]

            self.tasks.append(srcx)

            console(f" {len(srcFiles)}", newline=False)

            incoming = 0
            filtered = 0
            files = len(srcFiles)

            for srcFile in srcFiles:
                (inc, filt) = self.operation(srcx, srcFile)
                incoming += inc
                filtered += filt

            theseStats["files"] = files
            theseStats["incoming"] = incoming
            theseStats["filtered"] = filtered

            incomingTotal += incoming
            filteredTotal += filtered
            filesTotal += files

        tasks = self.tasks

        task = "TOTAL"
        theseStats = {}
        stats[task] = theseStats
        theseStats["files"] = filesTotal
        theseStats["incoming"] = incomingTotal
        theseStats["filtered"] = filteredTotal

        console(" done")
        console("Performing spellcheck on all tasks ...")

        self.check()

        console("Delivering results of all tasks ...")

        self.deliver()

        console(
            f"{'n':>3} | {'task':<40} | {'files':>5} | {'lines':>6} | {'text':>6} "
            f"| {'words':>5} | {'wrong':>5} | {'occs':>6}"
        )
        sepLine = (
            f"{'-' * 3} | {'-' * 40} | {'-' * 5} | {'-' * 6} | {'-' * 6} "
            f"| {'-' * 5} | {'-' * 5} | {'-' * 6}"
        )
        console(sepLine)

        for i, task in enumerate(tasks + ["TOTAL"]):
            theseStats = stats[task]
            files = theseStats["files"]
            incoming = theseStats["incoming"]
            filtered = theseStats["filtered"]

            all = 0
            wrongs = 0
            locations = 0

            isTotal = task == "TOTAL"

            if isTotal:
                console(sepLine)

            for word in words:
                info = words[word]
                if not isTotal and task not in info:
                    continue

                all += 1

                if word in wrong:
                    wrongs += 1
                    occs = list(info.values()) if isTotal else [info[task]]

                    for theseOccs in occs:
                        for names in theseOccs.values():
                            locations += len(names)

            iRep = "" if isTotal else (i + 1)
            console(
                f"{iRep:>3} | {task:<40} | {files:>5} | {incoming:>6} | {filtered:>6} "
                f"| {all:>5} | {wrongs:>5} | {locations:>6}"
            )

        if len(messages):
            console("Errors and warnings:")

            for task, msgs in messages.items():
                console(f"{task}:")
                for msg in msgs:
                    console(msg)
                console("")
        else:
            console("All went well.")

    def operation(self, srcx, srcFile):
        isPy = srcFile.endswith(".py")
        isMd = srcFile.endswith(".md")
        isIpynb = srcFile.endswith(".ipynb")

        if not isPy and not isMd and not isIpynb:
            return (0, 0)

        srcFileF = f"{ex(srcx)}/{srcFile}"

        messages = self.messages
        chunks = {}

        with open(srcFileF) as fh:
            incoming = 0
            filtered = 0

            if isMd:
                dstLines = []

                for line in fh:
                    incoming += 1
                    dstLines.append(apply(line))

                chunks[""] = dstLines

            if isIpynb:
                notebook = nbRead(fh, NO_CONVERT)
                cells = notebook["cells"]

                for cellNr, cell in enumerate(cells):
                    if cell["cell_type"] != "markdown":
                        continue
                    dstLines = []
                    md = cell["source"]

                    for line in md.split("\n"):
                        incoming += 1
                        dstLines.append(apply(line))

                    chunks[cellNr] = dstLines

            if isPy:
                text = fh.read()
                try:
                    code = ast.parse(text)
                except Exception as e:
                    messages.setdefault(srcx, []).append(
                        f"{srcFile}: could not parse: {str(e)}"
                    )
                    return (0, 0)

                for node in ast.walk(code):
                    tp = type(node)
                    isMod = tp is ast.Module
                    isClass = tp is ast.ClassDef
                    isFunc = tp is ast.FunctionDef

                    if not (isMod or isClass or isFunc):
                        continue

                    kind = (
                        ""
                        if isMod
                        else f"class {node.name}"
                        if isClass
                        else f"def {node.name}"
                    )
                    try:
                        docstring = ast.get_docstring(node)
                    except Exception as f:
                        messages.setdefault(srcx, []).append(
                            f"{srcFile}:{kind} docstring problem: {str(f)}"
                        )
                        break

                    if docstring:
                        dstLines = []
                        lines = docstring.split("\n")

                        for line in lines:
                            incoming += 1
                            dstLines.append(apply(line))

                        chunks[kind] = dstLines

        words = self.words

        for name, dstLines in chunks.items():
            text = "\n".join(dstLines)
            text = CMT_RE.sub(" ", text)
            text = ELEM_DEL1_RE.sub(" ", text)
            text = HEAD_COLON_RE.sub(" REFERENCE ", text)
            text = HEADING_RE.sub(headRepl, text)
            text = ALINK_RE.sub(r" LINK ", text)
            text = ILINK_RE.sub(r"LINK ", text)
            text = LINK_RE.sub(linkRepl, text)
            text = NLINK_RE.sub(r" LINK ", text)
            text = TTTICK_RE.sub("\nCODE\n", text)
            text = MATHD_RE.sub(" MATH ", text)
            text = MATHA_RE.sub(" MATH ", text)
            text = MATH_RE.sub(" MATH ", text)
            text = BRACES_RE.sub(" VAR ", text)

            good = True

            for i, line in enumerate(text.split("\n")):
                tc = line.count("`")
                if tc % 2 == 1:
                    good = False
                    messages.setdefault(srcx, []).append(
                        f"{srcFile}:{i + 1} odd number ({tc}) of ticks in: {line}"
                    )

            if good:
                text = TTICK_RE.sub(" CODE ", text)
                text = TICK_RE.sub(" CODE ", text)
            else:
                messages.setdefault(srcx, []).append(
                    f"{srcFile}: No `code` replacement because of unmatched `s"
                )

            text = SYM_RE.sub("", text)
            text = ELEM_DEL2_RE.sub(" ", text)
            text = ELEM_UNWRAP_RE.sub(" ", text)

            for line in text.split("\n"):
                line = line.strip()
                if line == "":
                    continue

                filtered += 1

                for word in {word for word in WORD_RE.findall(line)}:
                    if (
                        word.isnumeric()
                        or HEX_RE.match(word)
                        or NUM_PL.match(word)
                        or SIZES_RE.match(word)
                        or INITIALS_RE.match(word)
                    ):
                        continue
                    words.setdefault(word, {}).setdefault(srcx, {}).setdefault(
                        srcFile, set()
                    ).add(name)

        return (incoming, filtered)

    def check(self):
        symspell = self.symspell
        allowed = self.allowed
        words = self.words
        wrong = self.wrong

        for word in sorted(words):
            if word in allowed:
                continue

            suggestions = list(
                symspell.lookup(
                    word, Verbosity.TOP, max_edit_distance=2, transfer_casing=True
                )
            )
            corr = "XX" if len(suggestions) == 0 else suggestions[0].term

            if len(suggestions) == 0 or word != corr:
                wrong[word] = corr

    def deliver(self):
        projectDir = self.projectDir
        words = self.words
        wrong = self.wrong

        summaryFile = f"{projectDir}/{SUMMARY_FILE}"
        locationsFile = f"{projectDir}/{LOCATIONS_FILE}"

        self.lastSrcx = None

        with open(summaryFile, "w") as sh:
            with open(locationsFile, "w") as lh:
                for word in sorted(wrong, key=lambda x: x.lower()):
                    self.deliverOccs(word, words[word], lh)
                    sh.write(f"{word}\n")
                lh.write("\n")

    def deliverOccs(self, word, occs, fh):
        lastSrcx = self.lastSrcx

        for srcx, info in occs.items():
            if srcx != lastSrcx:
                fh.write(f"={srcx}\n")
                lastSrcx = srcx

            for fl, names in sorted(info.items()):
                for name in sorted(names):
                    fh.write(
                        f"{word}|{fl}|{str(name) if type(name) is int else (name or 'e')}\n"
                    )

        self.lastSrcx = lastSrcx


def apply(line):
    line = line.strip()

    if RETURN_RE.match(line) or PARAM_RE.match(line):
        line = ""
    elif line.startswith("!!! "):
        line = line[4:]

    line = DOTNAME_RE.sub(" ", line)

    return line


def main(cargs=sys.argv[1:]):
    if len(cargs) not in {1, 2}:
        console(HELP)
        console(f"{len(cargs)} argument(s) passed, instead of 1 or 2")
        return -1

    project = cargs[0]

    if len(cargs) == 2:
        task = cargs[1]
        if task.isdecimal() and not task.startswith("0"):
            task = int(task)
        else:
            console(f"Invalid task task number: {task}")
            return -1
    else:
        task = None

    S = Spell(project, task=task)
    S.checkAll()

    return 0


if __name__ == "__main__":
    sys.exit(main())
