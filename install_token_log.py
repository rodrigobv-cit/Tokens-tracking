#!/usr/bin/env python3
"""token-log kit installer (single file, no dependencies beyond Python 3.8+).

Installs a Claude Code hook that logs real token usage per tool call, the
`token-log` skill (reports with cost, skills flow, tool flow, suggestions) and
the /token-start, /token-end, /token-span, /token-report slash commands.

Usage:
  python3 install_token_log.py              install or update
  python3 install_token_log.py --check      show what is installed
  python3 install_token_log.py --dry-run    show what would change, change nothing
  python3 install_token_log.py --uninstall  remove (keeps your log)
  python3 install_token_log.py --uninstall --purge --yes   also delete log and reports

Options:
  --config-dir DIR   Claude config folder (default: $CLAUDE_CONFIG_DIR or ~/.claude)
  --python CMD       interpreter the hook should use (default: first of python3,
                     python, this interpreter that passes the self-test)
  --no-settings      do not touch settings.json (merge the hooks by hand)
  --no-test          skip the end-to-end self-test

Version 1.0.0, built 2026-10-31. The embedded payload is verified by SHA-256.
"""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

VERSION = "1.0.0"
BUILT = "2026-10-31"
SHA256 = "653940733ad723f67b3add557951454e5798caf92913e41509616341dfbf9ffd"
MARKER = "log_tokens.py"
EVENTS = ["PostToolUse", "Stop"]
IS_WINDOWS = os.name == "nt"

PAYLOAD = """
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
AAAAAAAApAEAAAAAaG9va3MvbG9nX3Rva2Vucy5weVBLAQIUAxQAAAAIAAAAIVzVkevDWAkAANcTAAAZAAAAAAAAAAAAAACkASoJ
AABza2lsbHMvdG9rZW4tbG9nL1NLSUxMLm1kUEsBAhQDFAAAAAgAAAAhXA/Otz7QAgAAFAoAAB0AAAAAAAAAAAAAAKQBuRIAAHNr
aWxscy90b2tlbi1sb2cvcHJpY2luZy5qc29uUEsBAhQDFAAAAAgAAAAhXG8QfHMqCwAAHRsAACIAAAAAAAAAAAAAAKQBxBUAAHNr
aWxscy90b2tlbi1sb2cvc2NyaXB0cy9hZHZpY2UucHlQSwECFAMUAAAACAAAACFcl+pVj7UFAABLDwAAIwAAAAAAAAAAAAAApAEu
IQAAc2tpbGxzL3Rva2VuLWxvZy9zY3JpcHRzL2Nvc3RpbmcucHlQSwECFAMUAAAACAAAACFc6/X5lDAoAACdhAAAJAAAAAAAAAAA
AAAApAEkJwAAc2tpbGxzL3Rva2VuLWxvZy9zY3JpcHRzL3JlYWRfbG9nLnB5UEsBAhQDFAAAAAgAAAAhXCfEXqnfAAAAWwEAABUA
AAAAAAAAAAAAAKQBlk8AAGNvbW1hbmRzL3Rva2VuLWVuZC5tZFBLAQIUAxQAAAAIAAAAIVwnYkTNUQEAAEICAAAYAAAAAAAAAAAA
AACkAahQAABjb21tYW5kcy90b2tlbi1yZXBvcnQubWRQSwECFAMUAAAACAAAACFcR+YcWd0AAABXAQAAFgAAAAAAAAAAAAAApAEv
UgAAY29tbWFuZHMvdG9rZW4tc3Bhbi5tZFBLAQIUAxQAAAAIAAAAIVxnMP1XyQAAADcBAAAXAAAAAAAAAAAAAACkAUBTAABjb21t
YW5kcy90b2tlbi1zdGFydC5tZFBLBQYAAAAACgAKANgCAAA+VAAAAAA=
"""


