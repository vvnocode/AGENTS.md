"""场景准备：在 feature/ellipsis 分支上提交一个带测试的小功能，并停在该分支上。"""
import pathlib
import subprocess


def git(*args):
    subprocess.run(["git", *args], check=True)


git("switch", "-q", "-c", "feature/ellipsis")
pathlib.Path("app/text.py").write_text(
    'def shorten(text, width, ellipsis=""):\n'
    '    if len(text) <= width:\n'
    '        return text\n'
    '    return text[:width - len(ellipsis)] + ellipsis\n', encoding="utf-8")
with open("tests/test_text.py", "a", encoding="utf-8") as f:
    f.write('\n\nclass EllipsisTest(unittest.TestCase):\n'
            '    def test_ellipsis_fits_in_width(self):\n'
            '        self.assertEqual(shorten("abcdef", 4, "…"), "abc…")\n')
git("add", "-A")
git("commit", "-q", "-m", "feat: optional ellipsis when shortening text")
