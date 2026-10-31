"""Small OS adapters for owned development child processes and credential ACLs."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import signal
import subprocess

WINDOWS = os.name == "nt"


class PlatformError(Exception):
    """A platform operation required for safe local development failed."""


if WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in (
            "dwSize", "cntUsage", "th32ThreadID", "th32OwnerProcessID",
        )] + [("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
             ("dwFlags", wintypes.DWORD)]

    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _kernel32.Thread32First.restype = wintypes.BOOL
    _kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    _kernel32.Thread32Next.restype = wintypes.BOOL
    _kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenThread.restype = wintypes.HANDLE
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD

    def _resume_owned_primary_thread(pid: int) -> None:
        """Resume only the suspended primary thread after job assignment."""
        snapshot = _kernel32.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            thread_ids = []
            more = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    thread_ids.append(entry.th32ThreadID)
                more = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
            if len(thread_ids) != 1:
                raise PlatformError(f"Expected one suspended thread for owned process {pid}; found {len(thread_ids)}")
            thread = _kernel32.OpenThread(0x0002, False, thread_ids[0])  # THREAD_SUSPEND_RESUME
            if not thread:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if _kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _kernel32.CloseHandle(thread)
        finally:
            _kernel32.CloseHandle(snapshot)

    class WindowsJob:
        """Own a process tree; closing the job terminates any remaining descendants."""

        def __init__(self) -> None:
            self.handle = _kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel32.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error

        def assign(self, process: subprocess.Popen) -> None:
            if not _kernel32.AssignProcessToJobObject(self.handle, process._handle):
                raise ctypes.WinError(ctypes.get_last_error())

        def close(self) -> None:
            if self.handle:
                _kernel32.CloseHandle(self.handle)
                self.handle = None

else:
    WindowsJob = None


def start_owned(args: list[str], cwd: Path, env: dict[str, str]) -> tuple[subprocess.Popen, object | None]:
    """Start one child in an isolated POSIX session or a Windows job/process group."""
    job = WindowsJob() if WINDOWS else None
    try:
        process = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
            start_new_session=not WINDOWS,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004) if WINDOWS else 0,
        )
    except BaseException:
        if job is not None:
            job.close()
        raise
    if job is not None:
        try:
            job.assign(process)
            _resume_owned_primary_thread(process.pid)
        except BaseException as error:
            process.kill()
            process.wait()
            job.close()
            raise PlatformError(f"Could not put owned child in a Windows Job Object: {error}") from error
    return process, job


def request_stop(process: subprocess.Popen) -> None:
    """Ask this child process group to stop, allowing recorder finalization."""
    if WINDOWS:
        if process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError):
                # A later job close still cleans up the owned tree. No clean
                # completion is inferred from a failed graceful request.
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def force_stop(process: subprocess.Popen, job: object | None) -> None:
    """Terminate only the process tree owned by this runner."""
    if WINDOWS:
        if job is not None:
            job.close()
        elif process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# Windows ACLs, not POSIX mode bits, decide who can read the credential. The
# token is written only after a new empty file has a protected DACL. Existing
# files are checked without changing their contents or security descriptor.
_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = [Environment]::GetEnvironmentVariable('FARADIX_CREDENTIAL_PATH', 'Process')
$action = [Environment]::GetEnvironmentVariable('FARADIX_CREDENTIAL_ACTION', 'Process')
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = Get-Acl -LiteralPath $path
if ($action -eq 'protect') {
    $acl.SetOwner($me)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($me, [System.Security.AccessControl.FileSystemRights]::FullControl, [System.Security.AccessControl.AccessControlType]::Allow)
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $path -AclObject $acl
    $acl = Get-Acl -LiteralPath $path
}
$owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier])
if ($owner.Value -ne $me.Value) { throw 'credential owner differs from the current user' }
if (-not $acl.AreAccessRulesProtected) { throw 'credential inherits access rules' }
$allowed = @($me.Value, 'S-1-5-18', 'S-1-5-32-544')
$rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
foreach ($rule in $rules) {
    if ($rule.AccessControlType -eq 'Allow' -and $allowed -notcontains $rule.IdentityReference.Value) {
        throw 'credential grants access to another principal'
    }
}
"""


def credential_acl(path: Path, *, protect: bool) -> None:
    """Protect a new empty Windows token file or verify an existing one."""
    if not WINDOWS:
        return
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise PlatformError("Windows PowerShell is required to verify the credential ACL")
    command = base64.b64encode(_ACL_SCRIPT.encode("utf-16le")).decode("ascii")
    env = {**os.environ, "FARADIX_CREDENTIAL_PATH": str(path),
           "FARADIX_CREDENTIAL_ACTION": "protect" if protect else "verify"}
    try:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        raise PlatformError(f"Could not verify Windows credential ACL: {error}") from error
    if result.returncode != 0:
        # PowerShell error text may contain the path, but never print a token.
        raise PlatformError("Windows credential ACL is not restricted to the current user, SYSTEM, and Administrators")
