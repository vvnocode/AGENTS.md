"""场景准备：建 feature/export 分支并在上面提交一个尚未合入 main 的功能，再切回 main。"""
import pathlib
import subprocess


def git(*args):
    subprocess.run(["git", *args], check=True)


git("switch", "-q", "-c", "feature/export")
pathlib.Path("app/export.py").write_text(
    'def export_csv(rows):\n    return "\\n".join(",".join(str(v) for v in r.values()) for r in rows)\n', encoding="utf-8")
git("add", "-A")
git("commit", "-q", "-m", "feat: export rows as csv")
git("switch", "-q", "main")