# ---------------------------------------------------------------- payload
def open_payload():
    data = base64.b64decode("".join(PAYLOAD.split()))
    if hashlib.sha256(data).hexdigest() != SHA256:
        sys.exit("Installer payload is corrupted (checksum mismatch). Download the installer again.")
    return zipfile.ZipFile(io.BytesIO(data))


def safe_target(cfg, name):
    """Map a zip entry to a path inside cfg; refuse anything that escapes it."""
    parts = Path(name).parts
    if not parts or ".." in parts or Path(name).is_absolute():
        sys.exit(f"Refusing unsafe path in payload: {name}")
    return cfg.joinpath(*parts)


# ---------------------------------------------------------------- helpers
def config_dir(args):
    raw = args.config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(raw).expanduser().resolve()


def q(text):
    text = str(text)
    return f'"{text}"' if " " in text else text


def log_path(cfg):
    return Path(os.environ.get("CLAUDE_TOKEN_LOG", cfg / "token-log.jsonl"))


def say(msg=""):
    print(msg)


# ---------------------------------------------------------------- settings.json
def load_settings(path):
    if path.exists() and path.read_text(encoding="utf-8").strip():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"{path} is not valid JSON ({e}).\nFix it first, or re-run with --no-settings. Nothing was changed.")
    return {}


def has_ours(group):
    return any(MARKER in h.get("command", "") for h in group.get("hooks", []))


def add_hooks(settings, command):
    hooks = settings.setdefault("hooks", {})
    changed = False
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        for g in groups:
            if has_ours(g):  # already registered: refresh the command in case the interpreter changed
                for h in g["hooks"]:
                    if MARKER in h.get("command", "") and h.get("command") != command:
                        h["command"] = command
                        changed = True
                break
        else:
            group = {"hooks": [{"type": "command", "command": command}]}
            if event == "PostToolUse":
                group["matcher"] = "*"
            groups.append(group)
            changed = True
    return changed


def remove_hooks(settings):
    hooks = settings.get("hooks", {})
    changed = False
    for event in list(hooks):
        kept = []
        for g in hooks[event]:
            if has_ours(g):
                changed = True
                rest = [h for h in g["hooks"] if MARKER not in h.get("command", "")]
                if rest:
                    kept.append(dict(g, hooks=rest))
            else:
                kept.append(g)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if "hooks" in settings and not settings["hooks"]:
        del settings["hooks"]
    return changed


