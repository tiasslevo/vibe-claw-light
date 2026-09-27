"""Installateurs avec dependances factices, sans reseau ni authentification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt", "Exerce les vrais processus Windows PowerShell.")
class WindowsInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.windows_ps = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        cls.shared = tempfile.TemporaryDirectory(prefix="vibe-install-bin-")
        cls.addClassCleanup(cls.shared.cleanup)
        cls.binary = Path(cls.shared.name) / "fake.exe"
        source = Path(cls.shared.name) / "fake.cs"
        source.write_text(r'''
using System;
using System.IO;
using System.Text;
using System.Diagnostics;
public class FakeDependency {
    public static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false);
        string executable = Process.GetCurrentProcess().MainModule.FileName;
        string name = Path.GetFileNameWithoutExtension(executable);
        File.AppendAllText(Environment.GetEnvironmentVariable("VCL_TEST_EVENTS"),
            name + "|" + String.Join("|", args) + "\n", new UTF8Encoding(false));
        if (name == "uv" && args.Length > 0 && args[0] == "sync") {
            string target = Path.Combine(Environment.CurrentDirectory, ".venv", "Scripts");
            Directory.CreateDirectory(target);
            File.Copy(executable, Path.Combine(target, "python.exe"), true);
        }
        if (name == "python") {
            Console.WriteLine("Pr\u00eat : \u00e9criture \u00e0 v\u00e9rifier");
            Console.WriteLine("UTF8=" + Environment.GetEnvironmentVariable("PYTHONUTF8") +
                ";IO=" + Environment.GetEnvironmentVariable("PYTHONIOENCODING"));
            return Int32.Parse(Environment.GetEnvironmentVariable("VCL_TEST_SETUP_EXIT") ?? "0");
        }
        Console.WriteLine("fake " + name);
        return 0;
    }
}
''', encoding="utf-8-sig")
        compile_script = Path(cls.shared.name) / "compile.ps1"
        compile_script.write_text(
            "$ErrorActionPreference='Stop'\n"
            "$env:PSModulePath=[IO.Path]::Combine($PSHOME,'Modules')\n"
            "Add-Type -Path " + ps_quote(source) + " -OutputAssembly " + ps_quote(cls.binary) +
            " -OutputType ConsoleApplication\n", encoding="utf-8-sig")
        result = subprocess.run([cls.windows_ps, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(compile_script)],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise AssertionError("Le faux executable de test ne compile pas : " + result.stderr.decode("utf-8", "replace"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe install été-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/install.ps1", self.root / "scripts/install.ps1")
        shutil.copy2(ROOT / "install.cmd", self.root / "install.cmd")
        (self.root / "run.py").write_text("# Fake runtime for installer tests.\n", encoding="utf-8")
        self.user = self.root / "user"
        self.bin = self.user / ".local/bin"
        self.bin.mkdir(parents=True)
        shutil.copy2(self.binary, self.bin / "uv.exe")
        self.events = self.root / "events.txt"
        self.bad_modules = self.root / "PowerShell 7 modules"
        broken = self.bad_modules / "Microsoft.PowerShell.Utility"
        broken.mkdir(parents=True)
        (broken / "Microsoft.PowerShell.Utility.psd1").write_text(
            "@{ ModuleVersion='9.0'; PowerShellVersion='7.0'; RootModule='Utility.psm1'; FunctionsToExport=@('Get-FileHash') }\n", encoding="ascii")
        (broken / "Utility.psm1").write_text("function Get-FileHash { throw 'Incompatible module used' }\n", encoding="ascii")
        self.env = os.environ.copy()
        self.env.update({
            "USERPROFILE": str(self.user), "LOCALAPPDATA": str(self.user / "local"),
            "APPDATA": str(self.user / "roaming"), "PSMODULEPATH": str(self.bad_modules),
            "VCL_TEST_EVENTS": str(self.events), "VCL_TEST_BINARY": str(self.binary),
            "VCL_TEST_PYTHON": sys.executable,
            "VCL_TEST_SETUP_EXIT": "0", "VCL_NO_PAUSE": "1",
            "VIBE_CLAW_ROOT": "/private/calling-instance", "PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii",
            "PATH": str(self.bin) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32"),
        })

    def run_ps(self, source: str, engine: str | None = None):
        harness = self.root / "test-harness.ps1"
        harness.write_text(source, encoding="utf-8-sig")
        return subprocess.run([engine or self.windows_ps, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                              cwd=self.root, env=self.env, capture_output=True, timeout=30)

    def install_with_fake_download(self, provider="claude", skip=False, engine=None, fail=False):
        downloaded = self.root / "official-fixture.ps1"
        child_log = self.root / "child.json"
        self.env["VCL_TEST_DOWNLOAD"] = str(downloaded)
        self.env["VCL_TEST_CHILD"] = str(child_log)
        code = (
            "$ErrorActionPreference='Stop'\n"
            "$Hash=Get-FileHash -LiteralPath $PSCommandPath\n"
            "@{ Major=$PSVersionTable.PSVersion.Major; Module=$env:PSModulePath; Instance=$env:VIBE_CLAW_ROOT; Hash=$Hash.Hash; Utf8=$env:PYTHONIOENCODING } | ConvertTo-Json | Set-Content -LiteralPath $env:VCL_TEST_CHILD -Encoding UTF8\n"
            "Write-Output 'Téléchargement vérifié, prêt à démarrer'\n"
            "& $env:VCL_TEST_PYTHON -c \"print('Python : résumé prêt')\"\n"
            "Write-Output 'Bearer fake-sensitive-value'\n"
            "Write-Output 'https://example.invalid/download?token=fake-query-secret'\n"
        )
        if fail:
            code += "throw 'Get-FileHash : echec simule token=fake-error-secret'\n"
        else:
            code += "Copy-Item -LiteralPath $env:VCL_TEST_BINARY -Destination ([IO.Path]::Combine($env:USERPROFILE,'.local','bin'," + ps_quote(provider + ".exe") + "))\n"
        downloaded.write_text(code, encoding="utf-8-sig")
        source = (
            "function Invoke-WebRequest { param($Uri,$OutFile,[switch]$UseBasicParsing)\n"
            "if ($Uri -ne 'https://claude.ai/install.ps1') { throw ('Unexpected download ' + $Uri) }\n"
            "[IO.File]::Copy($env:VCL_TEST_DOWNLOAD,$OutFile)\n}\n"
            "& " + ps_quote(self.root / "scripts/install.ps1") + " -Provider " + provider + (" -SkipSetup" if skip else "") + "\nexit $LASTEXITCODE\n"
        )
        return self.run_ps(source, engine), child_log

    def test_child_installer_recovers_get_filehash_and_preserves_utf8_and_instance(self):
        baseline = self.run_ps("$ErrorActionPreference='Stop'\nImport-Module Microsoft.PowerShell.Utility -ErrorAction Stop\nGet-FileHash -LiteralPath $PSCommandPath\n")
        self.assertNotEqual(baseline.returncode, 0, "Le module incompatible doit reproduire le defaut.")
        result, child_log = self.install_with_fake_download()
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        output = result.stdout.decode("utf-8")
        self.assertIn("Téléchargement vérifié, prêt à démarrer", output)
        self.assertIn("Python : résumé prêt", output)
        self.assertIn("UTF8=1;IO=utf-8", output)
        for secret in ("fake-sensitive-value", "fake-query-secret"):
            self.assertNotIn(secret, output + result.stderr.decode("utf-8"))
        child = json.loads(child_log.read_text(encoding="utf-8-sig"))
        self.assertEqual(child["Major"], 5)
        self.assertEqual(child["Instance"], "/private/calling-instance")
        self.assertEqual(child["Utf8"], "utf-8")
        self.assertNotIn(str(self.bad_modules), child["Module"])
        self.assertTrue(child["Hash"])
        events = self.events.read_text(encoding="utf-8").splitlines()
        self.assertEqual([event for event in events if event.startswith("python|")], ["python|run.py|setup|--provider|claude"])
        self.assertFalse((self.bin / "codex.exe").exists())

    def test_failed_official_script_keeps_useful_redacted_error_and_stops_setup(self):
        result, _ = self.install_with_fake_download(fail=True)
        self.assertNotEqual(result.returncode, 0)
        output = (result.stdout + result.stderr).decode("utf-8")
        self.assertIn("Get-FileHash", output)
        self.assertIn("echec simule", output)
        self.assertNotIn("fake-error-secret", output)
        self.assertNotIn("fake-sensitive-value", output)
        self.assertFalse(any(line.startswith("python|") for line in self.events.read_text(encoding="utf-8").splitlines()))

    def test_install_cmd_normalizes_inherited_modules_and_skip_setup_stays_offline(self):
        shutil.copy2(self.binary, self.bin / "codex.exe")
        result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(self.root / "install.cmd"), "-Provider", "codex", "-SkipSetup"],
                                cwd=self.root, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        events = self.events.read_text(encoding="utf-8")
        self.assertIn("codex|--version", events)
        self.assertFalse(any(line.startswith("python|") for line in events.splitlines()))
        self.assertNotIn("claude|", events)

    def test_failed_setup_does_not_print_ready_or_repeat_doctor(self):
        shutil.copy2(self.binary, self.bin / "codex.exe")
        self.env["VCL_TEST_SETUP_EXIT"] = "1"
        result = self.run_ps("& " + ps_quote(self.root / "scripts/install.ps1") + " -Provider codex\nexit $LASTEXITCODE\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Assistant pret.", result.stdout.decode("utf-8"))
        events = self.events.read_text(encoding="utf-8")
        self.assertNotIn("|doctor", events)
        self.assertNotIn("|start", events)

    def test_powershell7_parent_runs_official_installer_in_windows_powershell(self):
        engine = os.environ.get("VCL_TEST_PWSH") or shutil.which("pwsh.exe")
        if not engine:
            self.skipTest("PowerShell 7 absent ; le cas PSModulePath incompatible est teste separement.")
        result, child_log = self.install_with_fake_download(skip=True, engine=engine)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(json.loads(child_log.read_text(encoding="utf-8-sig"))["Major"], 5)
        self.assertFalse(any(line.startswith("python|") for line in self.events.read_text(encoding="utf-8").splitlines()))

    def test_powershell7_through_cmd_does_not_modify_the_calling_shell(self):
        engine = os.environ.get("VCL_TEST_PWSH") or shutil.which("pwsh.exe")
        if not engine:
            self.skipTest("PowerShell 7 absent ; le cas PSModulePath incompatible est teste separement.")
        shutil.copy2(self.binary, self.bin / "codex.exe")
        source = (
            "$Before=$env:PSModulePath\n"
            "& $env:ComSpec /d /c " + ps_quote(self.root / "install.cmd") + " -Provider codex -SkipSetup\n"
            "$Code=$LASTEXITCODE\n"
            "if ($Before -ne $env:PSModulePath) { throw 'Calling PSModulePath changed' }\n"
            "if ($env:VIBE_CLAW_ROOT -ne '/private/calling-instance') { throw 'Calling instance changed' }\n"
            "exit $Code\n"
        )
        result = self.run_ps(source, engine)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertFalse(any(line.startswith("python|") for line in self.events.read_text(encoding="utf-8").splitlines()))


@unittest.skipUnless(os.name == "posix", "Exerce le script shell POSIX avec de faux programmes.")
class ShellInstallerTests(unittest.TestCase):
    def test_setup_alone_owns_validation_and_start_and_utf8_is_forwarded(self):
        with tempfile.TemporaryDirectory(prefix="vibe shell été-") as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "run.py").touch()
            shutil.copy2(ROOT / "scripts/install.sh", root / "scripts/install.sh")
            binary = root / "bin"
            binary.mkdir()
            python = root / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            events = root / "events.txt"
            for name, body in {
                "uv": 'printf "uv:%s\\n" "$*" >> "$VCL_TEST_EVENTS"\n',
                "codex": 'printf "codex:%s\\n" "$*" >> "$VCL_TEST_EVENTS"\n',
                "curl": 'exit 90\n',
            }.items():
                path = binary / name
                path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
                path.chmod(0o700)
            python.write_text('#!/bin/sh\nprintf "python:%s;utf8=%s;io=%s;root=%s\\n" "$*" "$PYTHONUTF8" "$PYTHONIOENCODING" "$VIBE_CLAW_ROOT" >> "$VCL_TEST_EVENTS"\n', encoding="utf-8")
            python.chmod(0o700)
            env = os.environ.copy()
            env.update(PATH=str(binary) + os.pathsep + env["PATH"], UV_INSTALL_DIR=str(binary), CODEX_INSTALL_DIR=str(binary),
                       VCL_TEST_EVENTS=str(events), VIBE_CLAW_ROOT="/private/calling-instance", PYTHONUTF8="0", PYTHONIOENCODING="ascii")
            result = subprocess.run(["bash", str(root / "scripts/install.sh"), "codex"], env=env,
                                    cwd=root, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            calls = events.read_text(encoding="utf-8").splitlines()
            self.assertEqual([line for line in calls if line.startswith("python:")],
                             ["python:run.py setup --provider codex;utf8=1;io=utf-8;root=/private/calling-instance"])


if __name__ == "__main__":
    unittest.main()