def save_settings(path, settings):
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        say(f"  backup:   {backup}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- self-test
def self_test(cfg, py):
    """Run the installed hook and reader end to end on a throwaway transcript and log."""
    exe = shutil.which(py) or (py if Path(py).exists() else None)
    if not exe:
        return False, f"'{py}' was not found on PATH"
    hook = cfg / "hooks" / "log_tokens.py"
    reader = cfg / "skills" / "token-log" / "scripts" / "read_log.py"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        transcript, log = td / "t.jsonl", td / "log.jsonl"
        env = dict(os.environ, CLAUDE_TOKEN_LOG=str(log), CLAUDE_TOKEN_PRICING="")
        env.pop("CLAUDE_TOKEN_PRICING")

        def add_message(mid, out):
            entry = {"type": "assistant", "message": {"id": mid, "model": "claude-sonnet-5-5", "content": [],
                     "usage": {"input_tokens": 5, "output_tokens": out, "cache_read_input_tokens": 100,
                               "cache_creation_input_tokens": 20}}}
            with open(transcript, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        def fire(tool):
            payload = json.dumps({"session_id": "selftest", "transcript_path": str(transcript),
                                  "hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": {}})
            return subprocess.run([exe, str(hook)], input=payload, text=True, env=env,
                                  capture_output=True, timeout=60)

        def run_reader(*a):
            return subprocess.run([exe, str(reader), *a], text=True, env=env, capture_output=True, timeout=60)

        add_message("msg_1", 10)
        p = fire("Read")
        if p.returncode != 0 or not log.exists():
            return False, "the hook did not write a log line " + (p.stderr or "").strip()[:200]
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        if rec.get("context_tokens") != 125:
            return False, f"hook recorded unexpected data: {rec}"
        m = run_reader("--mark", "start", "--name", "selftest")
        if m.returncode != 0:
            return False, "reader failed on --mark: " + (m.stderr or m.stdout).strip()[:200]
        add_message("msg_2", 30)
        fire("Bash")
        r = run_reader("--report", "--name", "selftest", "--no-save")
        if r.returncode != 0 or "# Token window report" not in r.stdout:
            return False, "report failed: " + (r.stderr or r.stdout).strip()[:300]
        if "Estimated cost" not in r.stdout:
            return False, "report ran but the cost section is missing (pricing.json not found?)"
    return True, f"hook, reader and report work with '{py}'"


def choose_python(cfg, args):
    if args.python:
        ok, msg = (True, "not tested") if args.no_test else self_test(cfg, args.python)
        return args.python, ok, msg
    candidates = []
    for c in ("python3", "python", Path(sys.executable).as_posix()):
        if c not in candidates and (shutil.which(c) or Path(c).exists()):
            candidates.append(c)
    if args.no_test:
        return (candidates[0] if candidates else Path(sys.executable).as_posix()), True, "not tested"
    last = "no Python interpreter found"
    for c in candidates:
        ok, msg = self_test(cfg, c)
        if ok:
            return c, True, msg
        last = f"{c}: {msg}"
    return (candidates[0] if candidates else "python3"), False, last


# ---------------------------------------------------------------- commands
def adapt_commands(cfg, py):
    """Point the slash commands at this interpreter and config dir when they differ from the defaults."""
    default_dir = (Path.home() / ".claude").resolve()
    base = "~/.claude" if cfg == default_dir else cfg.as_posix()
    if py == "python3" and base == "~/.claude":
        return
    if " " in base:
        say(f"  note: {base} contains spaces; if a slash command fails, edit its python path by hand.")
    for f in (cfg / "commands").glob("token-*.md"):
        text = f.read_text(encoding="utf-8")
        f.write_text(text.replace("python3 ~/.claude", f"{q(py)} {base}"), encoding="utf-8")


# ---------------------------------------------------------------- actions
def do_install(args):
    cfg = config_dir(args)
    settings_path = cfg / "settings.json"
    settings = None if args.no_settings else load_settings(settings_path)  # fail before touching anything
    zf = open_payload()
    names = [n for n in zf.namelist() if not n.endswith("/")]

    if args.dry_run:
        say(f"[dry run] token-log kit {VERSION} -> {cfg}")
        for n in names:
            say(f"  write {safe_target(cfg, n)}")
        if settings is not None:
            trial = copy.deepcopy(settings)
            changed = add_hooks(trial, "<hook command>")
            say(f"  settings.json: {'hooks would be added' if changed else 'already up to date'}")
        say("[dry run] nothing was changed.")
        return 0

    say(f"Installing token-log kit {VERSION} into {cfg}")
    skill_dir = cfg / "skills" / "token-log"
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    for n in names:
        target = safe_target(cfg, n)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(n))
        if not IS_WINDOWS and target.suffix == ".py":
            target.chmod(0o755)
    (skill_dir / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    say("  hook:     " + str(cfg / "hooks" / MARKER))
    say("  skill:    " + str(skill_dir))
    say("  commands: /token-start /token-end /token-span /token-report")

    py, ok, msg = choose_python(cfg, args)
    adapt_commands(cfg, py)
    if not ok:
        say(f"\nSelf-test FAILED: {msg}")
        say("Files are installed, but the hooks were NOT registered because the hook could not run.")
        say("Fix Python (or pass --python /full/path/to/python) and run the installer again.")
        return 1
    say(f"  self-test: {msg}")

    if settings is not None:
        hook_cmd = f"{q(py)} {q((cfg / 'hooks' / MARKER).as_posix())}"
        if add_hooks(settings, hook_cmd):
            save_settings(settings_path, settings)
            say("  settings: hooks registered in " + str(settings_path))
        else:
            say("  settings: already up to date")
    else:
        say("  settings: skipped (--no-settings); add PostToolUse and Stop hooks that run the hook script.")

    say("\nDone. Restart Claude Code, run any tool, then try:")
    say(f"  {q(py)} {q((skill_dir / 'scripts' / 'read_log.py').as_posix())} --summary")
    say(f"or type /token-start, work, then /token-report.  Log file: {log_path(cfg)}")
    return 0


def do_check(args):
    cfg = config_dir(args)
    say(f"token-log kit installer {VERSION} (built {BUILT}); config dir {cfg}")
    ver = cfg / "skills" / "token-log" / "VERSION"
    say(f"  installed version: {ver.read_text().strip() if ver.exists() else 'not installed'}")
    for label, p in (("hook", cfg / "hooks" / MARKER),
                     ("skill", cfg / "skills" / "token-log" / "SKILL.md"),
                     ("pricing", cfg / "skills" / "token-log" / "pricing.json")):
        say(f"  {label:<8} {'ok' if p.exists() else 'MISSING'}  {p}")
    cmds = sorted(f.name for f in (cfg / "commands").glob("token-*.md")) if (cfg / "commands").exists() else []
    say(f"  commands {', '.join(cmds) if cmds else 'MISSING'}")
    try:
        settings = load_settings(cfg / "settings.json")
    except SystemExit as e:
        say(f"  settings: {e}")
        return 1
    for event in EVENTS:
        reg = any(has_ours(g) for g in settings.get("hooks", {}).get(event, []))
        say(f"  hook registered for {event}: {'yes' if reg else 'NO'}")
    lp = log_path(cfg)
    if lp.exists():
        n = sum(1 for _ in open(lp, encoding="utf-8"))
        say(f"  log: {lp} ({n} line(s), {lp.stat().st_size:,} bytes)")
    else:
        say(f"  log: {lp} (not created yet; it appears after the first tool call)")
    return 0


def do_uninstall(args):
    cfg = config_dir(args)
    if args.purge and not args.yes:
        if sys.stdin.isatty():
            if input(f"Delete the token log and saved reports under {cfg}? [y/N] ").strip().lower() != "y":
                say("Cancelled.")
                return 1
        else:
            sys.exit("--purge deletes data; add --yes to confirm.")
    settings_path = cfg / "settings.json"
    if not args.no_settings and settings_path.exists():
        settings = load_settings(settings_path)
        if remove_hooks(settings):
            save_settings(settings_path, settings)
            say("  settings: hooks removed")
        else:
            say("  settings: no token-log hooks found")
    (cfg / "hooks" / MARKER).unlink(missing_ok=True) if sys.version_info >= (3, 8) else None
    shutil.rmtree(cfg / "skills" / "token-log", ignore_errors=True)
    for name in ("token-start", "token-end", "token-span", "token-report"):
        (cfg / "commands" / f"{name}.md").unlink(missing_ok=True)
    say("Removed hook, skill and slash commands.")
    if args.purge:
        log_path(cfg).unlink(missing_ok=True)
        shutil.rmtree(cfg / "token-reports", ignore_errors=True)
        say("Deleted the log and saved reports.")
    else:
        say(f"Kept the log at {log_path(cfg)} (use --purge --yes to delete it).")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Install the token-log kit for Claude Code.")
    ap.add_argument("--config-dir")
    ap.add_argument("--python")
    ap.add_argument("--no-settings", action="store_true")
    ap.add_argument("--no-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        say(f"token-log kit installer {VERSION} (built {BUILT})")
        return 0
    if args.check:
        return do_check(args)
    if args.uninstall:
        return do_uninstall(args)
    return do_install(args)


if __name__ == "__main__":
    sys.exit(main())
